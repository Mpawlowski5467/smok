from catalog.paging import paginate
from catalog.service import list_products

items = list(range(23))
for fn in (paginate, list_products):
    assert fn(items, 2, 10) == {"items": list(range(10, 20)), "total": 23, "pages": 3}
    assert fn(items, 9, 10) == {"items": [], "total": 23, "pages": 3}
    assert fn([], 1, 10) == {"items": [], "total": 0, "pages": 0}
    for page, size in [(0, 2), (1, 0), (-1, 3), (1, -2)]:
        try:
            fn(items, page, size)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid pagination accepted")
assert items == list(range(23))
assert list_products(items)["items"] == list(range(10))
