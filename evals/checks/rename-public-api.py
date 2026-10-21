import ast
from pathlib import Path

from checkout import checkout
from pricing import total, total_cents
from pricing.core import total_cents as implementation

assert total_cents([100, 250], 25) == 325 and total([100, 250], 25) == 325
assert total_cents([]) == 0 and checkout([100, 250]) == 325
assert total_cents is implementation
tree = ast.parse(Path("checkout.py").read_text())
assert any(
    isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "total_cents"
    for n in ast.walk(tree)
)
