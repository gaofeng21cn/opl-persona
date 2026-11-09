"""Consume authorized Framework knowledge reads and validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .paths import PersonaPaths


KNOWLEDGE_DOMAIN = "persona"


def _framework_command(paths: PersonaPaths, command: str, **options: str) -> list[str]:
    argv = ["opl", "knowledge", command, "--workspace", str(paths.workspace), "--domain", KNOWLEDGE_DOMAIN]
    project = os.environ.get("OPL_PROJECT_ROOT")
    if project:
        argv += ["--project", project]
    for key, value in options.items():
        argv += [f"--{key.replace('_', '-')}", value]
    argv.append("--json")
    return argv


def _run_framework(paths: PersonaPaths, command: str, **options: str) -> dict[str, Any]:
    try:
        result = subprocess.run(_framework_command(paths, command, **options), capture_output=True,
                                text=True, timeout=30, check=False,
                                env=os.environ | {"OPL_PROFILE_WORKSPACE": str(paths.workspace)})
        if result.returncode:
            raise ValueError(f"Framework knowledge {command} failed")
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or value.get("version") != "g2":
            raise ValueError(f"Framework returned an invalid knowledge {command} response")
        return value
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Framework knowledge {command} requires current Framework readback") from exc


def resolve_knowledge_target(target: Path, paths: PersonaPaths) -> dict[str, Any]:
    """Identify registered bodies before allowing the ordinary document adapter."""
    if not (paths.workspace / "shared/memory/knowledge-bindings.json").exists():
        return {"registered": False}
    value = _run_framework(paths, "resolve-target", path=str(target)).get("knowledge_target")
    if not isinstance(value, dict) or type(value.get("registered")) is not bool:
        raise ValueError("Framework returned an invalid knowledge target")
    return value


def propose_knowledge_writeback(knowledge_id: str, paths: PersonaPaths, replacement: bytes, *,
                                source_refs: list[str], target_scope: dict[str, str] | None = None,
                                content_kind: str = "policy", proposed_rule_or_mechanism: str = "",
                                evidence_class: str = "persona-derived", review_requirement: str = "owner review required") -> dict[str, Any]:
    if not source_refs or not replacement:
        raise ValueError("knowledge writeback requires source_refs and a non-empty replacement")
    proposal = {
        "source_refs": source_refs,
        "target_scope": target_scope or {"kind": "topic", "id": knowledge_id},
        "content_kind": content_kind,
        "proposed_rule_or_mechanism": proposed_rule_or_mechanism or f"Persona update for {knowledge_id}",
        "evidence_class": evidence_class,
        "review_requirement": review_requirement,
    }
    with tempfile.TemporaryDirectory(prefix="persona-knowledge-writeback-") as temporary:
        root = Path(temporary)
        proposal_path, body_path = root / "proposal.json", root / "replacement.md"
        proposal_path.write_text(json.dumps(proposal, ensure_ascii=False), encoding="utf-8")
        body_path.write_bytes(replacement)
        envelope = _run_framework(paths, "propose", id=knowledge_id,
                                  proposal=str(proposal_path), body=str(body_path))
    result = envelope.get("knowledge_proposal")
    if not isinstance(result, dict) or not isinstance(result.get("proposal_id"), str):
        raise ValueError("Framework returned an invalid knowledge proposal")
    return result


def review_knowledge_writeback(paths: PersonaPaths, proposal_id: str, *, approval_ref: str,
                               reviewer: str, reviewed_at: str, next_review_at: str,
                               decision: str = "accepted") -> dict[str, Any]:
    envelope = _run_framework(paths, "review", **{
        "proposal-id": proposal_id, "decision": decision, "reviewer": reviewer,
        "review-ref": approval_ref, "reviewed-at": reviewed_at,
        "next-review-at": next_review_at,
    })
    result = envelope.get("knowledge_review")
    if not isinstance(result, dict):
        raise ValueError("Framework returned an invalid knowledge review")
    return result


def apply_knowledge_writeback(paths: PersonaPaths, proposal_id: str) -> dict[str, Any]:
    envelope = _run_framework(paths, "apply", **{"proposal-id": proposal_id})
    result = envelope.get("knowledge_writeback")
    if not isinstance(result, dict) or result.get("status") != "applied":
        raise ValueError("Framework returned an invalid knowledge writeback receipt")
    return result


def register_knowledge_source(paths: PersonaPaths, registration: dict[str, Any], *,
                               expected_sha256: str, approval_ref: str,
                               review: dict[str, str], expected_body_path: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="persona-knowledge-registration-") as temporary:
        item_path = Path(temporary) / "item.json"
        item_path.write_text(json.dumps(registration["item"], ensure_ascii=False), encoding="utf-8")
        envelope = _run_framework(paths, "register", registry=registration["registry_ref"],
            item=str(item_path), expected_sha256=expected_sha256,
            expected_body_path=str(expected_body_path), review_ref=approval_ref, **review)
    result = envelope.get("knowledge_registration")
    if not isinstance(result, dict) or result.get("status") != "registered":
        raise ValueError("Framework returned an invalid knowledge registration receipt")
    return result


def read_knowledge_source(knowledge_id: str, paths: PersonaPaths) -> dict[str, str]:
    """Read one accepted private source through Framework's authorized resolver."""
    if not isinstance(knowledge_id, str) or not re.fullmatch(r"[a-z][a-z0-9._-]*", knowledge_id):
        raise ValueError("knowledge_id is invalid")
    command = _framework_command(paths, "read-source", id=knowledge_id)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False,
                                env=os.environ | {"OPL_PROFILE_WORKSPACE": str(paths.workspace)})
        if result.returncode:
            raise ValueError("Framework knowledge source is not available for this caller")
        envelope = json.loads(result.stdout)
        source = envelope.get("knowledge_source") if isinstance(envelope, dict) else None
        if (not isinstance(envelope, dict) or envelope.get("version") != "g2" or not isinstance(source, dict)
                or source.get("knowledge_id") != knowledge_id or not isinstance(source.get("content"), str)
                or not isinstance(source.get("source_ref"), str) or not source["source_ref"]):
            raise ValueError("Framework returned an invalid knowledge source identity")
        body = source["content"].encode("utf-8")
        if not 0 < len(body) <= 256 * 1024 or source.get("sha256") != "sha256:" + hashlib.sha256(body).hexdigest():
            raise ValueError("Framework knowledge source content differs from its revision")
        return {key: source[key] for key in ("knowledge_id", "sha256", "content", "source_ref")}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"knowledge source {knowledge_id} requires current Framework readback") from exc


