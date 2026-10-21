from windows.ranges import parse_range
from windows.response import serve


def rejects(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("invalid byte window accepted")


for size in range(1, 12):
    data = bytes(range(size))
    for start in range(size):
        for end in range(start, size + 3):
            header = f"bytes={start}-{end}"
            bound = min(end, size - 1)
            assert parse_range(header, size) == (start, bound)
            assert serve(data, header) == {
                "status": 206,
                "body": data[start : bound + 1],
                "content_range": f"bytes {start}-{bound}/{size}",
            }
        assert parse_range(f"bytes={start}-", size) == (start, size - 1)
    for suffix in (1, size, size + 5):
        start = max(0, size - suffix)
        assert parse_range(f"bytes=-{suffix}", size) == (start, size - 1)
assert parse_range("bytes=001-003", 5) == (1, 3)
assert serve(b"x", "bytes=-9") == {"status": 206, "body": b"x", "content_range": "bytes 0-0/1"}
assert serve(b"abc") == {"status": 200, "body": b"abc", "content_range": None}
assert serve(b"") == {"status": 200, "body": b"", "content_range": None}
for bad in (
    None,
    1,
    "",
    "Bytes=0-1",
    "bytes=0-1\n",
    "bytes=٠-1",
    "bytes=1-２",
    "bytes=+1-2",
    "bytes= 0-1",
    "bytes=0-1 ",
    "bytes=0--1",
    "bytes=-0",
    "bytes=-",
    "bytes=3-1",
    "bytes=9-",
    "bytes=0-1,2-3",
):
    rejects(lambda bad=bad: parse_range(bad, 5))
    if bad is not None:
        rejects(lambda bad=bad: serve(b"abcde", bad))
for size in (0, -1, True, False, 1.5, "5", None):
    rejects(lambda size=size: parse_range("bytes=0-0", size))
for bad in ("abc", bytearray(b"a"), None, [], 0):
    rejects(lambda bad=bad: serve(bad))
    rejects(lambda bad=bad: serve(bad, "bytes=0-0"))
rejects(lambda: serve(b"", "bytes=0-0"))
