#!/usr/bin/env python3
"""Resolve the installed OPL Persona v2 package entrypoint without a source checkout."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys


def installed_entrypoint(state_dir: Path) -> Path:
    package_root = state_dir / "packages" / "opl-persona"
    candidates = []
    for root in package_root.iterdir():
        if root.is_symlink() or not root.is_dir() or not re.fullmatch(r"\d+\.\d+\.\d+", root.name):
            continue
        try:
            manifest = json.loads((root / "opl-package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        identity = manifest.get("identity") if isinstance(manifest, dict) else None
        entrypoint = root / "bin" / "opl-persona"
        if (
            isinstance(identity, dict)
            and manifest.get("schema_version") == "opl.package.v2"
            and identity.get("id") == "opl-persona"
            and identity.get("version") == root.name
            and entrypoint.is_file()
        ):
            candidates.append((tuple(int(part) for part in root.name.split(".")), entrypoint))
    if not candidates:
        raise ValueError("no valid installed Persona v2 package is available")
    return max(candidates)[1]


def main() -> None:
    try:
        state_dir = Path(os.environ.get("OPL_STATE_DIR", str(Path.home() / ".opl/state"))).expanduser().resolve()
        entrypoint = installed_entrypoint(state_dir)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"opl-persona: {exc}") from exc
    os.execv(sys.executable, [sys.executable, str(entrypoint), *sys.argv[1:]])


if __name__ == "__main__":
    main()
