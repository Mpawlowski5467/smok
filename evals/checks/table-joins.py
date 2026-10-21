from copy import deepcopy

from tables.indexing import index_rows
from tables.joining import left_join


def rejects(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("invalid input accepted")


left = [{"id": 1, "tags": []}, {"id": "1"}, {"id": 1, "label": "last"}, {"id": 0}]
right = [{"id": 1, "tags": ["a"]}, {"id": 1, "tags": ["b"]}, {"id": "1", "tags": []}]
original = deepcopy((left, right))
joined = left_join(left, right, "id")
assert len(joined) == 6
assert [r["right"]["tags"] if r["right"] is not None else None for r in joined] == [
    ["a"],
    ["b"],
    [],
    ["a"],
    ["b"],
    None,
]
assert [r["left"] for r in joined] == [left[0], left[0], left[1], left[2], left[2], left[3]]
assert all(set(r) == {"left", "right"} for r in joined)
joined[0]["left"]["tags"].append("changed")
joined[0]["right"]["tags"].append("changed")
assert joined[1]["left"]["tags"] == [] and joined[3]["right"]["tags"] == ["a"]
assert (left, right) == original
index = index_rows(right, "id")
index[1][0]["tags"].append("changed")
assert right == original[1] and index[1][1]["tags"] == ["b"]
assert left_join([], [], "id") == [] and index_rows([], "id") == {}
for bad in (None, {}, [None], [{}], [{"id": True}], [{"id": None}], [{"id": []}], [{"id": 1.0}]):
    rejects(lambda bad=bad: index_rows(bad, "id"))
    rejects(lambda bad=bad: left_join([], bad, "id"))
    rejects(lambda bad=bad: left_join(bad, [], "id"))
for key in ("", None, 1):
    rejects(lambda key=key: index_rows([], key))
