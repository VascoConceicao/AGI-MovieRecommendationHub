#!/usr/bin/env python3
"""Apply a validated local task move plan with staged references and rollback."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import task_engine


def git(root: Path, *arguments: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *arguments], text=True, capture_output=True, check=True).stdout
    except subprocess.CalledProcessError as error:
        task_engine.fail("GIT_PRECONDITION", error.stderr.strip() or "Git worktree check failed", root)


def require_clean(root: Path) -> None:
    if git(root, "status", "--short").strip():
        task_engine.fail("DIRTY_WORKTREE", "move requires a clean tracked and untracked worktree", root)


def require_unbranched_sources(root: Path, plan: dict[str, object]) -> None:
    refs = set(git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes").splitlines())
    for move in plan["moves"]:  # type: ignore[index]
        source = move["from"]  # type: ignore[index]
        if source in refs or any(reference.endswith(f"/{source}") for reference in refs):
            task_engine.fail("BRANCH_MIGRATION_REQUIRED", "move source has a local or tracked-remote branch", source)


def markdown_paths(root: Path) -> list[Path]:
    listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.md")
    paths: list[Path] = []
    for value in listed.split("\0"):
        if not value:
            continue
        path = root / value
        if path.is_symlink():
            task_engine.fail("SYMLINK_REFERENCE", "Markdown references may not use symlinks", path)
        if path.is_file():
            paths.append(path)
    return paths


def rewrite_todo(text: str, plan: dict[str, object]) -> str:
    moves = {move["from"]: move["to"] for move in plan["moves"]}  # type: ignore[index]
    parent = str(plan["parent"])
    child = str(plan["new_leaf"]).rsplit("/", 1)[1]
    moved_lines: dict[str, str] = {}
    for line in text.splitlines(keepends=True):
        match = task_engine.ENTRY.fullmatch(line.rstrip("\n"))
        link = match.group(5) if match else ""
        relative = "/".join(Path(link).parts[1:-1]) if Path(link).parts[:1] == ("tasks",) else ""
        if relative in moves:
            moved_lines[relative] = line.lstrip().replace(f"tasks/{relative}", f"tasks/{moves[relative]}")
    if set(moved_lines) != set(moves):
        task_engine.fail("MISSING_TODO_TASK", "move source has no TODO entry")
    output: list[str] = []
    inserted = False
    for line in text.splitlines(keepends=True):
        match = task_engine.ENTRY.fullmatch(line.rstrip("\n"))
        link = match.group(5) if match else ""
        relative = "/".join(Path(link).parts[1:-1]) if Path(link).parts[:1] == ("tasks",) else ""
        if relative not in moves:
            output.append(line)
            continue
        if not inserted:
            output.append(f"{'  ' * len(parent.split('/'))}- `{child}/`\n")
            for move in plan["moves"]:  # type: ignore[index]
                output.append(f"{'  ' * (len(parent.split('/')) + 1)}{moved_lines[move['from']]}")
            inserted = True
    return "".join(output)


def rewrite_references(text: str, moves: list[dict[str, str]]) -> str:
    for move in moves:
        for prefix in ("docs/tasks/", "tasks/"):
            source = f"{prefix}{move['from']}"
            destination = f"{prefix}{move['to']}"
            text = re.sub(re.escape(source) + r"(?=$|[^a-z0-9-])", destination, text)
    return text


def relocated(relative: Path, moves: list[dict[str, str]]) -> Path:
    prefix = Path("docs/tasks")
    for move in moves:
        source = prefix / move["from"]
        try:
            suffix = relative.relative_to(source)
        except ValueError:
            continue
        return prefix / move["to"] / suffix
    return relative


def atomic_write(destination: Path, content: bytes) -> None:
    if destination.is_symlink():
        task_engine.fail("SYMLINK_REFERENCE", "Markdown references may not use symlinks", destination)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.create-task-", dir=destination.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def rollback(root: Path, references: list[Path], originals: dict[Path, bytes], moves: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    for destination in reversed(references):
        try:
            atomic_write(destination, originals[destination])
        except Exception as error:
            errors.append(f"reference {destination}: {error}")
    for move in reversed(moves):
        source = root / "docs/tasks" / move["to"]
        destination = root / "docs/tasks" / move["from"]
        try:
            if source.exists() and not os.path.lexists(destination):
                os.replace(source, destination)
        except Exception as error:
            errors.append(f"task {move['to']}: {error}")
    return errors


def staged_replacements(root: Path, plan: dict[str, object], paths: list[Path]) -> tuple[dict[Path, bytes], dict[Path, bytes]]:
    moves = plan["moves"]  # type: ignore[assignment]
    with tempfile.TemporaryDirectory(prefix=".create-task-move-", dir=root) as temporary:
        staged_root = Path(temporary)
        staged_docs = staged_root / "docs"
        shutil.copytree(root / "docs", staged_docs)
        for move in moves:
            source = staged_docs / "tasks" / move["from"]
            destination = staged_docs / "tasks" / move["to"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        todo = staged_docs / "TODO.md"
        todo.write_text(
            rewrite_references(rewrite_todo(todo.read_text(encoding="utf-8"), plan), moves),
            encoding="utf-8",
        )
        task_engine.validate_todo(staged_root)

        replacements: dict[Path, bytes] = {}
        originals: dict[Path, bytes] = {}
        for path in paths:
            relative = path.relative_to(root)
            target_relative = relocated(relative, moves)
            source = staged_docs / target_relative.relative_to("docs") if target_relative.parts[0] == "docs" else path
            if not source.is_file():
                continue
            original = path.read_bytes()
            text = source.read_text(encoding="utf-8")
            rewritten = rewrite_references(text, moves)
            content = rewritten.encode("utf-8")
            destination = root / target_relative
            if content != original or destination != path:
                replacements[destination] = content
                originals[destination] = original
        return replacements, originals


def apply(root: Path, plan_file: Path) -> None:
    plan = task_engine.validate_move(root, plan_file)
    require_clean(root)
    require_unbranched_sources(root, plan)
    paths = markdown_paths(root)
    replacements, originals = staged_replacements(root, plan, paths)
    applied_moves: list[dict[str, str]] = []
    applied_references: list[Path] = []
    try:
        for move in plan["moves"]:
            source = root / "docs/tasks" / move["from"]
            destination = root / "docs/tasks" / move["to"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            applied_moves.append(move)
        for destination, content in replacements.items():
            atomic_write(destination, content)
            applied_references.append(destination)
    except Exception:
        errors = rollback(root, applied_references, originals, applied_moves)
        if errors:
            raise RuntimeError("create-task rollback failed: " + "; ".join(errors))
        raise


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: apply_move.py ROOT PLAN.json", file=sys.stderr)
        raise SystemExit(64)
    try:
        apply(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
    except task_engine.DiagnosticError as error:
        task_engine.emit({"ok": False, "diagnostics": [error.diagnostic]})
        raise SystemExit(1)
    except Exception as error:
        code = "ROLLBACK_FAILED" if str(error).startswith("create-task rollback failed:") else "MOVE_TRANSACTION_FAILED"
        task_engine.emit({"ok": False, "diagnostics": [{"code": code, "message": str(error)}]})
        raise SystemExit(1)
    task_engine.emit({"ok": True, "applied": "move"})


if __name__ == "__main__":
    main()
