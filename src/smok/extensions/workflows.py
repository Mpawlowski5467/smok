"""Client-side workflows built from the same bounded Agent.run stream."""

import json
import shlex
from contextlib import aclosing
from uuid import uuid4

from smok.extensions.review import review_prompt
from smok.tools.files import ToolError
from smok.types import Event, Message, Text, ToolCall


def parameters(items):
    result = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not key or key in result:
            raise ToolError("Use unique name=value parameters.")
        result[key] = value
    return result


def invocation(text):
    parts = shlex.split(text)
    if not parts:
        raise ToolError("Specify an extension name.")
    values = parameters([part for part in parts[1:] if "=" in part])
    args = " ".join(part for part in parts[1:] if "=" not in part)
    return parts[0], values, args


async def run_extension(agent, kind, name, values=None, args=""):
    prompts = agent.tools.extensions.catalog.render(kind, name, values, args)
    for number, prompt in enumerate(prompts, 1):
        if kind == "recipes":
            yield Event(
                "recipe_step_started", {"name": name, "step": number, "total": len(prompts)}
            )
        success = False
        async with aclosing(agent.run(prompt)) as stream:
            async for event in stream:
                yield event
                if event.type == "turn_finished":
                    success = event.data["reason"] == "complete"
                if kind == "recipes" and event.type == "tool_result" and event.data["is_error"]:
                    yield Event(
                        "recipe_stopped",
                        {"name": name, "step": number, "reason": "A tool failed or was denied."},
                    )
                    yield Event("turn_finished", {"reason": "recipe_step_failed"})
                    return
        if kind == "recipes":
            yield Event("recipe_step_finished", {"name": name, "step": number, "ok": success})
        if not success:
            return


async def run_review(agent, base=None):
    mode = agent.tools.mode
    agent.set_mode("plan")
    try:
        async with aclosing(agent.run(review_prompt(base))) as stream:
            async for event in stream:
                yield event
    finally:
        agent.set_mode(mode)
        agent.save()


async def connect_mcp(agent, server):
    call = ToolCall(uuid4().hex, "mcp_connect", json.dumps({"server": server}))
    prepared = agent.tools.prepare(call)
    approved = agent.policy.allowed(prepared)
    source = "saved policy"
    if not approved:
        yield Event("permission_requested", prepared.permission_data())
        decision = await agent.approver(prepared)
        approved = decision is True or decision == "always"
        if decision == "always":
            agent.policy.remember(prepared)
        source = "user"
    yield Event("permission_resolved", {"id": call.id, "approved": approved, "source": source})
    result = await agent.tools.execute(prepared, approved=approved)
    agent.messages.append(
        Message(
            "user", [Text("The user connected an MCP server. Discovered tool metadata:\n" + result)]
        )
    )
    agent.save()
    yield Event("extension_report", {"result": result})
