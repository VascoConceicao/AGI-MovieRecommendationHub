#!/usr/bin/env python3
"""Read-only validation and planning for hierarchical Forge tasks."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SEGMENT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*$")
TASK = re.compile(r"([0-9]{4})-([a-z0-9]+(?:-[a-z0-9]+)*)$")
PHASE = re.compile(r"[0-9]{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
CATEGORY = re.compile(r"^(\s*)-\s+`([a-z0-9]+(?:-[a-z0-9]+)*)/`\s*$")
ENTRY = re.compile(
    r"^(\s*)-\s+\[([ xX])\]\s+\*\*(Current|Next|Queued|Blocked|Completed)\*\*\s+—\s+"
    r"\[([^]]+)\]\(([^)]+)\)(.*)$"
)
CHRONOLOGY_ENTRY = re.compile(r"^([0-9]+)\.\s+\[([^]]+)\]\(([^)]+)\)\s*$")


class DiagnosticError(Exception):
    def __init__(self, code: str, message: str, path: str | None = None):
        self.diagnostic = {"code": code, "message": message}
        if path:
            self.diagnostic["path"] = path
        super().__init__(message)


def fail(code: str, message: str, path: Path | str | None = None) -> None:
    raise DiagnosticError(code, message, str(path) if path else None)


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True))


def relative_leaf(value: str) -> tuple[str, ...]:
    parts = tuple(part for part in value.split("/") if part)
    if not parts or "/".join(parts) != value or any(not SEGMENT.fullmatch(part) for part in parts):
        fail("INVALID_LEAF", "leaf must be one or more lowercase-hyphenated segments", value)
    return parts


def task_name(value: str) -> tuple[int, str]:
    match = TASK.fullmatch(value)
    if not match:
        fail("INVALID_TASK_NAME", "task name must be NNNN-lowercase-hyphenated", value)
    return int(match.group(1)), match.group(2)


def require_safe_path(root: Path, parts: tuple[str, ...] = ()) -> Path:
    if root.is_symlink():
        fail("SYMLINK_PATH", "task paths may not use symlinks", root)
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            fail("SYMLINK_PATH", "task paths may not use symlinks", current)
    return current


def validate_task_path(leaf_value: str, name: str, branch: str | None = None) -> str:
    leaf = relative_leaf(leaf_value)
    task_name(name)
    expected = "/".join((*leaf, name))
    if branch is not None and branch != expected:
        fail("BRANCH_MISMATCH", "branch must equal the full task path", branch)
    return expected


def validate_destination(tasks: Path, leaf_value: str, name: str, branch: str) -> str:
    expected = validate_task_path(leaf_value, name, branch)
    destination = require_safe_path(tasks, tuple(expected.split("/")))
    if os.path.lexists(destination):
        fail("DUPLICATE_DESTINATION", "task destination already exists", destination)
    expected_id = next_id(tasks)
    if name[:4] != expected_id:
        fail("INVALID_TASK_INDEX", f"task index must be the global next value: {expected_id}", name)
    return expected


def validate_planned_destination(root: Path, leaf_value: str, name: str, branch: str, plan_file: Path) -> str:
    if plan_file.resolve().is_relative_to(root.resolve()):
        fail("PLAN_LOCATION", "move plan must stay outside the worktree so clean checks remain meaningful", plan_file)
    plan = validate_move(root, plan_file)
    if plan["new_leaf"] != leaf_value:
        fail("INVALID_MOVE_PLAN", "move plan must target the new task leaf", plan_file)
    expected = validate_task_path(leaf_value, name, branch)
    tasks = root / "docs/tasks"
    destination = require_safe_path(tasks, tuple(expected.split("/")))
    if os.path.lexists(destination):
        fail("DUPLICATE_DESTINATION", "task destination already exists", destination)
    next_value = next_id(tasks)
    if name[:4] != next_value:
        fail("INVALID_TASK_INDEX", f"task index must be the global next value: {next_value}", name)
    return expected


def validate_branch_path(value: str) -> str:
    parts = value.split("/")
    if len(parts) < 2:
        fail("INVALID_TASK_PATH", "task path needs a category and task name", value)
    return validate_task_path("/".join(parts[:-1]), parts[-1], value)


def task_path(tasks: Path, path: Path) -> str:
    return path.relative_to(tasks).as_posix()


def direct_tasks(leaf: Path) -> list[Path]:
    require_safe_path(leaf)
    if not leaf.exists():
        return []
    if not leaf.is_dir():
        fail("INVALID_LEAF", "leaf is not a directory", leaf)
    values = [path for path in leaf.iterdir() if path.is_dir() and TASK.fullmatch(path.name)]
    return sorted(values, key=lambda path: (int(path.name[:4]), path.name))


def task_shape(path: Path) -> None:
    for name in ("state.md", "decisions.md"):
        if not (path / name).is_file():
            fail("INVALID_TASK_SHAPE", f"missing {name}", path)
    phases = path / "phases"
    if not phases.is_dir() or not any(phases.glob("*.md")):
        fail("INVALID_TASK_SHAPE", "missing Markdown phase", path)


def validate_layout(tasks: Path) -> list[str]:
    if not tasks.is_dir():
        fail("MISSING_TASKS", "missing docs/tasks directory", tasks)
    require_safe_path(tasks)
    for current, directories, _ in os.walk(tasks, followlinks=False):
        for directory in directories:
            candidate = Path(current) / directory
            if candidate.is_symlink():
                fail("SYMLINK_PATH", "task paths may not use symlinks", candidate)
    found: list[str] = []
    for path in sorted(tasks.rglob("*")):
        if not path.is_dir():
            continue
        if any(TASK.fullmatch(ancestor.name) for ancestor in path.parents):
            continue
        relative = path.relative_to(tasks)
        if TASK.fullmatch(path.name):
            if len(relative.parts) < 2:
                fail("FLAT_TASK", "task must be below a category directory", path)
            if any(not SEGMENT.fullmatch(part) for part in relative.parts[:-1]):
                fail("INVALID_CATEGORY", "invalid category segment", path)
            task_shape(path)
            found.append(relative.as_posix())
        elif not SEGMENT.fullmatch(path.name):
            fail("INVALID_CATEGORY", "category must be lowercase-hyphenated", path)
    identifiers: dict[int, str] = {}
    for relative in found:
        identifier, _ = task_name(Path(relative).name)
        if identifier in identifiers:
            fail(
                "DUPLICATE_TASK_ID",
                "task identifiers must be unique across the recursive task tree",
                f"{identifiers[identifier]}, {relative}",
            )
        identifiers[identifier] = relative
    return found


def next_id(tasks: Path) -> str:
    paths = validate_layout(tasks)
    highest = max((task_name(Path(path).name)[0] for path in paths), default=0)
    if highest >= 9999:
        fail("INDEX_EXHAUSTED", "no four-digit task identifiers remain", tasks)
    return f"{highest + 1:04d}"


def indent_level(indent: str, line: int) -> int:
    if "\t" in indent or len(indent) % 2:
        fail("INVALID_TODO_INDENT", "TODO nesting uses multiples of two spaces", f"line {line}")
    return len(indent) // 2


def parse_todo(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    todo = root / "docs/TODO.md"
    if not todo.is_file():
        fail("MISSING_TODO", "missing docs/TODO.md", todo)
    stack: dict[int, str] = {}
    entries: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    chronology: list[dict[str, str]] = []
    seen_chronology: set[str] = set()
    in_chronology = False
    for number, raw in enumerate(todo.read_text(encoding="utf-8").splitlines(), 1):
        if raw == "## Chronology":
            if in_chronology:
                fail("DUPLICATE_CHRONOLOGY", "TODO must contain exactly one Chronology section", f"line {number}")
            in_chronology = True
            continue
        if in_chronology:
            if not raw:
                continue
            chronological = CHRONOLOGY_ENTRY.fullmatch(raw)
            if not chronological:
                fail("INVALID_CHRONOLOGY_ITEM", "Chronology contains only undated task links", f"line {number}")
            ordinal_text, title, link = chronological.groups()
            ordinal = int(ordinal_text)
            if ordinal != len(chronology) + 1:
                fail("INVALID_CHRONOLOGY_ORDER", "Chronology ordinals must be contiguous in listed order", f"line {number}")
            link_parts = Path(link).parts
            if len(link_parts) < 4 or link_parts[0] != "tasks" or link_parts[-1] != "state.md":
                fail("INVALID_CHRONOLOGY_LINK", "chronology link must name a task state file", f"line {number}")
            relative = "/".join(link_parts[1:-1])
            task_name(link_parts[-2])
            if relative in seen_chronology:
                fail("DUPLICATE_CHRONOLOGY_TASK", "task appears more than once in Chronology", f"line {number}")
            seen_chronology.add(relative)
            chronology.append({"path": relative, "title": title, "ordinal": str(ordinal)})
            continue
        category = CATEGORY.fullmatch(raw)
        entry = ENTRY.fullmatch(raw)
        if not category and not entry:
            if raw.lstrip().startswith("-"):
                fail("INVALID_TODO_ITEM", "TODO list item is not a category or task entry", f"line {number}")
            continue
        match = category or entry
        assert match
        level = indent_level(match.group(1), number)
        if category:
            segment = category.group(2)
            if level and level - 1 not in stack:
                fail("INVALID_TODO_HIERARCHY", "category has no parent", f"line {number}")
            stack = {depth: value for depth, value in stack.items() if depth < level}
            stack[level] = segment
            continue
        stack = {depth: value for depth, value in stack.items() if depth < level}
        checked, marker, title, link, tail = entry.group(2, 3, 4, 5, 6)
        if level - 1 not in stack:
            fail("INVALID_TODO_HIERARCHY", "task has no category parent", f"line {number}")
        categories = tuple(stack[depth] for depth in range(level) if depth in stack)
        if len(categories) != level:
            fail("INVALID_TODO_HIERARCHY", "task category chain is incomplete", f"line {number}")
        if marker == "Completed" and checked.lower() != "x":
            fail("INVALID_TODO_CHECKBOX", "Completed must be checked", f"line {number}")
        if marker != "Completed" and checked.lower() == "x":
            fail("INVALID_TODO_CHECKBOX", "only Completed may be checked", f"line {number}")
        if marker == "Blocked" and not tail.strip(" —\t"):
            fail("MISSING_BLOCKER", "Blocked entry needs a concise blocker", f"line {number}")
        link_parts = Path(link).parts
        if len(link_parts) < 4 or link_parts[0] != "tasks" or link_parts[-1] != "state.md":
            fail("INVALID_TODO_LINK", "task link must be tasks/<category>/<task>/state.md", f"line {number}")
        expected = (*categories, link_parts[-2])
        if tuple(link_parts[1:-1]) != expected:
            fail("TODO_HIERARCHY_MISMATCH", "link does not match its nested category chain", f"line {number}")
        relative = "/".join(link_parts[1:-1])
        task_name(link_parts[-2])
        if relative in seen_links:
            fail("DUPLICATE_TODO_TASK", "task appears more than once", f"line {number}")
        seen_links.add(relative)
        if tail and marker != "Blocked":
            fail("INVALID_TODO_SUFFIX", "only Blocked task entries may have a suffix", f"line {number}")
        entries.append(
            {
                "line": number,
                "marker": marker,
                "path": relative,
                "title": title,
            }
        )
    if not in_chronology:
        fail("MISSING_CHRONOLOGY", "TODO must end with a Chronology section", todo)
    return entries, chronology


def validate_todo(root: Path) -> list[dict[str, Any]]:
    tasks = root / "docs/tasks"
    paths = set(validate_layout(tasks))
    entries, chronology = parse_todo(root)
    linked = {entry["path"] for entry in entries}
    missing = sorted(paths - linked)
    unknown = sorted(linked - paths)
    if missing:
        fail("MISSING_TODO_TASK", "task has no TODO entry", missing[0])
    if unknown:
        fail("MISSING_TASK", "TODO link does not name a valid task", unknown[0])
    completed = {entry["path"] for entry in entries if entry["marker"] == "Completed"}
    chronological = {entry["path"] for entry in chronology}
    missing_chronology = sorted(completed - chronological)
    incomplete_chronology = sorted(chronological - completed)
    if missing_chronology:
        fail("MISSING_CHRONOLOGY_TASK", "Completed task is missing from Chronology", missing_chronology[0])
    if incomplete_chronology:
        fail("INCOMPLETE_CHRONOLOGY_TASK", "Chronology contains a task that is not Completed", incomplete_chronology[0])
    for marker in ("Current", "Next"):
        values = [entry for entry in entries if entry["marker"] == marker]
        if len(values) > 1:
            fail("AMBIGUOUS_TODO", f"more than one {marker} task", ", ".join(value["path"] for value in values))
    return entries


def resolve(root: Path) -> dict[str, Any]:
    entries = validate_todo(root)
    current = [entry for entry in entries if entry["marker"] == "Current"]
    if current:
        selected = current[0]
        return {
            "selection": "Current",
            "task": selected["path"],
            "expected_branch": selected["path"],
        }
    following = [entry for entry in entries if entry["marker"] == "Next"]
    if following:
        selected = following[0]
        return {
            "selection": "Next",
            "task": selected["path"],
            "expected_branch": selected["path"],
        }
    fail("NO_SELECTED_TASK", "TODO has no Current or Next task; ask the user to prioritize")


def validate_move(root: Path, plan_file: Path) -> dict[str, Any]:
    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail("INVALID_MOVE_PLAN", f"cannot read move plan: {error}", plan_file)
    if not isinstance(plan, dict) or set(plan) != {"parent", "new_leaf", "moves"}:
        fail("INVALID_MOVE_PLAN", "plan needs parent, new_leaf, and moves", plan_file)
    parent = relative_leaf(plan["parent"])
    new_leaf = relative_leaf(plan["new_leaf"])
    if new_leaf[:-1] != parent:
        fail("INVALID_MOVE_PLAN", "new leaf must be the immediate child of parent", plan_file)
    moves = plan["moves"]
    if not isinstance(moves, list) or not moves:
        fail("INVALID_MOVE_PLAN", "plan needs one or more moves", plan_file)
    tasks = root / "docs/tasks"
    seen_from: set[str] = set()
    seen_to: set[str] = set()
    for item in moves:
        if not isinstance(item, dict) or set(item) != {"from", "to"}:
            fail("INVALID_MOVE_PLAN", "every move needs from and to", plan_file)
        source, destination = item["from"], item["to"]
        if not isinstance(source, str) or not isinstance(destination, str):
            fail("INVALID_MOVE_PLAN", "move paths must be strings", plan_file)
        source_path = Path(source)
        destination_path = Path(destination)
        if source_path.parts[:-1] != parent or destination_path.parts[:-1] != new_leaf:
            fail("INVALID_MOVE_PLAN", "moves must be direct parent siblings into the new leaf", plan_file)
        task_name(source_path.name)
        task_name(destination_path.name)
        if destination_path.name != source_path.name:
            fail("INVALID_MOVE_PLAN", "moving a task must preserve its global identifier and name", plan_file)
        if source in seen_from or destination in seen_to:
            fail("INVALID_MOVE_PLAN", "move paths must be unique", plan_file)
        seen_from.add(source)
        seen_to.add(destination)
        if not (tasks / source).is_dir():
            fail("MISSING_TASK", "move source is missing", tasks / source)
        require_safe_path(tasks, tuple(source_path.parts))
        destination_full = require_safe_path(tasks, tuple(destination_path.parts))
        if os.path.lexists(destination_full):
            fail("DUPLICATE_DESTINATION", "move destination exists", tasks / destination)
    order = {path.relative_to(tasks).as_posix(): index for index, path in enumerate(direct_tasks(tasks.joinpath(*parent)))}
    source_order = [order[source] for source in (item["from"] for item in moves)]
    if source_order != sorted(source_order):
        fail("INVALID_MOVE_PLAN", "moves must preserve existing direct-sibling order", plan_file)
    validate_todo(root)
    return {"parent": "/".join(parent), "new_leaf": "/".join(new_leaf), "moves": moves}


def command(argv: list[str]) -> dict[str, Any]:
    if not argv:
        fail("USAGE", "use leaves, next-id, validate-layout, validate-todo, resolve, or validate-move")
    action, *args = argv
    if action == "leaves" and len(args) == 1:
        tasks = Path(args[0])
        validate_layout(tasks)
        leaves = sorted({str(Path(path).parent) for path in validate_layout(tasks)})
        return {"leaves": leaves}
    if action == "next-id" and len(args) == 1:
        return {"id": next_id(Path(args[0]))}
    if action == "task-path" and len(args) in (2, 3):
        return {"task": validate_task_path(args[0], args[1], args[2] if len(args) == 3 else None)}
    if action == "preflight-path" and len(args) == 4:
        return {"task": validate_destination(Path(args[0]), args[1], args[2], args[3])}
    if action == "preflight-move-path" and len(args) == 5:
        return {"task": validate_planned_destination(Path(args[0]), args[1], args[2], args[3], Path(args[4]))}
    if action == "branch-path" and len(args) == 1:
        return {"task": validate_branch_path(args[0])}
    if action == "validate-layout" and len(args) == 1:
        return {"tasks": validate_layout(Path(args[0]) / "docs/tasks")}
    if action == "validate-todo" and len(args) == 1:
        return {"entries": validate_todo(Path(args[0]))}
    if action == "resolve" and len(args) == 1:
        return resolve(Path(args[0]))
    if action == "validate-move" and len(args) == 2:
        return validate_move(Path(args[0]), Path(args[1]))
    fail("USAGE", "invalid task engine command")


def main() -> None:
    try:
        emit({"ok": True, **command(sys.argv[1:])})
    except DiagnosticError as error:
        emit({"ok": False, "diagnostics": [error.diagnostic]})
        sys.exit(1)


if __name__ == "__main__":
    main()
