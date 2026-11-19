#!/usr/bin/env python3
"""Validate the AI-workflow files installed by the Forge project template."""

from __future__ import annotations

import argparse
import json
import re
import stat
import subprocess
import sys
from pathlib import Path


SKILLS = (
    "create-project-skill",
    "create-task",
    "implement-phase",
    "initialize-project",
    "push",
    "shared-dev-methodology",
)

REQUIRED_FILES = {
    "AGENTS.md",
    "README.md",
    ".vscode/tasks.json",
    "scripts/validation/validate_methodology.py",
    "docs/ai-context.md",
    "docs/bootstrap.md",
    "docs/project-spec.md",
    "docs/TODO.md",
    "docs/tasks/README.md",
    "docs/template/decisions.md",
    "docs/template/state.md",
    "docs/template/phases/README.md",
    "docs/template/phases/phase.md",
    "agents/plugins/forge/skills/create-project-skill/scripts/package-skill.sh",
    "agents/plugins/forge/skills/create-task/scripts/task-helper.sh",
    "agents/plugins/forge/skills/create-task/scripts/task_engine.py",
    "agents/plugins/forge/skills/create-task/scripts/apply_move.py",
    "agents/plugins/forge/skills/create-task/scripts/complete_task.py",
    "agents/plugins/forge/skills/implement-phase/scripts/implement-phase.sh",
    "agents/plugins/forge/skills/initialize-project/scripts/project-docs.sh",
    "agents/plugins/forge/skills/push/scripts/push-check.sh",
}

REQUIRED_HEADINGS = {
    "AGENTS.md": ("# Repository Agent Instructions", "# Repository Agent Instructions"),
    "README.md": ("## Documentation",),
    "docs/ai-context.md": ("# AI Context", "## Project Summary", "## Technology"),
    "docs/bootstrap.md": ("# AI Bootstrap", "## Startup Order", "## Task Folder Workflow", "## Operating Rules"),
    "docs/project-spec.md": ("# Project Specification", "## Overview", "## Requirements", "## Success Criteria"),
    "docs/tasks/README.md": ("# Tasks", "## Creating a Task", "## Implementing Phases", "## Conventions"),
    "docs/template/decisions.md": ("# Decisions", "## Pending"),
    "docs/template/state.md": ("# Task: `<Title>`", "## Todo", "## Changes Made", "## Validation"),
    "docs/template/phases/README.md": ("# Phases",),
    "docs/template/phases/phase.md": (
        "# Phase: `<Title>`",
        "## Recommended Model",
        "### Codex",
        "### Claude Code",
        "## Work Completed",
        "## Validation",
    ),
}

VERBOSE_RECOMMENDATION_FIELDS = (
    "Cost profile",
    "Expected token usage",
    "Rationale",
    "Reassess if",
    "Guidance checked",
)
PHASE_NAME = re.compile(r"[0-9]{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")


