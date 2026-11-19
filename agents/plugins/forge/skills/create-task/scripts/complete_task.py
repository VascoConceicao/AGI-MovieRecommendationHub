#!/usr/bin/env python3
"""Atomically mark one task Completed in TODO and append its chronology entry."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import task_engine


def atomic_write(destination: Path, content: bytes) -> None:
    if destination.is_symlink():
        task_engine.fail("SYMLINK_TODO", "TODO may not be a symlink", destination)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.create-task-", dir=destination.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def completed_todo(root: Path, task: str) -> bytes:
    task_engine.validate_branch_path(task)
    entries = task_engine.validate_todo(root)
    selected = next((entry for entry in entries if entry["path"] == task), None)
    if selected is None:
        task_engine.fail("MISSING_TODO_TASK", "task has no TODO entry", task)
    if selected["marker"] == "Completed":
        task_engine.fail("ALREADY_COMPLETED", "task is already Completed", task)

    todo = root / "docs/TODO.md"
    lines = todo.read_text(encoding="utf-8").splitlines(keepends=True)
    line_index = selected["line"] - 1
    match = task_engine.ENTRY.fullmatch(lines[line_index].rstrip("\n"))
    if not match:
        task_engine.fail("INVALID_TODO_ITEM", "selected TODO entry changed during completion", f"line {selected['line']}")
    indent, title, link = match.group(1, 4, 5)
    if "/".join(Path(link).parts[1:-1]) != task:
        task_engine.fail("TODO_CHANGED", "selected TODO entry changed during completion", f"line {selected['line']}")
    ending = "\n" if lines[line_index].endswith("\n") else ""
    lines[line_index] = f"{indent}- [x] **Completed** — [{title}]({link}){ending}"

    _, chronology = task_engine.parse_todo(root)
    text = "".join(lines)
    separator = "" if text.endswith("\n") else "\n"
    return f"{text}{separator}{len(chronology) + 1}. [{title}]({link})\n".encode("utf-8")


def complete(root: Path, task: str) -> None:
    todo = root / "docs/TODO.md"
    if todo.is_symlink():
        task_engine.fail("SYMLINK_TODO", "TODO may not be a symlink", todo)
    original = todo.read_bytes()
    replacement = completed_todo(root, task)
    try:
        atomic_write(todo, replacement)
        task_engine.validate_todo(root)
    except Exception:
        atomic_write(todo, original)
        raise


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: complete_task.py ROOT TASK_PATH", file=sys.stderr)
        raise SystemExit(64)
    try:
        task = task_engine.validate_branch_path(sys.argv[2])
        complete(Path(sys.argv[1]).resolve(), task)
    except task_engine.DiagnosticError as error:
        task_engine.emit({"ok": False, "diagnostics": [error.diagnostic]})
        raise SystemExit(1)
    except Exception as error:
        task_engine.emit({"ok": False, "diagnostics": [{"code": "COMPLETE_TRANSACTION_FAILED", "message": str(error)}]})
        raise SystemExit(1)
    task_engine.emit({"ok": True, "completed": task})


if __name__ == "__main__":
    main()
