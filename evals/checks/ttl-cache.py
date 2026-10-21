from cache import TTLCache

now = [10]
cache = TTLCache(lambda: now[0])
cache.set("a", 0, 5)
assert cache.get("a", 99) == 0
now[0] = 14.99
assert cache.get("a") == 0
now[0] = 15
assert cache.get("a", 99) == 99
cache.set("b", False, 5)
cache.set("b", "new", 10)
now[0] = 21
assert cache.get("b") == "new"
cache.set("b", "bad", 0)
assert cache.get("b", "absent") == "absent"
cache.set("c", 1, -2)
assert cache.get("c") is None
