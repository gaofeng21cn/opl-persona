"""Owner-side, approval-gated Obsidian note application.

The proposal builder remains proposal-only.  This module is the narrowly
scoped owner adapter that may write after a separate, exact approval record.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .approvals import proposal_digest
from .bindings import ResourceBinding
from .core import OBSIDIAN_NOTE_CONTRACT, build_obsidian_note_proposals


RECEIPT_SCHEMA_VERSION = "opl-persona-obsidian-apply-receipt.v1"
_CAPABILITY_IDS = {"knowledge.obsidian.v1", "knowledge.documents.v1"}


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _safe_target_path(value: object) -> str:
    target_path = _required_text(value, "target_path")
    path = PurePosixPath(target_path)
    if (
        path.is_absolute()
        or path.suffix.casefold() != ".md"
        or any(part in {"", ".", "..", ".obsidian"} for part in path.parts)
        or target_path != path.as_posix()
    ):
        raise ValueError("target_path must be a safe, precise relative Markdown path")
    return target_path


def _proposal_identity(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the proposal against the public core builder, not just its ID."""

    if proposal.get("proposal_kind") != OBSIDIAN_NOTE_CONTRACT:
        raise ValueError("proposal_kind must be knowledge.obsidian.note.v1")
    if proposal.get("target") != OBSIDIAN_NOTE_CONTRACT:
        raise ValueError("proposal target is not the Obsidian owner")
    payload = proposal.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("proposal payload must be an object")
    target_path = _safe_target_path(payload.get("target_path"))
    if proposal.get("target_path") != target_path:
        raise ValueError("proposal target_path does not match payload")
    builder_input = dict(payload)
    builder_input["operation"] = proposal.get("operation")
    expected = build_obsidian_note_proposals(builder_input)["proposals"][0]
    for field in (
        "proposal_id",
        "proposal_kind",
        "target",
        "operation",
        "payload",
        "source_refs",
        "target_path",
        "expected_digest",
        "allowed_outputs",
        "forbidden_outputs",
    ):
        if proposal.get(field) != expected.get(field):
            raise ValueError(f"proposal identity mismatch for {field}")
    return dict(payload)


def _require_approval(proposal: Mapping[str, Any], approval: Mapping[str, Any]) -> None:
    current = proposal.get("approval")
    if not isinstance(current, Mapping) or current.get("required") is not True:
        raise ValueError("proposal is not review-gated")
    if approval.get("status") != "approved":
        raise ValueError("external write requires approval.status=approved")
    if approval.get("external_write_allowed") is not True:
        raise ValueError("external write requires explicit external_write_allowed=true")
    approval_ref = _required_text(approval.get("approval_ref"), "approval_ref")
    if approval_ref.startswith("proposal://"):
        raise ValueError("approval_ref must identify a user approval, not a proposal")
    if approval.get("proposal_id") != proposal.get("proposal_id"):
        raise ValueError("approval proposal_id mismatch")
    expected_digest = proposal_digest(proposal)
    if approval.get("proposal_digest") != expected_digest:
        raise ValueError("approval proposal_digest mismatch")


def _binding_vault(binding: ResourceBinding, vault: Path) -> Path:
    if binding.capability_id not in _CAPABILITY_IDS or binding.provider_id != "obsidian":
        raise ValueError("binding is not an Obsidian knowledge binding")
    if "notes.write" not in binding.scopes:
        raise ValueError("binding does not grant notes.write")
    root = vault.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Obsidian vault not found: {root}")
    if binding.resource_ref != root.as_uri():
        raise ValueError("binding resource_ref does not match the configured vault")
    return root


def _yaml_scalar(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) or item is None for item in value):
        return "[" + ", ".join(_yaml_scalar(item) for item in value) + "]"
    raise ValueError("frontmatter must contain scalar or scalar-list values")


