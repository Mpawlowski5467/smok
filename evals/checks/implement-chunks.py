from collections_utils import chunks

items = [1, 2, 3, 4, 5]
assert chunks(items, 2) == [[1, 2], [3, 4], [5]]
assert items == [1, 2, 3, 4, 5]
assert chunks([], 3) == []
assert chunks([1], 5) == [[1]]
for size in (0, -2):
    try:
        chunks([1], size)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
