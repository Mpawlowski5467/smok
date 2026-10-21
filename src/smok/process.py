"""Bounded subprocess capture and process-group cleanup for local tools."""

import asyncio
import contextlib
import os
import signal
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    code: int
    output: bytes
    truncated: bool
    timed_out: bool


async def capture(
    argv: list[str],
    root: Path,
    *,
    seconds: float = 30,
    limit: int = 24_000,
    input_data: bytes | None = None,
) -> ProcessResult:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.PIPE if input_data is not None else asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    output = bytearray()
    total = 0

    async def drain():
        nonlocal total
        assert process.stdout is not None
        while chunk := await process.stdout.read(8192):
            total += len(chunk)
            output.extend(chunk[: max(0, limit - len(output))])

    reader = asyncio.create_task(drain())

    async def feed():
        if process.stdin is not None:
            try:
                process.stdin.write(input_data or b"")
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

    writer = asyncio.create_task(feed())
    timed_out = False
    try:
        async with asyncio.timeout(seconds):
            await process.wait()
            await reader
            await writer
    except TimeoutError:
        timed_out = True
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
        if not reader.done():
            reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader
        if not writer.done():
            writer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await writer
    return ProcessResult(process.returncode, bytes(output), total > len(output), timed_out)
