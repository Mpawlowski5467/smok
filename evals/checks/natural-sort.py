from names import natural_sort

values = ["file10.txt", "file2.txt", "File1.txt", "file02.txt", "file2a.txt"]
before = values.copy()
assert natural_sort(values) == ["File1.txt", "file2.txt", "file02.txt", "file2a.txt", "file10.txt"]
assert values == before
assert natural_sort(["a02", "A2", "a1"]) == ["a1", "a02", "A2"]
assert natural_sort(["10", "2", ""]) == ["", "2", "10"]
assert natural_sort([]) == []
