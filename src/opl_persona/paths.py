from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PersonaPaths:
    data_root: Path
    workspace: Path

    @classmethod
    def resolve(cls, *, environ: dict[str, str] | None = None) -> "PersonaPaths":
        env = os.environ if environ is None else environ
        data = env.get("OPL_PERSONA_HOME", "").strip()
        if not data:
            data = env.get("OPL_RELAY_HOME", "").strip()
        if not data:
            data = str(Path.home() / ".opl-persona")
        workspace = env.get("OPL_PERSONA_WORKSPACE", "").strip()
        if not workspace:
            workspace = str(Path(data).expanduser() / "workspaces" / "default")
        return cls(Path(data).expanduser(), Path(workspace).expanduser())

    @staticmethod
    def default_obsidian_vault(environ: dict[str, str] | None = None) -> Path:
        env = os.environ if environ is None else environ
        configured = env.get("OPL_PERSONA_OBSIDIAN_VAULT", "").strip()
        if configured:
            return Path(configured).expanduser()
        return Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents"

    def doctor(self) -> dict[str, object]:
        vault = self.default_obsidian_vault()
        return {
            "ok": True,
            "data_root": str(self.data_root),
            "workspace": str(self.workspace),
            "private_data_policy": "runtime_roots_only",
            "source_checkout_is_data_authority": False,
            "obsidian_vault": str(vault),
            "obsidian_vault_exists": vault.is_dir(),
        }

    def init_workspace(self) -> dict[str, object]:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        return self.doctor() | {"initialized": True}