def render_obsidian_note(payload: Mapping[str, Any]) -> bytes:
    """Render deterministic UTF-8 Markdown from an already validated payload."""

    target_path = _safe_target_path(payload.get("target_path"))
    del target_path  # Validation is intentional; content does not embed a filesystem path.
    frontmatter = payload.get("frontmatter", {})
    if not isinstance(frontmatter, Mapping):
        raise ValueError("frontmatter must be an object")
    metadata = dict(frontmatter)
    tags = payload.get("tags", [])
    links = payload.get("links", [])
    evidence_refs = payload.get("evidence_refs", [])
    if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
        raise ValueError("tags must be a list of strings")
    if not isinstance(links, list) or not all(isinstance(item, str) for item in links):
        raise ValueError("links must be a list of strings")
    if not isinstance(evidence_refs, list) or not all(isinstance(item, str) for item in evidence_refs):
        raise ValueError("evidence_refs must be a list of strings")
    if tags and "tags" not in metadata:
        metadata["tags"] = list(dict.fromkeys(item.strip() for item in tags if item.strip()))
    if evidence_refs and "source_refs" not in metadata:
        metadata["source_refs"] = list(dict.fromkeys(item.strip() for item in evidence_refs if item.strip()))
    lines: list[str] = []
    if metadata:
        lines.append("---")
        for key in sorted(metadata):
            key_text = _required_text(key, "frontmatter key")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", key_text):
                raise ValueError("frontmatter keys must use letters, digits, '_' or '-'")
            lines.append(f"{key_text}: {_yaml_scalar(metadata[key])}")
        lines.append("---")
        lines.append("")
    body = _required_text(payload.get("body"), "body")
    lines.extend(body.rstrip().splitlines())
    clean_links = [item.strip() for item in links if item.strip()]
    if clean_links:
        lines.extend(["", "## Links", ""])
        lines.extend(f"- {item}" for item in clean_links)
    return (("\n".join(lines).rstrip() + "\n").encode("utf-8"))


def _digest_bytes(value: bytes) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _resolve_target(root: Path, target_path: str) -> Path:
    current = root
    for part in PurePosixPath(target_path).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("target_path crosses a symlink")
    resolved = current.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise ValueError("target_path escapes the configured Obsidian vault")
    return resolved


def _atomic_write(path: Path, content: bytes, *, mode: int, expected_digest: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".opl-persona-note.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if expected_digest == "absent":
            if path.exists():
                raise ValueError("target changed after approval; expected an absent note")
        elif not path.is_file() or _digest_bytes(path.read_bytes()) != expected_digest:
            raise ValueError("target changed after approval; expected_digest no longer matches")
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:  # pragma: no cover - platform-specific directory fsync
            directory_fd = -1
        if directory_fd >= 0:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_approved_obsidian_note(
    proposal: Mapping[str, Any],
    approval: Mapping[str, Any],
    *,
    binding: ResourceBinding,
    vault: Path,
) -> dict[str, Any]:
    """Apply one approved note and return an authority readback receipt."""

    payload = _proposal_identity(proposal)
    _require_approval(proposal, approval)
    root = _binding_vault(binding, vault)
    target = _resolve_target(root, _safe_target_path(payload["target_path"]))
    operation = _required_text(proposal.get("operation"), "operation")
    expected_digest = _required_text(payload.get("expected_digest"), "expected_digest")
    exists = target.exists()
    if operation == "create":
        if expected_digest != "absent" or exists:
            raise ValueError("create requires an absent target and expected_digest=absent")
    elif operation == "update":
        if not exists or not target.is_file():
            raise FileNotFoundError(f"Obsidian note does not exist: {payload['target_path']}")
        observed = _digest_bytes(target.read_bytes())
        if observed != expected_digest:
            raise ValueError("expected_digest does not match the current Obsidian note")
    else:
        raise ValueError("operation must be create or update")
    content = render_obsidian_note(payload)
    mode = stat.S_IMODE(target.stat().st_mode) if exists else 0o644
    _atomic_write(target, content, mode=mode, expected_digest=expected_digest)
    readback = target.read_bytes()
    result_digest = _digest_bytes(readback)
    if readback != content:
        raise RuntimeError("Obsidian authority readback differs from the atomic write")
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "applied",
        "proposal_id": proposal["proposal_id"],
        "proposal_digest": proposal_digest(proposal),
        "approval_ref": approval["approval_ref"],
        "binding": {
            "capability_id": binding.capability_id,
            "provider_id": binding.provider_id,
            "resource_ref": binding.resource_ref,
            "scopes": list(binding.scopes),
        },
        "authority_ref": f"{binding.resource_ref.rstrip('/')}/{payload['target_path']}",
        "target_path": payload["target_path"],
        "operation": operation,
        "expected_digest": expected_digest,
        "readback": {
            "digest": result_digest,
            "bytes": len(readback),
            "matches_written_bytes": True,
        },
    }
