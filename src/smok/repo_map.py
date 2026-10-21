"""Bounded Tree-sitter outlines, ranked by prompt terms, visited files, and references."""

import hashlib
import re
from collections import Counter
from pathlib import Path

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Parser

from smok.process import capture
from smok.tools.files import ToolError, bounded
from smok.tools.search import EXCLUDES

LANGUAGES = {
    ".py": tree_sitter_python.language,
    ".pyi": tree_sitter_python.language,
    ".js": tree_sitter_javascript.language,
    ".jsx": tree_sitter_javascript.language,
    ".mjs": tree_sitter_javascript.language,
    ".ts": tree_sitter_typescript.language_typescript,
    ".tsx": tree_sitter_typescript.language_tsx,
}
DEFINITIONS = {
    "function_definition",
    "class_definition",
    "function_declaration",
    "class_declaration",
    "method_definition",
    "method_signature",
    "interface_declaration",
    "type_alias_declaration",
    "enum_declaration",
    "variable_declarator",
}


class RepoMap:
    def __init__(self, workspace):
        self.workspace = workspace
        self.cache = {}
        self.parsers = {}

    def outline(self, path):
        suffix = path.suffix
        if suffix not in LANGUAGES:
            return [], set()
        with path.open("rb") as stream:
            raw = stream.read(262145)
        if len(raw) > 262144 or b"\0" in raw:
            return [], set()
        digest = hashlib.sha256(raw).hexdigest()
        prior = self.cache.get(path)
        if prior and prior[0] == digest:
            return prior[1], prior[2]
        if suffix not in self.parsers:
            self.parsers[suffix] = Parser(Language(LANGUAGES[suffix]()))
        parser = self.parsers[suffix]
        tree = parser.parse(raw)
        symbols, identifiers = [], set()
        stack = [tree.root_node]
        visited = 0
        while stack and visited < 20000:
            node = stack.pop()
            visited += 1
            if node.type in DEFINITIONS:
                name = node.child_by_field_name("name")
                if name is not None:
                    label = raw[name.start_byte : name.end_byte].decode("utf-8", errors="replace")
                    if len(label) <= 120:
                        symbols.append(
                            {
                                "name": label,
                                "line": name.start_point.row + 1,
                                "kind": node.type.replace("_definition", "").replace(
                                    "_declaration", ""
                                ),
                            }
                        )
            elif node.type in {"identifier", "type_identifier", "property_identifier"}:
                identifiers.add(
                    raw[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
                )
            stack.extend(reversed(node.named_children))
        result = (digest, symbols[:200], identifiers)
        self.cache[path] = result
        return result[1], result[2]

    async def build(self, query="", *, max_chars=6000, focus=()):
        import asyncio

        argv = ["rg", "--files", "--hidden", "--no-config", "--no-require-git"]
        for excluded in EXCLUDES:
            argv += ["--glob", f"!**/{excluded}/**"]
        try:
            result = await capture(argv, self.workspace.root, seconds=10, limit=250000)
        except OSError as exc:
            raise ToolError("Repository maps require ripgrep on PATH.") from exc
        if result.timed_out or result.code not in {0, 1}:
            raise ToolError("Repository map discovery failed; check ripgrep and workspace access.")
        names = result.output.decode("utf-8", errors="replace").splitlines()
        names = sorted(n for n in names if Path(n).suffix in LANGUAGES)[:500]
        terms = {t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z_0-9]{2,}", query)}
        focused = set(focus)

        def scan():
            rows, references = [], Counter()
            for name in names:
                try:
                    path = self.workspace.resolve(name)
                    if (self.workspace.root / name).is_symlink():
                        continue
                    symbols, identifiers = self.outline(path)
                except (OSError, ToolError):
                    continue
                references.update(identifiers)
                rows.append((name, symbols))
            return rows, references

        rows, references = await asyncio.to_thread(scan)

        def rank(row):
            name, symbols = row
            words = {s["name"].lower() for s in symbols}
            return (
                (100 if name in focused else 0)
                + sum(8 for t in terms if t in name.lower())
                + 5 * len(terms & words)
                + min(20, sum(references[s["name"]] for s in symbols))
            )

        rows.sort(key=lambda r: (-rank(r), r[0]))
        lines = ["Repository outline (Python/JS/TS; relevance-ranked, not file contents):"]
        for name, symbols in rows:
            lines.append(name)
            symbols.sort(key=lambda s: (s["name"].lower() not in terms, s["line"]))
            lines.extend(f"  {s['line']}: {s['kind']} {s['name']}" for s in symbols[:12])
            if sum(len(line) + 1 for line in lines) >= max_chars:
                break
        if not rows:
            lines.append("(no supported source files)")
        if result.truncated or len(names) == 500:
            lines.append("[Discovery capped at 500 files / 250000 bytes.]")
        return bounded("\n".join(lines), max_chars)
