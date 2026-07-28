from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROFILE_WORKSPACE_ENV = "OPL_PROFILE_WORKSPACE"
PERSONA_HOME_ENV = "OPL_PERSONA_HOME"
PERSONA_WORKSPACE_ENV = "OPL_PERSONA_WORKSPACE"
WORKSPACE_SCHEMA = "opl_profile_workspace.v1"
MARKER_NAME = ".opl-profile-workspace.json"
LEGACY_MARKER_NAME = ".opl-persona-workspace.json"


def default_profile_workspace(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = env.get(PROFILE_WORKSPACE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    profile_name = Path.home().name or "default"
    return Path.home() / "OPL" / "profiles" / profile_name


@dataclass(frozen=True)
class PersonaPaths:
    data_root: Path
    workspace: Path

    @classmethod
    def resolve(cls, *, environ: dict[str, str] | None = None) -> "PersonaPaths":
        env = os.environ if environ is None else environ
        data = env.get(PERSONA_HOME_ENV, "").strip()
        if not data:
            data = str(default_profile_workspace(env) / "data" / "persona")
        workspace = env.get(PERSONA_WORKSPACE_ENV, "").strip()
        if not workspace:
            workspace = str(default_profile_workspace(env))
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
        marker = self.workspace / MARKER_NAME
        legacy_marker = self.workspace / LEGACY_MARKER_NAME
        return {
            "ok": True,
            "data_root": str(self.data_root),
            "workspace": str(self.workspace),
            "profile_workspace": str(self.workspace),
            "workspace_schema": WORKSPACE_SCHEMA,
            "workspace_marker": str(marker),
            "workspace_ready": marker.is_file() or legacy_marker.is_file(),
            "private_data_policy": "runtime_roots_only",
            "source_checkout_is_data_authority": False,
            "obsidian_vault": str(vault),
            "obsidian_vault_exists": vault.is_dir(),
        }

    def init_workspace(self) -> dict[str, object]:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        for relative in (
            "profile",
            "policies",
            "context",
            "templates",
            "exports",
            "data/relay",
            "data/persona",
        ):
            (self.workspace / relative).mkdir(parents=True, exist_ok=True)
        marker = self.workspace / MARKER_NAME
        expected = '{\n  "schema": "opl_profile_workspace.v1"\n}\n'
        if marker.exists() and marker.read_text(encoding="utf-8") != expected:
            raise ValueError(f"workspace marker already exists with different content: {marker}")
        marker.write_text(expected, encoding="utf-8")
        return self.doctor() | {"initialized": True}
