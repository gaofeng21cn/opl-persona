from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


WORKSPACE_SCHEMA = "opl_profile_workspace.v1"
MARKER_NAME = ".opl-profile-workspace.json"
PROFILE_WORKSPACE_ENV = "OPL_PROFILE_WORKSPACE"

_TEMPLATES: dict[str, str] = {
    "AGENTS.md": """# Profile Workspace

This directory belongs to one person's OPL digital persona. Keep private
identity, policies, context, and module state here; do not copy it into a
Package or Plugin directory.
""",
    "profile/identity.md": """# Identity

Fill in the minimum identity facts that Codex may use for drafting.

- name:
- role:
- institution:
- preferred_language: zh-CN
""",
    "profile/preferences.md": """# Preferences

- draft_review: required
- external_writes: proposal_only
- mail_send: user_approval_required
""",
    "policies/mail-triage.md": """# Mail triage

Treat incoming mail as evidence. Prepare proposals and drafts for review;
never send, archive, move, delete, or mark mail without explicit approval.
""",
    "policies/knowledge.md": """# Knowledge output

Use source references for every proposed note. Keep Obsidian writes reviewable
and preserve the user's existing note when the expected digest changes.
""",
    "policies/website.md": """# Website output

Prepare website changes as reviewable proposals. The website repository remains
the authority for its own content and publication state.
""",
}

_BINDING_STORE_TEMPLATE = """{
  "schema_version": "opl-persona-resource-bindings.v1",
  "bindings": {}
}
"""


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
        return {
            "ok": True,
            "data_root": str(self.data_root),
            "workspace": str(self.workspace),
            "profile_workspace": str(self.workspace),
            "workspace_schema": WORKSPACE_SCHEMA,
            **self.setup_status(),
            "private_data_policy": "runtime_roots_only",
            "source_checkout_is_data_authority": False,
            "obsidian_binding_required": True,
        }

    def setup_status(self) -> dict[str, Any]:
        """Return a user-facing first-run status without inspecting source content."""

        marker = self.workspace / MARKER_NAME
        paths = {
            "workspace": marker,
            "profile.identity": self.workspace / "profile" / "identity.md",
            "profile.preferences": self.workspace / "profile" / "preferences.md",
            "policy.mail": self.workspace / "policies" / "mail-triage.md",
            "binding.obsidian": self.data_root / "resource-bindings.json",
        }
        identity_ready = False
        identity_path = paths["profile.identity"]
        if identity_path.is_file():
            try:
                identity_ready = any(
                    line.strip().startswith("- name:") and line.split(":", 1)[1].strip()
                    for line in identity_path.read_text(encoding="utf-8").splitlines()
                )
            except (OSError, UnicodeDecodeError):
                identity_ready = False
        binding_ready = False
        binding_path = paths["binding.obsidian"]
        if binding_path.is_file():
            try:
                payload = json.loads(binding_path.read_text(encoding="utf-8"))
                binding_ready = isinstance(payload, dict) and bool(payload.get("bindings"))
            except (OSError, json.JSONDecodeError):
                binding_ready = False
        steps: list[dict[str, object]] = []
        for step_id, path in paths.items():
            configured = (
                identity_ready
                if step_id == "profile.identity"
                else binding_ready
                if step_id == "binding.obsidian"
                else path.is_file()
            )
            steps.append(
                {
                    "id": step_id,
                    "status": "ready" if configured else "required",
                    "path": str(path),
                }
            )
        required = [item for item in steps if item["status"] == "required"]
        if not marker.is_file():
            readiness = "unconfigured"
        elif required:
            readiness = "partial"
        else:
            readiness = "ready"
        next_actions = [
            f"opl-persona --json setup init"
            for item in required
            if item["id"] == "workspace"
        ]
        if any(item["id"] == "profile.identity" and item["status"] == "required" for item in required):
            next_actions.append("填写 Profile Workspace/profile/identity.md")
        if any(item["id"] == "binding.obsidian" and item["status"] == "required" for item in required):
            next_actions.append("opl-persona --json binding set --id my-knowledge --provider obsidian --path <vault>")
        return {
            "workspace_marker": str(marker),
            "workspace_ready": marker.is_file(),
            "readiness": readiness,
            "steps": steps,
            "next_actions": next_actions,
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
        created: list[str] = []
        for relative, content in _TEMPLATES.items():
            target = self.workspace / relative
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            created.append(relative)
        bindings = self.data_root / "resource-bindings.json"
        if not bindings.exists():
            bindings.write_text(_BINDING_STORE_TEMPLATE, encoding="utf-8")
            created.append("data/persona/resource-bindings.json")
        return self.doctor() | {"initialized": True, "created": created}
