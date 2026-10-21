from copy import deepcopy

from mappings import deep_merge

left = {"a": {"x": [1], "same": 1}, "b": [2], "c": 8}
right = {"a": {"y": [3], "same": None}, "b": [4]}
original_left, original_right = deepcopy(left), deepcopy(right)
result = deep_merge(left, right)
assert result == {"a": {"x": [1], "y": [3], "same": None}, "b": [4], "c": 8}
result["a"]["x"].append(9)
result["a"]["y"].append(9)
result["b"].append(9)
assert left == original_left and right == original_right
assert deep_merge({"a": 1}, {"a": {"b": 2}}) == {"a": {"b": 2}}
