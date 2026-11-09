#!/usr/bin/env python3
"""Resolve the enabled native Codex Persona carrier without a source checkout."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import tomllib


def installed_entrypoint(codex_root: Path) -> Path:
    config = tomllib.loads((codex_root / "config.toml").read_text(encoding="utf-8"))
    if config.get("plugins", {}).get("opl-persona@opl-persona", {}).get("enabled") is not True:
        raise ValueError("opl-persona@opl-persona is not enabled in Codex")
    cache = codex_root / "plugins" / "cache" / "opl-persona" / "opl-persona"
    candidates = []
    for root in cache.iterdir():
        if root.is_symlink() or not root.is_dir() or not re.fullmatch(r"\d+\.\d+\.\d+", root.name):
            continue
        try:
            plugin = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
            package = json.loads((root / "opl-package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entrypoint = root / "bin" / "opl-persona"
        if (plugin.get("name") == package.get("package_id") == "opl-persona"
                and plugin.get("version") == package.get("version") == root.name and entrypoint.is_file()):
            candidates.append((tuple(int(part) for part in root.name.split(".")), entrypoint))
    if not candidates:
        raise ValueError("no valid installed Persona carrier is available")
    return max(candidates)[1]


def main() -> None:
    try:
        root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
        entrypoint = installed_entrypoint(root)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"opl-persona: {exc}") from exc
    os.execv(sys.executable, [sys.executable, str(entrypoint), *sys.argv[1:]])


if __name__ == "__main__":
    main()
