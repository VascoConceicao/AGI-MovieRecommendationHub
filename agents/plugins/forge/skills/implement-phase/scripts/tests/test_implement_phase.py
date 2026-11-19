#!/usr/bin/env python3
"""Focused TODO-selection fixtures for the implement-phase consumer."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "implement-phase.sh"


def phase() -> str:
    return """## Status

Not started.

## Recommended Model

### Codex

- Model: `gpt-5.6-terra`
- Effort: `medium`

### Claude Code

- Model: `Unverified`
- Effort: `medium (advisory)`
"""


class ImplementPhaseResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="forge-implement-phase-")
        self.root = Path(self.temporary.name)
        (self.root / "docs/tasks").mkdir(parents=True)
        (self.root / "docs/template").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def add_task(self, relative: str) -> None:
        task = self.root / "docs/tasks" / relative
        (task / "phases").mkdir(parents=True)
        (task / "state.md").write_text("# Task: Fixture\n", encoding="utf-8")
        (task / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
        (task / "phases/01-work.md").write_text(phase(), encoding="utf-8")

    def write_todo(self, entries: list[tuple[str, str]]) -> None:
        lines = ["# TODO", ""]
        previous: list[str] = []
        for relative, marker in entries:
            categories, name = relative.split("/")[:-1], relative.split("/")[-1]
            common = 0
            while common < len(previous) and common < len(categories) and previous[common] == categories[common]:
                common += 1
            for depth, category in enumerate(categories[common:], common):
                lines.append(f"{'  ' * depth}- `{category}/`")
            previous = categories
            checked = "x" if marker == "Completed" else " "
            tail = " — dependency" if marker == "Blocked" else ""
            lines.append(f"{'  ' * len(categories)}- [{checked}] **{marker}** — [Task](tasks/{relative}/state.md){tail}")
        lines.extend(["", "## Chronology", ""])
        ordinal = 0
        for relative, marker in entries:
            if marker == "Completed":
                ordinal += 1
                lines.append(f"{ordinal}. [Task](tasks/{relative}/state.md)")
        (self.root / "docs/TODO.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def on_branch(self, branch: str) -> None:
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "fixture@example.test"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)
        subprocess.run(["git", "-C", str(self.root), "branch", "-M", branch], check=True)

    def resolve(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["sh", str(SCRIPT), "resolve", str(self.root), *arguments], text=True, capture_output=True)

    def test_current_next_and_deep_paths_use_the_create_task_resolver(self) -> None:
        current = "a/b/c/d/e/f/g/0001-current"
        following = "workflow/0002-next"
        self.add_task(current)
        self.add_task(following)
        self.write_todo([(current, "Current"), (following, "Next")])
        self.on_branch(current)
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "01-work.md\tNot started\tgpt-5.6-terra\tmedium\tUnverified\tmedium (advisory)\n")

        self.write_todo([(current, "Queued"), (following, "Next")])
        subprocess.run(["git", "-C", str(self.root), "branch", "-M", following], check=True)
        self.assertEqual(self.resolve().returncode, 0)

    def test_ambiguous_and_ineligible_queues_stop_with_resolver_diagnostics(self) -> None:
        first, second = "workflow/0001-first", "workflow/0002-second"
        self.add_task(first)
        self.add_task(second)
        self.write_todo([(first, "Current"), (second, "Current")])
        self.on_branch(first)
        ambiguous = self.resolve()
        self.assertNotEqual(ambiguous.returncode, 0)
        self.assertIn("code=todo-resolution", ambiguous.stderr)
        self.assertIn("AMBIGUOUS_TODO", ambiguous.stderr)

        self.write_todo([(first, "Queued"), (second, "Blocked")])
        ineligible = self.resolve()
        self.assertNotEqual(ineligible.returncode, 0)
        self.assertIn("NO_SELECTED_TASK", ineligible.stderr)

    def test_branch_disagreement_stops_after_todo_selection(self) -> None:
        task = "workflow/0001-current"
        self.add_task(task)
        self.write_todo([(task, "Current")])
        self.on_branch("workflow/0001-other")
        result = self.resolve()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("code=branch-disagreement", result.stderr)
        self.assertIn(f"selected={task}", result.stderr)

if __name__ == "__main__":
    unittest.main(verbosity=2)
