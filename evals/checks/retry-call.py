from retrying import retry

calls = []
error = OSError("temporary")


def flaky():
    calls.append(1)
    if len(calls) < 3:
        raise error
    return 42


assert retry(flaky) == 42 and len(calls) == 3
calls.clear()
try:
    retry(flaky, 2)
except OSError as caught:
    assert caught is error
else:
    raise AssertionError("failure swallowed")
assert len(calls) == 2
calls.clear()


def wrong():
    calls.append(1)
    raise ValueError("stop")


try:
    retry(wrong, 5)
except ValueError:
    pass
else:
    raise AssertionError("wrong failure swallowed")
assert len(calls) == 1
try:
    retry(flaky, 0)
except ValueError:
    pass
else:
    raise AssertionError("zero attempts accepted")
assert len(calls) == 1