def source_dependencies(value: object) -> list[dict[str, str]]:
    if not isinstance(value, dict) or not value:
        raise ValueError("source_versions must map accepted knowledge identities to revisions")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for identifier, revision in value.items():
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9._-]*", identifier):
            raise ValueError("source_versions knowledge_id is invalid")
        if not isinstance(revision, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", revision):
            raise ValueError("source_versions sha256 is invalid")
        if identifier in seen:
            raise ValueError("source_dependencies knowledge identities must be unique")
        seen.add(identifier)
        result.append({"knowledge_id": identifier, "sha256": revision})
    return result


def verify_knowledge_dependencies(value: object, paths: PersonaPaths) -> dict[str, Any]:
    """Return a fresh body-free verdict from the selected Profile's bindings."""
    try:
        dependencies = source_dependencies(value)
    except ValueError:
        return {"valid": False, "issues": ["source_dependencies_missing_or_invalid"]}
    try:
        with tempfile.TemporaryDirectory(prefix="persona-knowledge-") as temporary:
            request_path = Path(temporary) / "dependencies.json"
            with request_path.open("x", encoding="utf-8") as handle:
                os.chmod(request_path, 0o600)
                json.dump(dependencies, handle)
            command = _framework_command(paths, "verify-dependencies", dependencies=str(request_path))
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False,
                                    env=os.environ | {"OPL_PROFILE_WORKSPACE": str(paths.workspace)})
        if result.returncode:
            raise ValueError("Framework dependency verification failed")
        envelope = json.loads(result.stdout)
        verdict = envelope.get("knowledge_dependencies") if isinstance(envelope, dict) else None
        if (not isinstance(envelope, dict) or envelope.get("version") != "g2"
                or not isinstance(verdict, dict) or type(verdict.get("valid")) is not bool
                or not isinstance(verdict.get("issues"), list)
                or not all(isinstance(issue, str) for issue in verdict["issues"])
                or (verdict["valid"] and verdict["issues"])):
            raise ValueError("Framework returned an invalid dependency verdict")
        return {"valid": verdict["valid"], "issues": verdict["issues"]}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"valid": False, "issues": ["framework_knowledge_verification_unavailable"]}
