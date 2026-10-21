import os

from config import env_bool

key = "SMOK_EVAL_BOOL"
os.environ.pop(key, None)
assert env_bool(key) is False and env_bool(key, True) is True
for value in ["1", "TRUE", " yes ", "On"]:
    os.environ[key] = value
    assert env_bool(key) is True
for value in ["0", "FALSE", " no ", "Off"]:
    os.environ[key] = value
    assert env_bool(key, True) is False
for value in ["", "maybe", "2"]:
    os.environ[key] = value
    try:
        env_bool(key)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid boolean accepted")
