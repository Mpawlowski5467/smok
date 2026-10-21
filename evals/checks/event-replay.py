from copy import deepcopy

from events.replay import replay
from events.validation import normalize


def rejects(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("invalid event input accepted")


def put(identity="x", key="a", version=1, value=None):
    return dict(id=identity, key=key, version=version, action="put", value=value)


first = put(value={"nested": [1]})
before = deepcopy(first)
normalized = normalize(dict(first, extra="ignored"))
assert normalized == first and normalized is not first
normalized["value"]["nested"].append(2)
assert first == before
shared = {"nested": []}
stream = [put("one", "a", 3, shared), put("two", "b", 1, shared)]
saved = deepcopy(stream)
output = replay(stream)
output["values"]["a"]["nested"].append(1)
assert output["values"]["b"] == shared == {"nested": []} and stream == saved
deletion = dict(id="d", key="a", version=7, action="delete")
raw_delete = dict(deletion, extra={"ignored": []})
saved_delete = deepcopy(raw_delete)
normalized_delete = normalize(raw_delete)
assert normalized_delete == deletion, "delete normalization must omit value and extra fields"
assert normalized_delete is not raw_delete and raw_delete == saved_delete
output = replay([first, deletion, dict(first, extra=99), put("new", "a", 9, None), deletion])
assert output == {"values": {"a": None}, "versions": {"a": 9}}
assert replay([put("x", " a ", 1, 2), put("X", "A", 1, 3)]) == {
    "values": {" a ": 2, "A": 3},
    "versions": {" a ": 1, "A": 1},
}
assert replay([]) == {"values": {}, "versions": {}}
for bad in (None, {}, (), ""):
    rejects(lambda bad=bad: replay(bad))
invalid = [
    None,
    [],
    {},
    dict(first, id=""),
    dict(first, key=1),
    dict(first, action=[]),
    dict(first, action="PUT"),
    dict(deletion, value=None),
]
invalid += [dict(first, version=v) for v in (0, -1, True, False, 1.5, "1", None)]
for key in first:
    invalid.append({k: v for k, v in first.items() if k != key})
for bad in invalid:
    rejects(lambda bad=bad: normalize(bad))
    rejects(lambda bad=bad: replay([first, bad]))
for stream in (
    [first, dict(first, key="b")],
    [first, dict(first, value=1)],
    [deletion, put("next", "a", 7)],
    [deletion, put("next", "a", 6)],
):
    saved = deepcopy(stream)
    rejects(lambda stream=stream: replay(stream))
    assert stream == saved
