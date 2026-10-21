from launch.cli import options
from launch.config import load_config

env = {"APP_HOST": "bind", "APP_PORT": "1234", "APP_DEBUG": " YES "}
before = dict(env)
assert options([], env) == {"host": "bind", "port": 1234, "debug": True}
assert options(["--host", "", "--port", "1", "--no-debug"], env) == {
    "host": "",
    "port": 1,
    "debug": False,
}
assert env == before
assert load_config({}) == {"host": "localhost", "port": 8000, "debug": False}
for value in [" false ", "0", "NO"]:
    assert load_config({"APP_DEBUG": value})["debug"] is False
for value in ["TRUE", "1", "yes"]:
    assert load_config({"APP_DEBUG": value})["debug"] is True
for value in ["maybe", "", "on"]:
    try:
        load_config({"APP_DEBUG": value})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid boolean accepted")
for value in ["0", "65536", "-1", "1.2", "bad"]:
    try:
        load_config({"APP_PORT": value})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid port accepted")
for value in ["0", "65536"]:
    try:
        options(["--port", value], {})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid CLI port accepted")
