from urllib.parse import parse_qsl, urlsplit

from urls import set_query

value = set_query("https://example.test/a?x=1&q=old&x=2&empty=#part", "q", ["a b", "x/y"])
parts = urlsplit(value)
assert (parts.scheme, parts.netloc, parts.path, parts.fragment) == (
    "https",
    "example.test",
    "/a",
    "part",
)
assert parse_qsl(parts.query, keep_blank_values=True) == [
    ("x", "1"),
    ("x", "2"),
    ("empty", ""),
    ("q", "a b"),
    ("q", "x/y"),
]
assert set_query("/a?q=1#b", "q", []) == "/a#b"
assert parse_qsl(urlsplit(set_query("/", "q", ["é&="])).query) == [("q", "é&=")]
