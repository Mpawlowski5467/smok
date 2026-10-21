from manifest.loader import load
from manifest.paths import normalize

assert normalize("./one//./two/") == "one/two"
assert normalize(".../a#b") == ".../a#b"
assert load("\n # comment\n b \n./a\nb\na//x\n./a/x\na#b\n") == ["b", "a", "a/x", "a#b"]
assert load("") == []
for value in ["", ".", "./", "/a", "//a", "a/../b", "../b", "a\\b", "a\x00b", None, 3]:
    try:
        normalize(value)
    except ValueError:
        pass
    else:
        raise AssertionError(f"invalid path accepted: {value!r}")
try:
    load("# header\na\n\n../oops\n")
except ValueError as exc:
    assert "line 4" in str(exc)
else:
    raise AssertionError("invalid manifest accepted")
