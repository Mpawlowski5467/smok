from copy import deepcopy
from itertools import permutations

from renames.operations import apply_renames
from renames.validation import rename_map


def rejects(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("invalid rename input accepted")


original = {"a": {"tags": [1]}, "b": {"tags": [2]}, "c": {"tags": [3]}}
before = deepcopy(original)
for order in permutations(original):
    changes = [
        {"source": key, "target": target} for key, target in zip(original, order, strict=True)
    ]
    frozen = deepcopy(changes)
    output = apply_renames(original, changes)
    assert list(output) == list(order)
    assert [value["tags"][0] for value in output.values()] == [1, 2, 3]
    for value in output.values():
        value["tags"].append(99)
    assert original == before and changes == frozen
shared = {"tags": []}
output = apply_renames({"a": shared, "b": shared}, [])
output["a"]["tags"].append(1)
assert output["b"] == shared == {"tags": []}
assert list(
    apply_renames({" a ": 1, "A": 2}, [{"source": " a ", "target": " a ", "extra": 3}])
) == [" a ", "A"]
for bad in (None, [], {"": 1}, {1: 2}):
    rejects(lambda bad=bad: rename_map(bad, []))
    rejects(lambda bad=bad: apply_renames(bad, []))
for bad in (
    None,
    {},
    (),
    [None],
    [{}],
    [{"source": "a"}],
    [{"source": "", "target": "x"}],
    [{"source": "a", "target": []}],
    [{"source": True, "target": "x"}],
    [{"source": "z", "target": "x"}],
    [{"source": "a", "target": "b"}],
    [{"source": "a", "target": "x"}, {"source": "a", "target": "y"}],
    [{"source": "a", "target": "x"}, {"source": "b", "target": "x"}],
):
    saved = deepcopy(bad)
    rejects(lambda bad=bad: rename_map(original, bad))
    rejects(lambda bad=bad: apply_renames(original, bad))
    assert original == before and bad == saved
