#!/usr/bin/env python3
"""Validate project skill membership without editing host caches or configuration."""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def main() -> None:
    arguments = sys.argv[1:]
    if len(arguments) == 2:
        action, name, selected = "prepare", *arguments
    elif len(arguments) == 3:
        action, name, selected = arguments
    else:
        raise ValueError("Usage: package-skill.sh [prepare|validate] <skill-name> <repository-root>")
    require(action in {"prepare", "validate"}, "Unknown action; use prepare or validate")
    require(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is not None, "Invalid skill name")
    root = Path(selected).resolve(strict=True)
    plugin = root / "agents/plugins/forge"
    skill = plugin / "skills" / name
    for target in [plugin, skill]:
        for path in [target, *target.parents]:
            if path == root:
                break
            require(not path.is_symlink(), f"Refusing symlinked plugin path: {path}")
    require((root / "docs/bootstrap.md").is_file(), f"Selected root has no docs/bootstrap.md: {root}")
    require((skill / "SKILL.md").is_file(), f"Missing canonical skill: {skill}/SKILL.md")
    for path in plugin.rglob("*"):
        require(not path.is_symlink(), f"Plugin resources must be contained real files: {path}")
    for provider in ["codex", "claude"]:
        manifest = json.loads((plugin / f".{provider}-plugin/plugin.json").read_text())
        require(manifest.get("name") == "forge", f"Wrong {provider} plugin identity")
        require(isinstance(manifest.get("version"), str), f"Missing {provider} version")
        if provider == "codex":
            require(manifest.get("skills") == "./skills/", "Wrong Codex skills directory")
        catalog_path = root / (".agents/plugins/marketplace.json" if provider == "codex" else ".claude-plugin/marketplace.json")
        require(not catalog_path.is_symlink(), f"Catalog must be a real file: {catalog_path}")
        catalog = json.loads(catalog_path.read_text())
        entries = [entry for entry in catalog.get("plugins", []) if entry.get("name") == "forge"]
        source = {"source": "local", "path": "./agents/plugins/forge"} if provider == "codex" else "./agents/plugins/forge"
        require(len(entries) == 1 and entries[0].get("source") == source, f"Wrong or missing Forge entry: {catalog_path}")
    for host in [".agents", ".claude"]:
        directory = root / host / "skills"
        require(not directory.is_symlink(), f"Refusing symlinked discovery directory: {directory}")
        entry = directory / name
        require(not entry.exists() and not entry.is_symlink(), f"Duplicate loose skill requires explicit cleanup: {entry}")
    for helper in skill.rglob("*.sh"):
        subprocess.run(["sh", "-n", str(helper)], check=True)
        require(os.access(helper, os.X_OK), f"Shell helper is not executable: {helper}")
    print(f"Validated plugin skill: {skill}")
    if action == "prepare":
        print("Plugin packaged; host refresh required. Follow README.md: refresh each provider version/install, then start a new session.")
        print("Project-created skill remains project-owned; do not add it to .forge/managed-files.json.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"plugin-skill: {error}", file=sys.stderr)
        raise SystemExit(1)
