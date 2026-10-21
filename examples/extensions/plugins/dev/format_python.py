"""Optional hook example. Requires Ruff on the selected shell backend's PATH."""

import json
import subprocess
import sys

event = json.load(sys.stdin)
path = event["arguments"]["path"]
if not event["is_error"] and path.endswith((".py", ".pyi")):
    subprocess.run(["ruff", "format", "--", path], check=True)
