import random
from numbers import clamp

rng = random.Random(71)
for _ in range(40):
    a, b = sorted((rng.randint(-30, 30), rng.randint(-30, 30)))
    value = rng.randint(-50, 50)
    assert clamp(value, a, b) == max(a, min(b, value))
assert clamp(1.5, 1, 2) == 1.5
try:
    clamp(0, 2, 1)
except ValueError:
    pass
else:
    raise AssertionError("invalid bounds accepted")
