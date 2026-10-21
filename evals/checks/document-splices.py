from copy import deepcopy

from splices.batch import apply_documents
from splices.core import replace_spans


def rejects(call, exception=ValueError):
    try:
        call()
    except exception:
        return
    raise AssertionError("invalid input accepted")


spans = [{"start": 3, "end": 4, "text": "Z"}, {"start": 0, "end": 1, "text": "LONG"}]
original = deepcopy(spans)
assert replace_spans("abcd", spans) == "LONGbcZ" and spans == original
assert replace_spans("a🙂éz", [{"start": 1, "end": 3, "text": "X"}]) == "aXz"
assert (
    replace_spans("abc", [{"start": 0, "end": 1, "text": ""}, {"start": 1, "end": 3, "text": "!"}])
    == "!"
)
assert replace_spans("", []) == ""
for start, end in ((-1, 1), (0, 0), (2, 1), (0, 5), (True, 2), (0, True), (0, 1.0)):
    rejects(
        lambda start=start, end=end: replace_spans(
            "abcd", [{"start": start, "end": end, "text": ""}]
        )
    )
for bad in (None, {}, [{}], [None], [{"start": 0, "end": 1, "text": None}]):
    rejects(lambda bad=bad: replace_spans("abc", bad))
rejects(lambda: replace_spans(None, []))
rejects(
    lambda: replace_spans(
        "abcd", [{"start": 0, "end": 2, "text": ""}, {"start": 0, "end": 2, "text": "x"}]
    )
)
docs = {"a": "abcd", "b": "keep"}
result = apply_documents(docs, {"a": spans})
assert result == {"a": "LONGbcZ", "b": "keep"} and result is not docs
rejects(lambda: apply_documents(docs, {"a": spans, "missing": []}), KeyError)
rejects(lambda: apply_documents(docs, {"a": spans, "b": [{}]}))
assert docs == {"a": "abcd", "b": "keep"} and spans == original
for bad in (None, [], {"a": 4}, {1: "text"}):
    rejects(lambda bad=bad: apply_documents(bad, {}))
rejects(lambda: apply_documents({}, None))
rejects(lambda: apply_documents({}, {1: []}))
