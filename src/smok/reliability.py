"""Turn deadlines and identities for actions denied during the current turn."""

import asyncio
import hashlib
import json
import math
from contextlib import aclosing
from contextvars import ContextVar

_ACTIVE_DEADLINE = ContextVar("smok_active_deadline", default=None)


def deadline_guidance():
    deadline = _ACTIVE_DEADLINE.get()
    if deadline is None:
        return ""
    remaining = max(0, math.ceil(deadline - asyncio.get_running_loop().time()))
    return (
        f"\nTURN TIME BUDGET: approximately {remaining} seconds remain, including model "
        "responses, tools, approvals, and verification. Use the code and diffs already "
        "available; avoid repeated reads of unchanged files. Prioritize the requested change "
        "and required checks, then finish with a concise, truthful result. "
        "Do not skip necessary checks or claim unfinished work is complete to meet the limit.\n"
    )


class TurnDeadlineExceeded(Exception):
    pass


def validate_timeout(value):
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 < value <= 86400
    ):
        raise ValueError("Turn timeout must be a positive number up to 86400 seconds, or null.")
    return value


async def within_deadline(events, deadline):
    # Never leave a timeout context active across yield: it would cancel client code
    # while the client renders an event or waits before requesting the next one.
    async with aclosing(events):
        while True:
            if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                raise TurnDeadlineExceeded
            timer = asyncio.timeout_at(deadline)
            inherited = _ACTIVE_DEADLINE.get()
            deadlines = [d for d in (deadline, inherited) if d is not None]
            token = _ACTIVE_DEADLINE.set(min(deadlines) if deadlines else None)
            try:
                async with timer:
                    event = await anext(events)
            except StopAsyncIteration:
                return
            except TimeoutError as exc:
                if timer.expired():
                    raise TurnDeadlineExceeded from exc
                raise
            finally:
                # The consumer may run another agent between events. Never leak a
                # turn's time budget into client code or an unrelated session.
                _ACTIVE_DEADLINE.reset(token)
            yield event


def denial_key(prepared):
    if prepared.approval_key:
        scope = ["extension", prepared.approval_key]
    elif prepared.write:
        write = prepared.write
        scope = [
            "file",
            str(write.resolved_path),
            write.expected_hash,
            hashlib.sha256(write.content.encode()).hexdigest(),
        ]
    elif prepared.server:
        scope = ["server", list(prepared.server.command)]
    elif prepared.call.name == "run_shell":
        # A different timeout is still the same command. Do not attempt to infer
        # equivalence between different shell programs or quoted arguments.
        scope = ["shell", prepared.arguments["command"]]
    else:
        scope = [prepared.call.name, prepared.arguments]
    return hashlib.sha256(
        json.dumps([prepared.workspace, scope], sort_keys=True).encode()
    ).hexdigest()
