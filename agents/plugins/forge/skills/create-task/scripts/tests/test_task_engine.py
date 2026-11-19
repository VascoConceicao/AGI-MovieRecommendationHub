#!/usr/bin/env python3
"""Focused fixtures for the create-task engine and façade."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
import task_engine  # noqa: E402
import apply_move  # noqa: E402
import complete_task  # noqa: E402


def make_task(root: Path, relative: str) -> None:
    task = root / "docs/tasks" / relative
    (task / "phases").mkdir(parents=True)
    (task / "state.md").write_text("# Task: Fixture\n\n## Status\n\nQueued\n", encoding="utf-8")
    (task / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (task / "phases/01-discovery.md").write_text("# Phase\n", encoding="utf-8")


def write_todo(root: Path, entries: list[tuple[str, str]]) -> None:
    lines = ["# TODO", ""]
    seen: list[str] = []
    for relative, marker in entries:
        parts = relative.split("/")
        categories, name = parts[:-1], parts[-1]
        shared = 0
        while shared < len(seen) and shared < len(categories) and seen[shared] == categories[shared]:
            shared += 1
        for depth, category in enumerate(categories[shared:], shared):
            lines.append(f"{'  ' * depth}- `{category}/`")
        seen = categories
        checked = "x" if marker == "Completed" else " "
        suffix = " — dependency" if marker == "Blocked" else ""
        lines.append(
            f"{'  ' * len(categories)}- [{checked}] **{marker}** — [Task](tasks/{relative}/state.md){suffix}"
        )
    lines.extend(["", "## Chronology", ""])
    ordinal = 0
    for relative, marker in entries:
        if marker == "Completed":
            ordinal += 1
            lines.append(f"{ordinal}. [Task](tasks/{relative}/state.md)")
    (root / "docs/TODO.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


class TaskEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="forge-task-engine-")
        self.plans = tempfile.TemporaryDirectory(prefix="forge-task-plans-")
        self.root = Path(self.temporary.name)
        (self.root / "docs/tasks").mkdir(parents=True)
        (self.root / "docs/template").mkdir(parents=True)

    def tearDown(self) -> None:
        self.plans.cleanup()
        self.temporary.cleanup()

    def commit_fixture(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "fixture@example.test"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)

    def test_deep_todo_and_global_ids(self) -> None:
        deep = "a/b/c/d/e/f/g/0001-deep"
        other = "other/0002-other"
        make_task(self.root, deep)
        make_task(self.root, other)
        write_todo(self.root, [(deep, "Current"), (other, "Next")])
        self.assertEqual(task_engine.next_id(self.root / "docs/tasks"), "0003")
        self.assertEqual(
            task_engine.resolve(self.root),
            {"selection": "Current", "task": deep, "expected_branch": deep},
        )

    def test_template_category_is_valid_after_reusable_template_moves_up(self) -> None:
        task = "foundation/template/0001-foundation"
        root_template_task = "template/0002-root-template-task"
        make_task(self.root, task)
        make_task(self.root, root_template_task)
        write_todo(self.root, [(task, "Current"), (root_template_task, "Queued")])
        self.assertEqual(task_engine.validate_todo(self.root)[0]["path"], task)
        self.assertEqual(task_engine.next_id(self.root / "docs/tasks"), "0003")

    def test_duplicate_global_ids_are_rejected_across_leaves(self) -> None:
        make_task(self.root, "one/0001-first")
        make_task(self.root, "two/0001-second")
        write_todo(self.root, [("one/0001-first", "Current"), ("two/0001-second", "Queued")])
        with self.assertRaisesRegex(task_engine.DiagnosticError, "unique across"):
            task_engine.validate_todo(self.root)

    def test_chronology_requires_contiguous_order_and_exact_completed_membership(self) -> None:
        completed = "workflow/0001-completed"
        queued = "workflow/0002-queued"
        make_task(self.root, completed)
        make_task(self.root, queued)
        write_todo(self.root, [(completed, "Completed"), (queued, "Queued")])
        todo = self.root / "docs/TODO.md"
        text = todo.read_text(encoding="utf-8")
        todo.write_text(text.replace("1. [Task]", "2. [Task]"), encoding="utf-8")
        with self.assertRaisesRegex(task_engine.DiagnosticError, "ordinals must be contiguous"):
            task_engine.validate_todo(self.root)

        todo.write_text(
            text + f"2. [Queued](tasks/{queued}/state.md)\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(task_engine.DiagnosticError, "not Completed"):
            task_engine.validate_todo(self.root)

    def test_complete_updates_todo_and_appends_chronology(self) -> None:
        first = "workflow/skills/0001-first"
        second = "workflow/skills/0002-second"
        make_task(self.root, first)
        make_task(self.root, second)
        write_todo(self.root, [(first, "Completed"), (second, "Blocked")])

        complete_task.complete(self.root, second)

        todo = (self.root / "docs/TODO.md").read_text(encoding="utf-8")
        self.assertIn(
            "    - [x] **Completed** — [Task](tasks/workflow/skills/0002-second/state.md)\n",
            todo,
        )
        self.assertNotIn("dependency", todo)
        self.assertTrue(todo.endswith("2. [Task](tasks/workflow/skills/0002-second/state.md)\n"))
        task_engine.validate_todo(self.root)

    def test_complete_rejects_repeated_or_unknown_tasks_without_changes(self) -> None:
        completed = "workflow/0001-completed"
        queued = "workflow/0002-queued"
        make_task(self.root, completed)
        make_task(self.root, queued)
        write_todo(self.root, [(completed, "Completed"), (queued, "Queued")])
        todo = self.root / "docs/TODO.md"
        original = todo.read_bytes()

        with self.assertRaisesRegex(task_engine.DiagnosticError, "already Completed"):
            complete_task.complete(self.root, completed)
        self.assertEqual(todo.read_bytes(), original)
        with self.assertRaisesRegex(task_engine.DiagnosticError, "no TODO entry"):
            complete_task.complete(self.root, "workflow/0003-unknown")
        self.assertEqual(todo.read_bytes(), original)

    def test_shell_complete_uses_exact_task_path(self) -> None:
        task = "workflow/skills/0001-one"
        make_task(self.root, task)
        write_todo(self.root, [(task, "Current")])
        helper = SCRIPT_DIR / "task-helper.sh"

        completed = subprocess.run(
            ["sh", str(helper), "complete", str(self.root), task], text=True, capture_output=True, check=True
        )
        self.assertIn(f'"completed": "{task}"', completed.stdout)
        task_engine.validate_todo(self.root)

        invalid = subprocess.run(
            ["sh", str(helper), "complete", str(self.root), "0001-one"], text=True, capture_output=True
        )
        self.assertNotEqual(invalid.returncode, 0)

    def test_todo_rejects_wrong_hierarchy_and_multiple_next(self) -> None:
        task = "workflow/skills/0001-one"
        next_task = "workflow/skills/0002-two"
        parent_task = "workflow/0003-parent"
        make_task(self.root, task)
        make_task(self.root, next_task)
        make_task(self.root, parent_task)
        (self.root / "docs/TODO.md").write_text(
            "# TODO\n\n- `workflow/`\n  - [ ] **Next** — [One](tasks/workflow/skills/0001-one/state.md)\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(task_engine.DiagnosticError, "nested category chain"):
            task_engine.validate_todo(self.root)
        write_todo(self.root, [(task, "Next"), (next_task, "Next"), (parent_task, "Queued")])
        with self.assertRaisesRegex(task_engine.DiagnosticError, "more than one Next"):
            task_engine.validate_todo(self.root)
        (self.root / "docs/TODO.md").write_text(
            "# TODO\n\n- `workflow/`\n  - `skills/`\n    - [ ] **Current** — [One](tasks/workflow/skills/0001-one/state.md)\n"
            "  - [ ] **Queued** — [Parent](tasks/workflow/0003-parent/state.md)\n"
            "    - [ ] **Queued** — [Two](tasks/workflow/skills/0002-two/state.md)\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(task_engine.DiagnosticError, "no category parent"):
            task_engine.validate_todo(self.root)

    def test_move_preserves_order_updates_separated_todo_and_repository_references(self) -> None:
        first = "workflow/0001-one"
        second = "workflow/0002-two"
        third = "workflow/0003-three"
        make_task(self.root, first)
        make_task(self.root, second)
        make_task(self.root, third)
        write_todo(self.root, [(first, "Completed"), (second, "Queued"), (third, "Queued")])
        (self.root / "README.md").write_text(
            "See docs/tasks/workflow/0001-one/state.md and docs/tasks/workflow/0001-one-extra/state.md.\n",
            encoding="utf-8",
        )
        self.commit_fixture()
        plan = Path(self.plans.name) / "move.json"
        plan.write_text(
            json.dumps(
                {
                    "parent": "workflow",
                    "new_leaf": "workflow/skills",
                    "moves": [
                        {"from": first, "to": "workflow/skills/0001-one"},
                        {"from": third, "to": "workflow/skills/0003-three"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        subprocess.run([sys.executable, str(SCRIPT_DIR / "apply_move.py"), str(self.root), str(plan)], check=True)
        self.assertTrue((self.root / "docs/tasks/workflow/skills/0001-one/state.md").is_file())
        todo = (self.root / "docs/TODO.md").read_text(encoding="utf-8")
        self.assertEqual(todo.count("`skills/`"), 1)
        self.assertLess(todo.index("0001-one"), todo.index("0003-three"))
        self.assertLess(todo.index("0003-three"), todo.index("0002-two"))
        self.assertIn("  - [ ] **Queued** — [Task](tasks/workflow/0002-two/state.md)", todo)
        self.assertNotIn("tasks/workflow/0003-three", todo)
        self.assertIn("1. [Task](tasks/workflow/skills/0001-one/state.md)", todo)
        task_engine.validate_todo(self.root)
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/tasks/workflow/skills/0001-one", readme)
        self.assertIn("docs/tasks/workflow/0001-one-extra", readme)

    def test_move_rejects_reordered_sources_dirty_worktree_and_task_branches(self) -> None:
        first, second = "workflow/0001-one", "workflow/0002-two"
        make_task(self.root, first)
        make_task(self.root, second)
        write_todo(self.root, [(first, "Current"), (second, "Queued")])
        self.commit_fixture()
        plan = Path(self.plans.name) / "move.json"
        plan.write_text(json.dumps({"parent": "workflow", "new_leaf": "workflow/skills", "moves": [
            {"from": first, "to": "workflow/skills/0001-one"}, {"from": second, "to": "workflow/skills/0002-two"}
        ]}), encoding="utf-8")
        reversed_plan = Path(self.plans.name) / "reversed.json"
        reversed_plan.write_text(json.dumps({"parent": "workflow", "new_leaf": "workflow/skills", "moves": [
            {"from": second, "to": "workflow/skills/0002-two"}, {"from": first, "to": "workflow/skills/0001-one"}
        ]}), encoding="utf-8")
        with self.assertRaisesRegex(task_engine.DiagnosticError, "preserve existing"):
            task_engine.validate_move(self.root, reversed_plan)
        (self.root / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        dirty = subprocess.run([sys.executable, str(SCRIPT_DIR / "apply_move.py"), str(self.root), str(plan)], text=True, capture_output=True)
        self.assertNotEqual(dirty.returncode, 0)
        self.assertTrue((self.root / "docs/tasks" / first).is_dir())
        (self.root / "dirty.txt").unlink()
        subprocess.run(["git", "-C", str(self.root), "branch", first], check=True)
        branched = subprocess.run([sys.executable, str(SCRIPT_DIR / "apply_move.py"), str(self.root), str(plan)], text=True, capture_output=True)
        self.assertNotEqual(branched.returncode, 0)
        self.assertTrue((self.root / "docs/tasks" / first).is_dir())
        subprocess.run(["git", "-C", str(self.root), "branch", "-D", first], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "update-ref", f"refs/remotes/origin/{first}", "HEAD"], check=True)
        remote = subprocess.run([sys.executable, str(SCRIPT_DIR / "apply_move.py"), str(self.root), str(plan)], text=True, capture_output=True)
        self.assertNotEqual(remote.returncode, 0)
        self.assertTrue((self.root / "docs/tasks" / first).is_dir())

    def test_shell_create_uses_full_branch_path(self) -> None:
        shutil.copytree(Path.cwd() / "docs/template", self.root / "docs/template", dirs_exist_ok=True)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "fixture@example.test"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)
        subprocess.run(["git", "-C", str(self.root), "branch", "-M", "development"], check=True)
        helper = SCRIPT_DIR / "task-helper.sh"
        command = ["sh", str(helper), "create", str(self.root), "workflow/skills", "0001-fixture", "01-discovery.md", "workflow/skills/0001-fixture"]
        wrong_branch = subprocess.run(command, text=True, capture_output=True)
        self.assertNotEqual(wrong_branch.returncode, 0)
        preflight = ["sh", str(helper), "preflight", *command[3:]]
        subprocess.run(preflight, check=True)
        subprocess.run(["git", "-C", str(self.root), "switch", "-qc", "workflow/skills/0001-fixture"], check=True)
        subprocess.run(command, check=True)
        task = self.root / "docs/tasks/workflow/skills/0001-fixture"
        self.assertTrue((task / "phases/01-discovery.md").is_file())
        (task / "state.md").write_text("# Task: Fixture\n", encoding="utf-8")
        (task / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
        (task / "phases/01-discovery.md").write_text(
            "# Phase\n\n## Recommended Model\n\n### Codex\n\n- Model: gpt-5.6-terra\n- Effort: low\n"
            "\n### Claude Code\n\n- Model: Unverified\n- Effort: low (advisory)\n",
            encoding="utf-8",
        )
        subprocess.run(["sh", str(helper), "validate", *command[3:]], check=True)
        wrong = subprocess.run(command[:-1] + ["0001-fixture"], text=True, capture_output=True)
        self.assertNotEqual(wrong.returncode, 0)
        wrong_id = subprocess.run(
            ["sh", str(helper), "create", str(self.root), "workflow/skills", "0003-wrong-id", "01-discovery.md", "workflow/skills/0003-wrong-id"],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(wrong_id.returncode, 0)

    def test_preflight_rejects_local_and_remote_branch_namespace_collisions(self) -> None:
        shutil.copytree(Path.cwd() / "docs/template", self.root / "docs/template", dirs_exist_ok=True)
        self.commit_fixture()
        subprocess.run(["git", "-C", str(self.root), "branch", "-M", "development"], check=True)
        helper = SCRIPT_DIR / "task-helper.sh"
        args = ["sh", str(helper), "preflight", str(self.root), "workflow/skills", "0001-fixture", "01-discovery.md", "workflow/skills/0001-fixture"]
        subprocess.run(["git", "-C", str(self.root), "branch", "workflow/skills"], check=True)
        self.assertNotEqual(subprocess.run(args, text=True, capture_output=True).returncode, 0)
        subprocess.run(["git", "-C", str(self.root), "branch", "-D", "workflow/skills"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "update-ref", "refs/remotes/origin/workflow/skills/0001-fixture/sub", "HEAD"], check=True)
        self.assertNotEqual(subprocess.run(args, text=True, capture_output=True).returncode, 0)

    def test_move_aware_preflight_reserves_post_move_index_then_creates(self) -> None:
        shutil.copytree(Path.cwd() / "docs/template", self.root / "docs/template", dirs_exist_ok=True)
        first, second = "workflow/0001-one", "workflow/0002-two"
        make_task(self.root, first)
        make_task(self.root, second)
        write_todo(self.root, [(first, "Current"), (second, "Queued")])
        self.commit_fixture()
        subprocess.run(["git", "-C", str(self.root), "branch", "-M", "development"], check=True)
        plan = Path(self.plans.name) / "move.json"
        plan.write_text(json.dumps({"parent": "workflow", "new_leaf": "workflow/skills", "moves": [
            {"from": first, "to": "workflow/skills/0001-one"}, {"from": second, "to": "workflow/skills/0002-two"}
        ]}), encoding="utf-8")
        helper = SCRIPT_DIR / "task-helper.sh"
        base = ["sh", str(helper), "preflight", str(self.root), "workflow/skills", "0003-new", "01-discovery.md", "workflow/skills/0003-new", str(plan)]
        subprocess.run(base, check=True)
        wrong = [*base]
        wrong[5] = "0002-wrong"
        wrong[7] = "workflow/skills/0002-wrong"
        self.assertNotEqual(subprocess.run(wrong, text=True, capture_output=True).returncode, 0)
        subprocess.run(["git", "-C", str(self.root), "switch", "-qc", "workflow/skills/0003-new"], check=True)
        subprocess.run([sys.executable, str(SCRIPT_DIR / "apply_move.py"), str(self.root), str(plan)], check=True)
        subprocess.run(["sh", str(helper), "create", str(self.root), "workflow/skills", "0003-new", "01-discovery.md", "workflow/skills/0003-new"], check=True)
        self.assertTrue((self.root / "docs/tasks/workflow/skills/0001-one").is_dir())
        self.assertTrue((self.root / "docs/tasks/workflow/skills/0002-two").is_dir())
        self.assertTrue((self.root / "docs/tasks/workflow/skills/0003-new").is_dir())

    def test_paths_reject_symlinked_categories_and_broken_destinations(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "docs/tasks/workflow").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(task_engine.DiagnosticError, "symlinks"):
            task_engine.next_id(self.root / "docs/tasks")
        (self.root / "docs/tasks/workflow").unlink()
        destination = self.root / "docs/tasks/workflow/skills/0001-broken"
        destination.parent.mkdir(parents=True)
        destination.symlink_to(self.root / "missing")
        with self.assertRaisesRegex(task_engine.DiagnosticError, "symlinks"):
            task_engine.validate_destination(self.root / "docs/tasks", "workflow/skills", "0001-broken", "workflow/skills/0001-broken")

    def test_switch_preflight_requires_an_explicit_clean_existing_task_branch(self) -> None:
        task = "workflow/skills/0001-one"
        make_task(self.root, task)
        self.commit_fixture()
        subprocess.run(["git", "-C", str(self.root), "branch", task], check=True)
        helper = SCRIPT_DIR / "task-helper.sh"
        subprocess.run(["sh", str(helper), "switch-preflight", str(self.root), task], check=True)
        missing = subprocess.run(
            ["sh", str(helper), "switch-preflight", str(self.root), "workflow/skills/0002-missing"],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(missing.returncode, 0)
        non_exact = subprocess.run(
            ["sh", str(helper), "switch-preflight", str(self.root), "workflow/skills/0001-one-extra"],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(non_exact.returncode, 0)
        other = Path(self.plans.name) / "other-worktree"
        subprocess.run(["git", "-C", str(self.root), "worktree", "add", "-q", str(other), task], check=True)
        elsewhere = subprocess.run(["sh", str(helper), "switch-preflight", str(self.root), task], text=True, capture_output=True)
        self.assertNotEqual(elsewhere.returncode, 0)
        subprocess.run(["git", "-C", str(self.root), "worktree", "remove", "--force", str(other)], check=True)
        (self.root / "untracked.txt").write_text("dirty\n", encoding="utf-8")
        dirty = subprocess.run(
            ["sh", str(helper), "switch-preflight", str(self.root), task], text=True, capture_output=True
        )
        self.assertNotEqual(dirty.returncode, 0)

    def test_rollback_continues_after_a_reference_restore_failure(self) -> None:
        first, second = self.root / "one.md", self.root / "two.md"
        attempts: list[Path] = []

        def fail_first(destination: Path, content: bytes) -> None:
            attempts.append(destination)
            if destination == second:
                raise OSError("fixture failure")

        with patch.object(apply_move, "atomic_write", side_effect=fail_first):
            errors = apply_move.rollback(self.root, [first, second], {first: b"one", second: b"two"}, [])
        self.assertEqual(attempts, [second, first])
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