def display(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def check_file(path: Path, root: Path, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing required file: {display(path, root)}")


def check_headings(root: Path, errors: list[str]) -> None:
    for relative_path, headings in REQUIRED_HEADINGS.items():
        path = root / relative_path
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for heading in headings:
            if heading not in text:
                errors.append(f"{relative_path} is missing required section: {heading}")

    readme = root / "README.md"
    if readme.is_file():
        first_content_line = next(
            (line for line in readme.read_text(encoding="utf-8").splitlines() if line.strip()),
            "",
        )
        if not first_content_line.startswith("# ") or not first_content_line[2:].strip():
            errors.append("README.md must start with a non-empty level-one project heading")

    check_recommendation_block(
        root / "docs/template/phases/phase.md", root, errors, require_both_providers=True
    )


def check_recommendation_block(
    path: Path, root: Path, errors: list[str], *, require_both_providers: bool = False
) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if "## Recommended Model" not in text:
        return
    block = text.split("## Recommended Model", 1)[1].split("\n## ", 1)[0]
    for field in VERBOSE_RECOMMENDATION_FIELDS:
        if f"- {field}:" in block:
            errors.append(f"{display(path, root)} uses verbose recommendation field: {field}")
    if block.count("- Model:") == 0 or block.count("- Model:") != block.count("- Effort:"):
        errors.append(f"{display(path, root)} must pair each recommendation model with one effort")
    if require_both_providers and ("### Codex" not in block or "### Claude Code" not in block):
        errors.append(f"{display(path, root)} must include compact Codex and Claude Code recommendations")


def check_docs(root: Path, errors: list[str]) -> None:
    docs = root / "docs"
    if not docs.is_dir():
        errors.append("missing required directory: docs")
        return

    expected_docs_entries = {"ai-context.md", "bootstrap.md", "project-spec.md", "TODO.md", "tasks", "template"}
    for child in docs.iterdir():
        if child.name not in expected_docs_entries:
            errors.append(f"unexpected documentation path: {display(child, root)}")

    tasks = docs / "tasks"
    if not tasks.is_dir():
        errors.append("missing required directory: docs/tasks")
        return

    template = docs / "template"
    expected_template_entries = {"decisions.md", "state.md", "phases"}
    if template.is_dir():
        for child in template.iterdir():
            if child.name not in expected_template_entries:
                errors.append(f"unexpected template documentation path: {display(child, root)}")
        phases = template / "phases"
        if phases.is_dir():
            for child in phases.iterdir():
                if child.name not in {"README.md", "phase.md"}:
                    errors.append(f"unexpected template phase path: {display(child, root)}")

    helper = root / "agents/plugins/forge/skills/create-task/scripts/task-helper.sh"
    if helper.is_file():
        result = subprocess.run(
            ["sh", str(helper), "validate-todo", str(root)],
            text=True,
            capture_output=True,
        )
        if result.returncode:
            detail = (result.stdout or result.stderr).strip().replace("\n", " ")
            errors.append(f"create-task task/TODO validation failed: {detail or 'no diagnostic'}")
            return
        try:
            entries = json.loads(result.stdout)["entries"]
            paths = sorted({entry["path"] for entry in entries})
        except (KeyError, TypeError, json.JSONDecodeError):
            errors.append("create-task task/TODO validation returned invalid entries")
            return
        for relative in paths:
            if not isinstance(relative, str):
                errors.append("create-task task/TODO validation returned an invalid task path")
                continue
            check_task_phases(tasks / relative, root, errors)


def check_task_phases(task: Path, root: Path, errors: list[str]) -> None:
    phases = task / "phases"
    if not phases.is_dir():
        errors.append(f"task is missing required path: {display(phases, root)}")
        return
    for phase in phases.iterdir():
        if not phase.is_file() or not PHASE_NAME.fullmatch(phase.name):
            errors.append(f"invalid task phase path: {display(phase, root)}")
        else:
            check_recommendation_block(phase, root, errors)


def check_skills(root: Path, errors: list[str], skills: tuple[str, ...]) -> None:
    canonical_skills = root / "agents/plugins/forge/skills"
    if not canonical_skills.is_dir():
        errors.append("missing required directory: agents/plugins/forge/skills")
        return

    actual_skills = {child.name for child in canonical_skills.iterdir()}
    expected_skills = set(skills)
    for name in sorted(expected_skills - actual_skills):
        errors.append(f"missing required skill: agents/plugins/forge/skills/{name}")
    for name in sorted(actual_skills | expected_skills):
        skill = canonical_skills / name
        check_file(skill / "SKILL.md", root, errors)
        check_file(skill / "agents/openai.yaml", root, errors)
        if not (skill / "SKILL.md").is_file():
            continue
        content = (skill / "SKILL.md").read_text(encoding="utf-8")
        if f"name: {name}" not in content or "description:" not in content:
            errors.append(f"agents/plugins/forge/skills/{name}/SKILL.md has invalid skill metadata")

    plugin = root / "agents/plugins/forge"
    for path in plugin.rglob("*"):
        if path.is_symlink():
            errors.append(f"plugin resource must not be a symlink: {display(path, root)}")
    for provider in ("codex", "claude"):
        manifest_path = plugin / f".{provider}-plugin/plugin.json"
        catalog_path = root / (".agents/plugins/marketplace.json" if provider == "codex" else ".claude-plugin/marketplace.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("name") != "forge" or not isinstance(manifest.get("version"), str):
                errors.append(f"invalid Forge manifest: {display(manifest_path, root)}")
            if provider == "codex" and manifest.get("skills") != "./skills/":
                errors.append("Codex manifest must declare ./skills/")
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            entries = [entry for entry in catalog["plugins"] if entry.get("name") == "forge"]
            source = {"source": "local", "path": "./agents/plugins/forge"} if provider == "codex" else "./agents/plugins/forge"
            if len(entries) != 1 or entries[0].get("source") != source:
                errors.append(f"invalid Forge catalog source: {display(catalog_path, root)}")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", catalog.get("name", "")):
                errors.append(f"invalid catalog identity: {display(catalog_path, root)}")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            errors.append(f"invalid {provider} plugin package: {error}")
    for discovery_directory in (".agents/skills", ".claude/skills"):
        for name in actual_skills:
            entry = root / discovery_directory / name
            if entry.exists() or entry.is_symlink():
                errors.append(f"duplicate loose skill: {display(entry, root)}")


def check_configuration(root: Path, errors: list[str]) -> None:
    gitignore_variants = [root / "gitignore.template", root / ".gitignore"]
    present_gitignores = [path for path in gitignore_variants if path.is_file()]
    if not present_gitignores:
        errors.append("missing required file: gitignore.template (template) or .gitignore (generated project)")
    elif len(present_gitignores) > 1:
        errors.append("expected exactly one Git ignore template: gitignore.template or .gitignore")

    tasks_file = root / ".vscode/tasks.json"
    if tasks_file.is_file():
        try:
            tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            errors.append(f".vscode/tasks.json is invalid JSON: {error.msg}")
        else:
            if not isinstance(tasks, dict) or tasks.get("version") != "2.0.0" or not isinstance(tasks.get("tasks"), list):
                errors.append(".vscode/tasks.json must contain version 2.0.0 and a tasks list")

    for script in (
        root / "agents/plugins/forge/skills/create-project-skill/scripts/package-skill.sh",
        root / "agents/plugins/forge/skills/create-task/scripts/task-helper.sh",
        root / "agents/plugins/forge/skills/implement-phase/scripts/implement-phase.sh",
        root / "agents/plugins/forge/skills/initialize-project/scripts/project-docs.sh",
        root / "agents/plugins/forge/skills/push/scripts/push-check.sh",
    ):
        if script.is_file():
            content = script.read_text(encoding="utf-8")
            if not content.startswith("#!/bin/sh\n") or "set -eu" not in content:
                errors.append(f"{display(script, root)} must remain a strict POSIX shell script")
            if not script.stat().st_mode & stat.S_IXUSR:
                errors.append(f"{display(script, root)} must be executable")


def validate(root: Path, skills: tuple[str, ...] = SKILLS) -> list[tuple[str, list[str]]]:
    required_file_errors: list[str] = []
    for relative_path in sorted(REQUIRED_FILES):
        check_file(root / relative_path, root, required_file_errors)

    documentation_errors: list[str] = []
    check_headings(root, documentation_errors)
    check_docs(root, documentation_errors)

    skill_errors: list[str] = []
    check_skills(root, skill_errors, skills)

    configuration_errors: list[str] = []
    check_configuration(root, configuration_errors)

    return [
        ("Required methodology files", required_file_errors),
        ("Documentation and task structure", documentation_errors),
        ("Plugin skills, manifests, and catalogs", skill_errors),
        ("Configuration, scripts, and workflow", configuration_errors),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="project root to validate (defaults to the root containing this script)",
    )
    parser.add_argument(
        "--extra-skill",
        action="append",
        default=[],
        help="additional project-only canonical skill expected under the selected root",
    )
    arguments = parser.parse_args()
    root = arguments.root.resolve()

    invalid_extra_skills = [name for name in arguments.extra_skill if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)]
    if invalid_extra_skills:
        parser.error(f"invalid extra skill name: {invalid_extra_skills[0]}")
    skills = tuple(dict.fromkeys((*SKILLS, *arguments.extra_skill)))

    results = validate(root, skills)
    failed = any(errors for _, errors in results)
    output = sys.stderr if failed else sys.stdout

    print(f"Methodology validation report for {root}:", file=output)
    for label, errors in results:
        if errors:
            print(f"❌ {label}", file=output)
            for error in errors:
                print(f"   - {error}", file=output)
        else:
            print(f"✅ {label}", file=output)

    if failed:
        print("❌ Methodology validation failed.", file=output)
        return 1

    print("✅ Methodology validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
