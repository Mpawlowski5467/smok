"""Bounded journal projections for browsers, external CLI watchers, and snapshots."""

import json
import re
from collections import deque

from smok.journal import ID_PATTERN, MAX_RECORD, MAX_SESSION
from smok.state import state_path
from smok.types import Event, messages_from_data


def append_event(events, event):
    item = event.to_dict() if isinstance(event, Event) else event
    if item["type"] == "text_delta":
        if (
            events
            and events[-1]["type"] == "text_delta"
            and events[-1]["data"].get("worker") == item["data"].get("worker")
        ):
            events[-1] = {
                **item,
                "data": {
                    **item["data"],
                    "text": (events[-1]["data"]["text"] + item["data"]["text"])[-100_000:],
                },
            }
            return
    events.append(item)


def journal_view(root, identifier, *, checkpoint=None):
    if not re.fullmatch(ID_PATTERN, identifier):
        raise ValueError("Invalid session ID.")
    path = state_path(root, "sessions", identifier + ".jsonl")
    if path.stat().st_size > MAX_SESSION:
        raise ValueError("Session exceeds 256 MiB.")
    events, state, selected = deque(maxlen=400), None, None
    finished = None
    title, count = "New session", 0
    with path.open("rb") as stream:
        while raw := stream.readline(MAX_RECORD + 1):
            if len(raw) > MAX_RECORD:
                raise ValueError("Session record exceeds 16 MiB.")
            if not raw.endswith(b"\n"):
                break
            item = json.loads(raw)
            if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
                raise ValueError("Invalid session record.")
            kind, data = item.get("type"), item["data"]
            if not count and (kind != "session_started" or data.get("workspace") != str(root)):
                raise ValueError("Session belongs to another workspace.")
            count += 1
            if kind == "session_state":
                state = data
                if finished == checkpoint and selected is None:
                    selected = data
                continue
            if kind == "checkpoint_finished":
                finished = data.get("id")
            if kind == "branch_created":
                title = data.get("title", "Branched session")[:100]
            if kind == "turn_started" and not data.get("internal") and title == "New session":
                title = data.get("prompt", "New session")[:90]
            append_event(events, item)
    state = selected if checkpoint is not None else state
    if state:
        messages_from_data(state.get("messages"))
    return {
        "id": identifier,
        "title": title,
        "state": state,
        "events": list(events),
        "record_count": count,
        "truncated_events": count > 400,
    }


def share_projection(view, *, include_tools=False):
    # Sharing is deliberately an explicit text export. No image bytes, keys, pins,
    # workspace paths, approval grants, raw events, or artifact URLs are exported.
    messages = []
    for message in (view.get("state") or {}).get("messages", []):
        blocks = []
        for b in message["content"]:
            if b["type"] == "text":
                blocks.append({"type": "text", "text": b["text"]})
            elif b["type"] == "image":
                blocks.append({"type": "text", "text": "[Image omitted from share]"})
            elif include_tools:
                blocks.append(b)
        if blocks:
            messages.append({"role": message["role"], "content": blocks})
    result = {"title": view["title"], "messages": messages, "read_only": True}
    if len(json.dumps(result).encode()) > 2_000_000:
        raise ValueError("Share exceeds 2 MB; shorten the session first.")
    return result
