from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


WORKSPACE_SCHEMA = "opl_profile_workspace.v1"
MARKER_NAME = ".opl-profile-workspace.json"
PROFILE_WORKSPACE_ENV = "OPL_PROFILE_WORKSPACE"


def default_profile_workspace(environ: dict[str, str] | None = None) -> Path:
    """Return the selected Profile Workspace or the user's standard default."""

    env = os.environ if environ is None else environ
    configured = env.get(PROFILE_WORKSPACE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    home = Path.home()
    return home / "OPL" / "profiles" / (home.name or "default")


@dataclass(frozen=True)
class PersonaPaths:
    data_root: Path
    workspace: Path

    @classmethod
    def resolve(cls, *, environ: dict[str, str] | None = None) -> "PersonaPaths":
        workspace = default_profile_workspace(environ)
        return cls(workspace / "data" / "persona", workspace)

    def doctor(self) -> dict[str, object]:
        marker = self.workspace / MARKER_NAME
        return {
            "ok": True,
            "data_root": str(self.data_root),
            "workspace": str(self.workspace),
            "profile_workspace": str(self.workspace),
            "workspace_schema": WORKSPACE_SCHEMA,
            "workspace_marker": str(marker),
            "workspace_ready": marker.is_file(),
            "private_data_policy": "runtime_roots_only",
            "source_checkout_is_data_authority": False,
            "obsidian_binding_required": True,
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
