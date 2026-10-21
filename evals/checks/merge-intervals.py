from intervals import merge_intervals

values = [(5, 8), (1, 3), (3, 5), (12, 12), (2, 2)]
before = values.copy()
assert merge_intervals(values) == [(1, 8), (12, 12)]
assert values == before
assert merge_intervals([]) == []
assert merge_intervals([(-3, -1), (-2, 0), (2, 4)]) == [(-3, 0), (2, 4)]
assert merge_intervals([(1, 5), (2, 3)]) == [(1, 5)]
assert merge_intervals([(1, 3), (4, 5)]) == [(1, 3), (4, 5)]
assert merge_intervals([(1, 1), (2, 2)]) == [(1, 1), (2, 2)]
