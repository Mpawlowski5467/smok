from types import SimpleNamespace

from retrieval.client import fetch
from retrieval.policy import delay

for value in ["NaN", "inf", "-1", "bad", None, ""]:
    assert delay({"Retry-After": value}, 2) == 4
assert delay({"RETRY-AFTER": " 0 "}, 3) == 0
assert delay({"Retry-After": "1.5"}, 0) == 1.5
response = SimpleNamespace(status=404, headers={})
calls, sleeps = [], []


def send():
    calls.append(1)
    return response


assert fetch(send, sleeps.append) is response and len(calls) == 1 and sleeps == []
response.status = 503
calls.clear()
assert fetch(send, sleeps.append, 1) is response and len(calls) == 1 and sleeps == []
calls.clear()
assert fetch(send, sleeps.append, 3) is response and len(calls) == 3 and sleeps == [1, 2]
for attempts in [0, -1, True, 1.5, "2"]:
    try:
        fetch(send, sleeps.append, attempts)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid attempts accepted")


def broken():
    raise RuntimeError("transport")


try:
    fetch(broken, sleeps.append)
except RuntimeError as exc:
    assert str(exc) == "transport"
else:
    raise AssertionError("transport exception swallowed")


def bad_sleep(_):
    raise RuntimeError("sleep")


try:
    fetch(send, bad_sleep)
except RuntimeError as exc:
    assert str(exc) == "sleep"
else:
    raise AssertionError("sleep exception swallowed")
