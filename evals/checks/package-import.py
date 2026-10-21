import ast
from pathlib import Path

import toolkit
from toolkit.formatting import render
from toolkit.text import shout

assert toolkit.render("smok") == "[SMOK]" and render("a") == "[A]" and shout("b") == "B"
for path in ["toolkit/__init__.py", "toolkit/formatting.py"]:
    tree = ast.parse(Path(path).read_text())
    assert any(isinstance(n, ast.ImportFrom) and n.level == 1 for n in ast.walk(tree))
    assert "sys.path" not in Path(path).read_text()
