import copy

from catalog.api import list_items
from catalog.paging import page

rows = [{"id": 3, "name": "B"}, {"id": 2, "name": "a"}, {"id": 1, "name": "A"}]
before = copy.deepcopy(rows)
query = {"page": "1", "per_page": "2"}
assert [r["id"] for r in list_items(rows, query)["items"]] == [1, 2]
assert rows == before and query == {"page": "1", "per_page": "2"}
assert page(rows, 10, 2) == {"items": [], "total": 3, "page": 10, "pages": 2}
assert list_items(rows, {})["total"] == 3
for n, s in [(0, 2), (-1, 2), (1, 0), (1, 101), (True, 2), (1, False), (1.5, 2), (1, "2")]:
    try:
        page(rows, n, s)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid parameters accepted")
for query in [{"page": "x"}, {"page": "0"}, {"per_page": "101"}, {"per_page": "1.5"}]:
    try:
        list_items(rows, query)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid query accepted")
