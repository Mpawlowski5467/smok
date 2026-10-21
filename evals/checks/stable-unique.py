import copy

from sequence import stable_unique

values = [{"a": 1}, [2], {"a": 1}, 3, [2], 2, 3]
before = copy.deepcopy(values)
assert stable_unique(values) == [{"a": 1}, [2], 3, 2]
assert values == before
assert stable_unique([]) == []
assert stable_unique(["b", "a", "b", "c"]) == ["b", "a", "c"]
assert stable_unique(iter([2, 1, 2])) == [2, 1]
