import json
from pathlib import Path

value = json.loads(Path("config.json").read_text())
assert value == {
    "server": {"host": "127.0.0.1", "port": 8080},
    "features": {"cache": True, "telemetry": False},
    "name": "fixture",
}
