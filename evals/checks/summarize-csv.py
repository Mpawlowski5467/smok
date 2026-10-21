import json
from pathlib import Path

value = json.loads(Path("summary.json").read_text())
assert value == {"total_amount": 27.0, "order_count": 4}
