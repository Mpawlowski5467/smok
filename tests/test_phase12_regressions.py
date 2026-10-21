"""Public feedback catches the boundary defects observed during Phase 12."""

import json
import sys

import pytest

from evals import suite
from smok.process import capture

TASKS = {task["id"]: task for task in suite.load_tasks("phase12")}
SOLUTIONS = json.loads((suite.HERE / "phase12_solutions.json").read_text())
CHECK = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q"]


@pytest.mark.parametrize(
    "task_id,file,before,after,diagnostic",
    [
        (
            "batch-renames",
            "renames/validation.py",
            " or not isinstance(changes, list)",
            "",
            "test_container_types_even_when_empty",
        ),
        (
            "byte-windows",
            "windows/ranges.py",
            " or not isinstance(header, str)",
            "",
            "test_header_and_size_types",
        ),
        (
            "byte-windows",
            "windows/ranges.py",
            "count = int(right)",
            "count = int('-' + right)",
            "test_ranges",
        ),
        (
            "byte-windows",
            "windows/response.py",
            "if header is None:",
            "if not header:",
            "test_empty_header_is_not_missing",
        ),
        (
            "event-replay",
            "events/replay.py",
            "    if not isinstance(events, list):\n"
            "        raise ValueError('expected event list')\n",
            "",
            "test_stream_requires_list",
        ),
        (
            "byte-windows",
            "windows/ranges.py",
            "[0-9]*",
            r"\d*",
            "test_range_grammar_is_ascii_and_exact",
        ),
        (
            "byte-windows",
            "windows/ranges.py",
            "re.fullmatch(r'bytes=([0-9]*)-([0-9]*)', header)",
            "re.match(r'^bytes=([0-9]*)-([0-9]*)$', header)",
            "test_range_grammar_is_ascii_and_exact",
        ),
        (
            "event-replay",
            "events/validation.py",
            "    return result\n",
            "    result.setdefault('value', None)\n    return result\n",
            "test_normalized_delete_has_no_value_or_extra_fields",
        ),
        (
            "command-arguments",
            "arguments/lexing.py",
            "if active:",
            "if chars:",
            "test_empty_words_and_adjacent_fragments",
        ),
        (
            "command-arguments",
            "arguments/lexing.py",
            "elif char in ' \\t\\r\\n':",
            "elif False:",
            "test_unquoted_separators",
        ),
        (
            "command-arguments",
            "arguments/lexing.py",
            "ValueError('expected string')",
            "TypeError('expected string')",
            "test_input_types_raise_value_error",
        ),
        (
            "command-arguments",
            "arguments/options.py",
            "re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key)",
            "re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', key)",
            "test_key_cannot_end_with_newline",
        ),
        (
            "command-arguments",
            "arguments/options.py",
            "        result[key] = value",
            "        result.pop(key, None)\n        result[key] = value",
            "test_repeated_key_keeps_first_position",
        ),
    ],
)
async def test_public_checks_diagnose_known_defects(
    task_id, file, before, after, diagnostic, tmp_path
):
    task = TASKS[task_id]
    suite.write_fixture(tmp_path, task["files"])
    repairs = dict(SOLUTIONS[task_id])
    assert before in repairs[file]
    repairs[file] = repairs[file].replace(before, after)
    suite.write_fixture(tmp_path, repairs)
    public = await capture(CHECK, tmp_path)
    assert public.code != 0 and diagnostic.encode() in public.output, public.output
    passed, output = await suite.check_task(task, tmp_path)
    assert not passed, output
    assert suite.scope_check(task, tmp_path)["passed"]
