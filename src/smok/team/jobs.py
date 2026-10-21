"""Session-owned background shells with bounded output and process-group cleanup."""

import asyncio
import contextlib
import json
import os
import signal
import time
from uuid import uuid4

from smok.process import capture
from smok.tools.files import ToolError
from smok.tools.shell import docker_command


class Jobs:
    def __init__(self, registry):
        self.registry = registry
        self.jobs = {}

    async def start(self, command, timeout_seconds=600):
        if len(self.jobs) >= 32 or sum(not j["task"].done() for j in self.jobs.values()) >= 4:
            raise ToolError("Background job limit reached (4 running, 32 per session).")
        root, sandbox = self.registry.workspace.root, self.registry.sandbox
        identifier = uuid4().hex[:12]
        container = "smok-job-" + identifier
        argv = (
            docker_command(command, root, sandbox, container)
            if sandbox.backend == "docker"
            else ["/bin/sh", "-c", command]
        )
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        job = {
            "id": identifier,
            "command": command,
            "process": process,
            "output": bytearray(),
            "total": 0,
            "status": "running",
            "started": time.monotonic(),
            "exit_code": None,
        }
        self.jobs[identifier] = job

        async def monitor():
            async def drain():
                while chunk := await process.stdout.read(8192):
                    job["total"] += len(chunk)
                    job["output"].extend(chunk)
                    del job["output"][:-65536]

            reader = asyncio.create_task(drain())
            try:
                async with asyncio.timeout(timeout_seconds):
                    await process.wait()
                    await reader
                job["status"] = "finished"
            except TimeoutError:
                job["status"] = "timed_out"
            except asyncio.CancelledError:
                job["status"] = "stopped"
                raise
            finally:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
                reader.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader
                if sandbox.backend == "docker":
                    with contextlib.suppress(OSError):
                        await capture(["docker", "rm", "-f", container], root, seconds=10)
                job["exit_code"] = process.returncode
                self.registry.workspace.read_hashes.clear()
                self.registry.revision += 1
                self.registry.shell_evidence.append(
                    {
                        "background_job": identifier,
                        "command": command,
                        "ok": job["status"] == "finished" and process.returncode == 0,
                        "output": bytes(job["output"][-2000:]).decode("utf-8", errors="replace"),
                    }
                )

        job["task"] = asyncio.create_task(monitor())
        # Let monitor enter its try/finally before a caller can immediately stop it.
        await asyncio.sleep(0)
        return self.poll(identifier)

    def poll(self, id=None, offset=0):
        if id is None:
            return json.dumps({"jobs": [self.row(j) for j in self.jobs.values()]})
        job = self.get(id)
        start = job["total"] - len(job["output"])
        actual = max(start, min(offset, job["total"]))
        data = bytes(job["output"][actual - start : actual - start + 12000])
        return json.dumps(
            {
                **self.row(job),
                "output": data.decode("utf-8", errors="replace"),
                "offset": actual,
                "next_offset": actual + len(data),
                "lost_bytes": max(0, start - offset),
            }
        )

    def get(self, id):
        if id not in self.jobs:
            raise ToolError("Unknown job ID; jobs belong to this running session only.")
        return self.jobs[id]

    def row(self, job):
        return {k: job[k] for k in ("id", "command", "status", "exit_code", "total")}

    async def stop(self, id):
        task = self.get(id)["task"]
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return self.poll(id)

    async def close(self):
        for id in self.jobs:
            await self.stop(id)
