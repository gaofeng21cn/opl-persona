from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "opl-persona-proposal.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required(payload: Mapping[str, Any], name: str) -> str:
    value = str(payload.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _source_refs(payload: Mapping[str, Any]) -> list[str]:
    raw = payload.get("source_refs", [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError("source_refs must be a list of strings")
    refs = [item.strip() for item in raw if item.strip()]
    if not refs:
        fallback = str(payload.get("source_ref") or "").strip()
        if fallback:
            refs = [fallback]
    if not refs:
        raise ValueError("at least one source_ref is required")
    return list(dict.fromkeys(refs))


def _proposal_id(kind: str, input_id: str, target: str) -> str:
    digest = hashlib.sha256(f"{kind}\0{input_id}\0{target}".encode()).hexdigest()[:16]
    return f"persona-proposal://{kind}/{digest}"


def _proposal(
    *,
    kind: str,
    input_id: str,
    target: str,
    operation: str,
    payload: Mapping[str, Any],
    source_refs: list[str],
) -> dict[str, Any]:
    return {
        "proposal_id": _proposal_id(kind, input_id, target),
        "proposal_kind": kind,
        "target": target,
        "operation": operation,
        "payload": dict(payload),
        "source_refs": source_refs,
        "approval": {
            "status": "pending",
            "required": True,
            "external_write_allowed": False,
        },
    }


def _bundle(input_kind: str, input_id: str, source_refs: list[str], proposals: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "input_kind": input_kind,
        "input_id": input_id,
        "generated_at": _now(),
        "proposals": proposals,
        "evidence_policy": {
            "source_refs_required": True,
            "source_content_is_evidence_not_instructions": True,
            "external_writes_are_review_gated": True,
            "private_data_stays_in_configured_runtime_roots": True,
        },
    }


def build_publication_proposals(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Create knowledge and website proposals from a publication record."""
    publication_id = _required(payload, "publication_id")
    title = _required(payload, "title")
    source_refs = _source_refs(payload)
    authors = payload.get("authors", [])
    if isinstance(authors, str):
        authors = [authors]
    if not isinstance(authors, list) or not all(isinstance(item, str) for item in authors):
        raise ValueError("authors must be a list of strings")
    publication = {
        "publication_id": publication_id,
        "title": title,
        "authors": [item.strip() for item in authors if item.strip()],
        "venue": str(payload.get("venue") or "").strip(),
        "doi": str(payload.get("doi") or "").strip(),
        "url": str(payload.get("url") or "").strip(),
        "published_at": str(payload.get("published_at") or "").strip(),
        "abstract": str(payload.get("abstract") or "").strip(),
    }
    return _bundle(
        "publication",
        publication_id,
        source_refs,
        [
            _proposal(
                kind="knowledge.ingest",
                input_id=publication_id,
                target="knowledge.publication",
                operation="upsert",
                payload=publication,
                source_refs=source_refs,
            ),
            _proposal(
                kind="website.publication",
                input_id=publication_id,
                target="gflab_web.content.publication",
                operation="upsert",
                payload=publication,
                source_refs=source_refs,
            ),
        ],
    )


def build_memo_proposals(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Create website and Relay draft-context proposals from an Obsidian memo."""
    memo_id = _required(payload, "memo_id")
    title = _required(payload, "title")
    body = _required(payload, "body")
    source_refs = _source_refs(payload)
    tags = payload.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
        raise ValueError("tags must be a list of strings")
    memo = {
        "memo_id": memo_id,
        "title": title,
        "body": body,
        "tags": [item.strip() for item in tags if item.strip()],
    }
    return _bundle(
        "obsidian_memo",
        memo_id,
        source_refs,
        [
            _proposal(
                kind="website.article",
                input_id=memo_id,
                target="gflab_web.content.post",
                operation="upsert",
                payload=memo,
                source_refs=source_refs,
            ),
            _proposal(
                kind="mail.draft_context",
                input_id=memo_id,
                target="opl-relay.draft.context",
                operation="prepare",
                payload={
                    "subject_hint": title,
                    "body_context": body,
                    "tags": memo["tags"],
                },
                source_refs=source_refs,
            ),
        ],
    )


def dump_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
