from copy import deepcopy

from stock.lines import quantities
from stock.orders import reserve


def rejects(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("invalid input accepted")


lines = [{"sku": "b", "quantity": 1}, {"sku": "a", "quantity": 2}, {"sku": "b", "quantity": 3}]
before = deepcopy(lines)
assert list(quantities(lines).items()) == [("b", 4), ("a", 2)]
inventory = {"a": 2, "b": 4, "c": 0}
result = reserve(inventory, lines)
assert result == {"a": 0, "b": 0, "c": 0} and result is not inventory
assert inventory == {"a": 2, "b": 4, "c": 0} and lines == before
assert reserve({}, []) == {} and quantities([]) == {}
assert quantities([{"sku": " a ", "quantity": 1}, {"sku": "A", "quantity": 2}]) == {
    " a ": 1,
    "A": 2,
}
for bad in (None, {}, [None], [{}], [{"sku": "", "quantity": 1}], [{"sku": 1, "quantity": 1}]):
    rejects(lambda bad=bad: quantities(bad))
for bad in (0, -1, True, False, 1.5, "2", None):
    rejects(lambda bad=bad: quantities([{"sku": "a", "quantity": bad}]))
for bad in (None, [], {"a": True}, {"a": -1}, {"a": "2"}, {"": 1}, {1: 2}):
    rejects(lambda bad=bad: reserve(bad, []))
for order in (
    [{"sku": "a", "quantity": 1}, {"sku": "missing", "quantity": 1}],
    [{"sku": "a", "quantity": 2}, {"sku": "a", "quantity": 1}],
    [{"sku": "a", "quantity": 1}, {"sku": "b", "quantity": 0}],
):
    original = deepcopy(order)
    rejects(lambda order=order: reserve(inventory, order))
    assert inventory == {"a": 2, "b": 4, "c": 0} and order == original
