import shutil

from smok.process import capture
from smok.tools.files import ToolError, Workspace

EXCLUDES = (".git", ".smok", ".venv", "node_modules", "__pycache__")


class Search:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.output_limit = 24000

    async def run(self, args: list[str], *, no_matches: str) -> str:
        if not shutil.which("rg"):
            raise ToolError("Search requires ripgrep (rg). Install ripgrep and retry.")
        argv = ["rg", "--no-config", "--no-require-git", "--hidden", "--color", "never"]
        separator = args.index("--")
        argv += args[:separator]
        for excluded in EXCLUDES:
            argv += ["--glob", f"!**/{excluded}/**"]
        result = await capture(
            argv + args[separator:], self.workspace.root, seconds=10, limit=self.output_limit
        )
        if result.timed_out:
            raise ToolError("Search timed out; narrow the path or pattern.")
        text = result.output.decode("utf-8", errors="replace")
        if result.code not in {0, 1}:
            raise ToolError(text)
        if result.truncated:
            text += (
                f"\n[Search capture reached {self.output_limit} bytes; narrow the pattern or path.]"
            )
        return text or no_matches

    async def grep(
        self,
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        ignore_case: bool = False,
        limit: int = 100,
    ) -> str:
        resolved = self.workspace.resolve(path)
        target = str(resolved.relative_to(self.workspace.root))
        args = [
            "--line-number",
            "--with-filename",
            "--no-heading",
            "--max-filesize",
            "16M",
            "--max-count",
            str(limit),
        ]
        if ignore_case:
            args.append("--ignore-case")
        if glob:
            args += ["--glob", glob]
        return await self.run(args + ["--", pattern, target], no_matches="No matches.")

    async def glob(self, pattern: str, path: str = ".", limit: int = 200) -> str:
        resolved = self.workspace.resolve(path)
        if not resolved.is_dir():
            raise ToolError("Glob path must be a directory.")
        target = str(resolved.relative_to(self.workspace.root))
        output = await self.run(
            ["--files", "--glob", pattern, "--", target], no_matches="No files."
        )
        lines = output.splitlines()
        return "\n".join(lines[:limit]) + ("\n[Listing truncated.]" if len(lines) > limit else "")
