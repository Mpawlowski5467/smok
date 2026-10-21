from copy import deepcopy

from releases.catalog import choose
from releases.versions import parse_version


def rejects(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("invalid input accepted")


assert parse_version("0.10.200-rc.0") == (0, 10, 200, 0)
assert parse_version("12.0.3") == (12, 0, 3, None)
for value in (
    None,
    123,
    "",
    "1.2",
    "1.2.3.4",
    "1.02.3",
    "1.2.3-rc.01",
    "1.2.3-rc.-1",
    "1.2.3\n",
    " 1.2.3",
    "+1.2.3",
    "1.2.3-beta.1",
    "１.2.3",
    "1.2.3+build",
):
    rejects(lambda value=value: parse_version(value))
records = [
    {"version": "1.0.0-rc.2", "id": "a"},
    {"version": "1.0.0-rc.10", "id": "b"},
    {"version": "1.0.0", "id": "c"},
    {"version": "1.0.0", "id": "d"},
    {"version": "2.0.0", "yanked": True},
]
before = deepcopy(records)
result = choose(records, True)
assert result == records[2] and result is not records[2]
assert choose(records[:2], True) == records[1]
assert choose(records[:2]) is None
assert choose([{"version": "2.0.0-rc.1"}, {"version": "1.99.99"}], True)["version"] == "2.0.0-rc.1"
assert choose([]) is None and records == before
for bad in (
    None,
    {},
    [None],
    [{}],
    [{"version": "1.0.0", "yanked": 1}],
    [{"version": "BAD", "yanked": True}],
    [{"version": "2.0.0-rc.X"}],
):
    rejects(lambda bad=bad: choose(bad))
rejects(lambda: choose([], 1))
