from arguments.lexing import split_words
from arguments.options import parse_assignments


def rejects(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("invalid argument input accepted")


cases = [
    ("", []),
    (" \t\r\n ", []),
    ('""', [""]),
    ("'' x \"\"", ["", "x", ""]),
    ('a""b', ["ab"]),
    ("ab' cd 'ef", ["ab cd ef"]),
    ("a\\ b", ["a b"]),
    (r'"a\"b"', ['a"b']),
    (r"'a\b'", [r"a\b"]),
    ('"a\'b"', ["a'b"]),
    ("'a\"b'", ['a"b']),
    ("a\u00a0b", ["a\u00a0b"]),
    ("a\vb", ["a\vb"]),
    ("a\\\nb", ["a\nb"]),
    (r'"a\qb"', ["aqb"]),
    (r"\\", ["\\"]),
]
for text, expected in cases:
    assert split_words(text) == expected, (repr(text), split_words(text), expected)
assert list(parse_assignments('B=1 A=2 B=3 C=""').items()) == [("B", "3"), ("A", "2"), ("C", "")]
assert parse_assignments('A="a=b" _=ok x1=\\ value') == {"A": "a=b", "_": "ok", "x1": " value"}
assert parse_assignments("") == {}
for text in (None, [], 1, True, '"a', "'a", "a\\", '"a\\'):
    rejects(lambda text=text: split_words(text))
    rejects(lambda text=text: parse_assignments(text))
for text in (
    '""',
    "''",
    "A",
    "1A=x",
    "A-B=x",
    "é=x",
    "Ａ=x",
    "=x",
    "A=ok BAD",
    "A\\\n=x",
    "A\u00a0=x",
):
    rejects(lambda text=text: parse_assignments(text))
