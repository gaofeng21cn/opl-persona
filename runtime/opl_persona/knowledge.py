"""Consume authorized workspace knowledge reads and validation via OPL v2 bindings & opl_client."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4

from opl_client import OplClientError, connect

from .paths import PersonaPaths


KNOWLEDGE_DOMAIN = "persona"
MAX_SOURCE_BYTES = 256 * 1024
_KNOWLEDGE_ID_RE = re.compile(r"[a-z][a-z0-9._-]*")
_SHA256_RE = re.compile(r"sha256:[a-f0-9]{64}")


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _bindings_path(paths: PersonaPaths) -> Path:
    return paths.workspace / "shared/memory/knowledge-bindings.json"


def _load_bindings(paths: PersonaPaths) -> list[dict[str, Any]]:
    bpath = _bindings_path(paths)
    if not bpath.is_file():
        raise FileNotFoundError("knowledge_bindings_unavailable")
    payload = json.loads(bpath.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("registries"), list):
        raise ValueError("invalid knowledge-bindings.json")
    return [r for r in payload["registries"] if isinstance(r, dict)]


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _resolve_registry_ref(paths: PersonaPaths, ref: str) -> Path:
    candidate = Path(ref)
    if not candidate.is_absolute():
        candidate = paths.workspace / candidate
    return candidate.resolve(strict=True)


def _find_source_grant(
    source: dict[str, Any],
    paths: PersonaPaths,
    scope_id: str | None,
    *,
    require_write: bool = False,
) -> bool:
    ws_resolved = paths.workspace.resolve(strict=False)
    for grant in source.get("grants", []):
        if not isinstance(grant, dict):
            continue
        grant_ws = grant.get("workspace_root")
        if not isinstance(grant_ws, str) or Path(grant_ws).resolve(strict=False) != ws_resolved:
            continue
        domains = grant.get("write_domains" if require_write else "domains", [])
        if not isinstance(domains, list) or KNOWLEDGE_DOMAIN not in domains:
            continue
        scope_ids = grant.get("scope_ids")
        if scope_id and isinstance(scope_ids, list) and scope_id not in scope_ids:
            continue
        return True
    return False


def _resolve_body_path(source: dict[str, Any], body_ref: dict[str, Any]) -> Path:
    root_raw = source.get("root")
    ref_raw = body_ref.get("ref")
    if not isinstance(root_raw, str) or not isinstance(ref_raw, str) or not ref_raw:
        raise ValueError("invalid source body_ref")
    root = Path(root_raw).resolve(strict=True)
    target = (root / ref_raw).resolve(strict=True)
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("body_ref escapes source root or is missing")
    return target


def _lookup_item(
    knowledge_id: str,
    paths: PersonaPaths,
    *,
    require_write: bool = False,
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], Path, str]:
    now_dt = datetime.now(timezone.utc)
    for reg_entry in _load_bindings(paths):
        reg_ref = reg_entry.get("registry_ref")
        if not isinstance(reg_ref, str) or not reg_ref:
            continue
        reg_path = _resolve_registry_ref(paths, reg_ref)
        registry = json.loads(reg_path.read_text(encoding="utf-8"))
        if not isinstance(registry, dict):
            continue
        sources = {s.get("source_id"): s for s in registry.get("sources", []) if isinstance(s, dict)}
        for item in registry.get("items", []):
            if not isinstance(item, dict) or item.get("knowledge_id") != knowledge_id:
                continue
            if item.get("status") != "active":
                raise ValueError(f"source_revoked:{knowledge_id}")
            app = item.get("applicability", {})
            if isinstance(app, dict) and app.get("domains") and KNOWLEDGE_DOMAIN not in app["domains"]:
                raise ValueError(f"source_unauthorized:{knowledge_id}")
            next_review = item.get("next_review_at")
            if isinstance(next_review, str) and next_review:
                if _parse_iso(next_review) < now_dt:
                    raise ValueError(f"source_expired:{knowledge_id}")
            body_ref = item.get("body_ref")
            if not isinstance(body_ref, dict):
                raise ValueError(f"source_missing:{knowledge_id}")
            source_id = body_ref.get("source_id")
            source = sources.get(source_id)
            if not source:
                raise ValueError(f"source_missing:{knowledge_id}")
            if source.get("status") != "active":
                raise ValueError(f"source_revoked:{knowledge_id}")
            allowed_sources = reg_entry.get("source_ids")
            if isinstance(allowed_sources, list) and source_id not in allowed_sources:
                raise ValueError(f"source_unauthorized:{knowledge_id}")
            scope = item.get("scope", {})
            scope_id = scope.get("id") if isinstance(scope, dict) else None
            allowed_scopes = reg_entry.get("scope_ids")
            if scope_id and isinstance(allowed_scopes, list) and scope_id not in allowed_scopes:
                raise ValueError(f"source_unauthorized:{knowledge_id}")
            if not _find_source_grant(source, paths, scope_id, require_write=require_write):
                raise ValueError(f"source_unauthorized:{knowledge_id}")
            if require_write and source.get("writable") is not True:
                raise ValueError(f"source_readonly:{knowledge_id}")
            body_path = _resolve_body_path(source, body_ref)
            body_bytes = body_path.read_bytes()
            actual_sha = _sha256_bytes(body_bytes)
            if actual_sha != body_ref.get("sha256"):
                raise ValueError(f"source_drifted:{knowledge_id}")
            return reg_path, registry, item, source, body_path, actual_sha
    raise ValueError(f"source_missing:{knowledge_id}")


def _notify_daemon_writeback(paths: PersonaPaths, method: str, params: dict[str, Any]) -> None:
    """Best-effort notification to active opld workspace if registered; never breaks standalone mode."""
    try:
        with connect() as client:
            listed = client.workspace_list()
            ws_resolved = str(paths.workspace.resolve(strict=False))
            workspaces = listed.get("workspaces", []) if isinstance(listed, dict) else []
            match = next(
                (
                    w for w in workspaces
                    if isinstance(w, dict) and str(Path(str(w.get("root_path", ""))).resolve(strict=False)) == ws_resolved
                ),
                None,
            )
            if match and isinstance(match.get("workspace_id"), str):
                client.call(method, {"workspace_id": match["workspace_id"], **params})
    except (OSError, ValueError, OplClientError):
        return


def resolve_knowledge_target(target: Path, paths: PersonaPaths) -> dict[str, Any]:
    """Identify registered bodies before allowing the ordinary document adapter."""
    if not _bindings_path(paths).exists():
        return {"registered": False}
    resolved_target = target.resolve(strict=False)
    try:
        for reg_entry in _load_bindings(paths):
            reg_ref = reg_entry.get("registry_ref")
            if not isinstance(reg_ref, str) or not reg_ref:
                continue
            reg_path = _resolve_registry_ref(paths, reg_ref)
            registry = json.loads(reg_path.read_text(encoding="utf-8"))
            sources = {s.get("source_id"): s for s in registry.get("sources", []) if isinstance(s, dict)}
            for item in registry.get("items", []):
                if not isinstance(item, dict):
                    continue
                body_ref = item.get("body_ref")
                if not isinstance(body_ref, dict):
                    continue
                source = sources.get(body_ref.get("source_id"))
                if not source or not isinstance(source.get("root"), str) or not isinstance(body_ref.get("ref"), str):
                    continue
                candidate = (Path(source["root"]).resolve(strict=False) / body_ref["ref"]).resolve(strict=False)
                if candidate == resolved_target:
                    scope = item.get("scope", {})
                    scope_id = scope.get("id") if isinstance(scope, dict) else None
                    authorized = (
                        item.get("status") == "active"
                        and source.get("status") == "active"
                        and _find_source_grant(source, paths, scope_id, require_write=False)
                    )
                    return {
                        "registered": True,
                        "knowledge_id": item.get("knowledge_id"),
                        "authorized": authorized,
                    }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid knowledge registry target") from exc
    return {"registered": False}


def _proposals_dir(paths: PersonaPaths) -> Path:
    return paths.workspace / "shared/memory/.knowledge-proposals"


def propose_knowledge_writeback(
    knowledge_id: str,
    paths: PersonaPaths,
    replacement: bytes,
    *,
    source_refs: list[str],
    target_scope: dict[str, str] | None = None,
    content_kind: str = "policy",
    proposed_rule_or_mechanism: str = "",
    evidence_class: str = "persona-derived",
    review_requirement: str = "owner review required",
) -> dict[str, Any]:
    if not source_refs or not replacement:
        raise ValueError("knowledge writeback requires source_refs and a non-empty replacement")
    reg_path, _registry, item, _source, body_path, current_sha = _lookup_item(
        knowledge_id, paths, require_write=True
    )
    proposal_id = f"kwb-{uuid4().hex[:12]}"
    proposal_record = {
        "proposal_id": proposal_id,
        "knowledge_id": knowledge_id,
        "registry_path": str(reg_path),
        "body_path": str(body_path),
        "expected_sha256": current_sha,
        "replacement_utf8": replacement.decode("utf-8"),
        "replacement_sha256": _sha256_bytes(replacement),
        "source_refs": source_refs,
        "target_scope": target_scope or item.get("scope") or {"kind": "topic", "id": knowledge_id},
        "content_kind": content_kind,
        "proposed_rule_or_mechanism": proposed_rule_or_mechanism or f"Persona update for {knowledge_id}",
        "evidence_class": evidence_class,
        "review_requirement": review_requirement,
        "status": "proposed",
        "review": None,
    }
    _atomic_write_json(_proposals_dir(paths) / f"{proposal_id}.json", proposal_record)
    _notify_daemon_writeback(
        paths,
        "workspace.writeback.propose",
        {"knowledge_id": knowledge_id, "proposal_id": proposal_id},
    )
    return {
        "proposal_id": proposal_id,
        "knowledge_id": knowledge_id,
        "status": "proposed",
        "expected_sha256": current_sha,
    }


def review_knowledge_writeback(
    paths: PersonaPaths,
    proposal_id: str,
    *,
    approval_ref: str,
    reviewer: str,
    reviewed_at: str,
    next_review_at: str,
    decision: str = "accepted",
) -> dict[str, Any]:
    if decision not in {"accepted", "rejected"}:
        raise ValueError("unsupported knowledge review decision")
    proposal_path = _proposals_dir(paths) / f"{proposal_id}.json"
    if not proposal_path.is_file():
        raise ValueError(f"unknown knowledge proposal: {proposal_id}")
    record = json.loads(proposal_path.read_text(encoding="utf-8"))
    record["status"] = decision
    record["review"] = {
        "decision": decision,
        "approval_ref": approval_ref,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "next_review_at": next_review_at,
    }
    _atomic_write_json(proposal_path, record)
    return {"proposal_id": proposal_id, **record["review"]}


def apply_knowledge_writeback(paths: PersonaPaths, proposal_id: str) -> dict[str, Any]:
    proposal_path = _proposals_dir(paths) / f"{proposal_id}.json"
    if not proposal_path.is_file():
        raise ValueError(f"unknown knowledge proposal: {proposal_id}")
    record = json.loads(proposal_path.read_text(encoding="utf-8"))
    review = record.get("review")
    if record.get("status") != "accepted" or not isinstance(review, dict):
        raise ValueError("knowledge writeback must be accepted before apply")
    knowledge_id = record["knowledge_id"]
    reg_path, registry, item, _source, body_path, current_sha = _lookup_item(
        knowledge_id, paths, require_write=True
    )
    if current_sha != record["expected_sha256"]:
        raise ValueError("knowledge source changed before writeback apply")
    replacement_bytes = record["replacement_utf8"].encode("utf-8")
    new_sha = _sha256_bytes(replacement_bytes)
    _atomic_write_bytes(body_path, replacement_bytes)
    item["body_ref"]["sha256"] = new_sha
    item["reviewed_at"] = review["reviewed_at"]
    item["next_review_at"] = review["next_review_at"]
    _atomic_write_json(reg_path, registry)
    record["status"] = "applied"
    _atomic_write_json(proposal_path, record)
    _notify_daemon_writeback(
        paths,
        "workspace.writeback.commit",
        {"knowledge_id": knowledge_id, "proposal_id": proposal_id, "sha256": new_sha},
    )
    return {
        "status": "applied",
        "proposal_id": proposal_id,
        "knowledge_id": knowledge_id,
        "sha256": new_sha,
    }


def register_knowledge_source(
    paths: PersonaPaths,
    registration: dict[str, Any],
    *,
    expected_sha256: str,
    approval_ref: str,
    review: dict[str, str],
    expected_body_path: Path,
) -> dict[str, Any]:
    body_bytes = expected_body_path.read_bytes()
    actual_sha = _sha256_bytes(body_bytes)
    if actual_sha != expected_sha256:
        raise ValueError("registered body digest differs from expected_sha256")
    reg_ref = registration.get("registry_ref")
    if not isinstance(reg_ref, str) or not reg_ref:
        raise ValueError("registration missing registry_ref")
    reg_path = _resolve_registry_ref(paths, reg_ref)
    registry = json.loads(reg_path.read_text(encoding="utf-8"))
    item = dict(registration["item"])
    item["body_ref"] = {**dict(item.get("body_ref", {})), "sha256": actual_sha}
    item["reviewed_at"] = review["reviewed_at"]
    item["next_review_at"] = review["next_review_at"]
    item["status"] = "active"
    item["approval_ref"] = approval_ref
    items = [entry for entry in registry.get("items", []) if entry.get("knowledge_id") != item.get("knowledge_id")]
    items.append(item)
    registry["items"] = items
    _atomic_write_json(reg_path, registry)
    return {"status": "registered", "knowledge_id": item.get("knowledge_id"), "sha256": actual_sha}


def read_knowledge_source(knowledge_id: str, paths: PersonaPaths) -> dict[str, str]:
    """Read one accepted private source through authorized workspace bindings."""
    if not isinstance(knowledge_id, str) or not _KNOWLEDGE_ID_RE.fullmatch(knowledge_id):
        raise ValueError("knowledge_id is invalid")
    try:
        _reg_path, _registry, item, _source, body_path, actual_sha = _lookup_item(knowledge_id, paths)
        body = body_path.read_bytes()
        if not 0 < len(body) <= MAX_SOURCE_BYTES:
            raise ValueError("knowledge source size out of bounds")
        content = body.decode("utf-8")
        source_ref = item["body_ref"].get("ref")
        if not isinstance(source_ref, str) or not source_ref:
            raise ValueError("invalid source_ref")
        return {
            "knowledge_id": knowledge_id,
            "sha256": actual_sha,
            "content": content,
            "source_ref": source_ref,
        }
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"knowledge source {knowledge_id} requires current Framework readback") from exc


def source_dependencies(value: object) -> list[dict[str, str]]:
    if not isinstance(value, dict) or not value:
        raise ValueError("source_versions must map accepted knowledge identities to revisions")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for identifier, revision in value.items():
        if not isinstance(identifier, str) or not _KNOWLEDGE_ID_RE.fullmatch(identifier):
            raise ValueError("source_versions knowledge_id is invalid")
        if not isinstance(revision, str) or not _SHA256_RE.fullmatch(revision):
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
        _load_bindings(paths)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"valid": False, "issues": ["framework_knowledge_verification_unavailable"]}

    issues: list[str] = []
    for dep in dependencies:
        kid = dep["knowledge_id"]
        expected_sha = dep["sha256"]
        try:
            _reg_path, _registry, _item, _source, _body_path, actual_sha = _lookup_item(kid, paths)
            if actual_sha != expected_sha:
                issues.append(f"source_drifted:{kid}")
        except ValueError as exc:
            issues.append(str(exc))
        except (OSError, json.JSONDecodeError):
            issues.append(f"framework_knowledge_verification_unavailable:{kid}")
    return {"valid": not issues, "issues": issues}
