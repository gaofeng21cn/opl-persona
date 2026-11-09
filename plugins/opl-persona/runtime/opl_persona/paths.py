from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


from ._opl_profile_workspace import (
    MARKER_NAME,
    PROFILE_WORKSPACE_ENV,
    WORKSPACE_SCHEMA,
    default_profile_workspace,
    initialize_profile_workspace,
)

_TEMPLATES: dict[str, str] = {
    "AGENTS.md": """# Profile Workspace

This directory holds one person's private OPL control state and task context.
Existing personal knowledge remains in its selected source. Create local
knowledge bodies only when this workspace is their canonical home; do not copy
personal knowledge into a Package or Plugin directory.

The user owns personal knowledge bodies. Persona owns derived context,
interpretation and reviewable proposals, not the maintenance authority of the
source. Framework manages source registration and version mechanics;
`data/knowledge-sources.json` may hold the single private source registry, and
`shared/memory/knowledge-bindings.json` selects explicit sources and scopes.
These files contain references and review metadata, never a second knowledge
body. Other workspaces bind the same registry instead of copying its state.
""",
    "policies/mail-triage.md": """# Mail triage

Treat incoming mail as evidence. Prepare proposals and drafts for review;
never send, archive, move, delete, or mark mail without explicit approval.
""",
    "policies/knowledge.md": """# Knowledge output

Use source references for every proposed note. Keep writes to the selected
knowledge source reviewable and preserve existing notes when their expected
digest changes. A resource binding identifies a source; it does not copy its
body into this workspace or authorize a write.
""",
    "policies/website.md": """# Website output

Prepare website changes as reviewable proposals. The website repository remains
the authority for its own content and publication state.
""",
}

_LOCAL_KNOWLEDGE_TEMPLATES: dict[str, str] = {
    "profile/identity.md": """# Identity

This is the canonical local identity note when no existing source is selected.
Fill in the minimum identity facts needed for drafting.

- name:
- role:
- institution:
- preferred_language: zh-CN
""",
    "profile/preferences.md": """# Preferences

This is the canonical local preferences note when no existing source is selected.

- draft_review: required
- external_writes: proposal_only
- mail_send: user_approval_required
""",
}

_BINDING_STORE_TEMPLATE = """{
  "schema_version": "opl-persona-resource-bindings.v1",
  "bindings": {}
}
"""


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
            "external_knowledge_binding_required": False,
        }

    def setup_status(self) -> dict[str, Any]:
        """Return a user-facing first-run status without inspecting source content."""

        marker = self.workspace / MARKER_NAME
        paths = {
            "workspace": marker,
            "profile.identity": self.workspace / "profile" / "identity.md",
            "profile.preferences": self.workspace / "profile" / "preferences.md",
            "policy.mail": self.workspace / "policies" / "mail-triage.md",
            "binding.knowledge": self.data_root / "resource-bindings.json",
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
        binding_path = paths["binding.knowledge"]
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
                if step_id == "binding.knowledge"
                else path.is_file()
            )
            required = step_id in {"workspace", "policy.mail"}
            steps.append(
                {
                    "id": step_id,
                    "status": "ready" if configured else "required" if required else "optional",
                    "required": required,
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
        return {
            "workspace_marker": str(marker),
            "workspace_ready": marker.is_file(),
            "readiness": readiness,
            "readiness_scope": "runtime_configuration",
            "steps": steps,
            "next_actions": next_actions,
            "knowledge_setup": {
                "required": False,
                "local_templates_command": "opl-persona --json setup init --local-knowledge",
                "binding_command": "opl-persona --json binding set --id my-knowledge --provider <obsidian|markdown> --path <directory>",
                "policy": "Keep one canonical body; use an existing source or opt into local notes.",
            },
        }

    def init_workspace(self, *, local_knowledge: bool = False) -> dict[str, object]:
        self.data_root.mkdir(parents=True, exist_ok=True)
        templates = _TEMPLATES | (_LOCAL_KNOWLEDGE_TEMPLATES if local_knowledge else {})
        created = initialize_profile_workspace(self.workspace, templates)
        bindings = self.data_root / "resource-bindings.json"
        if not bindings.exists():
            bindings.write_text(_BINDING_STORE_TEMPLATE, encoding="utf-8")
            created.append("data/persona/resource-bindings.json")
        return self.doctor() | {"initialized": True, "created": created}
