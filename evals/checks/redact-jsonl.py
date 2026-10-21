import copy
import io
import json

from scrub.cli import run
from scrub.core import redact

value = [
    {"PASSWORD": {"deep": "secret"}, "api_key": None, "mytoken": "keep", "Token_count": 2},
    False,
    None,
    7,
]
original = copy.deepcopy(value)
result = redact(value)
assert result == [
    {"PASSWORD": "[REDACTED]", "api_key": "[REDACTED]", "mytoken": "keep", "Token_count": 2},
    False,
    None,
    7,
]
assert value == original and result is not value
out, err = io.StringIO(), io.StringIO()
assert run(io.StringIO(' \nnull\n3\n[true,{"ToKeN":"s"}]\n'), out, err) == 0
assert [json.loads(s) for s in out.getvalue().splitlines()] == [
    None,
    3,
    [True, {"ToKeN": "[REDACTED]"}],
]
assert not err.getvalue()
out, err = io.StringIO(), io.StringIO()
assert run(io.StringIO("\nsecret-invalid\n{}\n"), out, err) == 2
assert err.getvalue() == "line 2: invalid JSON\n" and not out.getvalue()
