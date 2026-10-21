"""Session planning state; updating it never grants workspace permissions."""

import json
import re


def validate_todos(items):
    if not isinstance(items, list) or len(items) > 30:
        raise ValueError("Todos must be a list of at most 30 items.")
    identifiers = set()
    active = 0
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "text", "status"}:
            raise ValueError("Each todo needs id, text, and status.")
        if not isinstance(item["id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", item["id"]):
            raise ValueError("Todo IDs must be short letters, digits, hyphens, or underscores.")
        if (
            item["id"] in identifiers
            or not isinstance(item["text"], str)
            or not 1 <= len(item["text"]) <= 500
        ):
            raise ValueError("Todo IDs must be unique and text must contain 1–500 characters.")
        if not isinstance(item["status"], str) or item["status"] not in {
            "pending",
            "in_progress",
            "done",
            "blocked",
        }:
            raise ValueError("Invalid todo status.")
        identifiers.add(item["id"])
        active += item["status"] == "in_progress"
    if active > 1:
        raise ValueError("Only one todo may be in progress.")
    return json.loads(json.dumps(items))
