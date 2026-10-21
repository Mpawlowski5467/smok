from text_utils import slugify

assert slugify("  Hello, World!  ") == "hello-world"
assert slugify("a___b---c") == "a-b-c"
assert slugify("123 Test") == "123-test"
assert slugify("") == ""
assert slugify(" !!! ") == ""
