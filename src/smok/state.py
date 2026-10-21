"""Private per-project metadata; never follow a redirected .smok directory."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def state_path(root: Path, *parts: str) -> Path:
    current = root.resolve() / ".smok"
    for part in ("", *parts):
        if part:
            if part in {".", ".."} or "/" in part or "\\" in part:
                raise ValueError("Invalid metadata path.")
            current = current / part
        if current.is_symlink():
            raise ValueError(f"Smok metadata must not be a symlink: {current.name}")
    return current


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
