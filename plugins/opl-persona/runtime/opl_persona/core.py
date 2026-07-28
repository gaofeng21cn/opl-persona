from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Mapping

SCHEMA_VERSION = "opl-persona-proposal.v1"
EMAIL_STORE_REF_PREFIX = "email-store://"
OBSIDIAN_NOTE_CONTRACT = "knowledge.obsidian.note.v1"


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


def _string_list(
    payload: Mapping[str, Any],
    name: str,
    *,
    required: bool = False,
) -> list[str]:
    raw = payload.get(name, [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"{name} must be a list of strings")
    values = list(dict.fromkeys(item.strip() for item in raw if item.strip()))
    if required and not values:
        raise ValueError(f"at least one {name} entry is required")
    return values


def _email_store_source_refs(payload: Mapping[str, Any]) -> list[str]:
    refs = _source_refs(payload)
    if not all(ref.startswith(EMAIL_STORE_REF_PREFIX) for ref in refs):
        raise ValueError("mail triage source_refs must use stable email-store:// identities")
    return refs


def _policy_provenance(payload: Mapping[str, Any]) -> tuple[list[str], str]:
    policy_refs = _string_list(payload, "policy_refs", required=True)
    policy_digest = _required(payload, "policy_digest")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", policy_digest):
        raise ValueError("policy_digest must be a sha256 digest")
    return policy_refs, policy_digest


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
        "schema_version": SCHEMA_VERSION,
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


def _inbox_capture(
    *,
    capture_id: str,
    item_kind: str,
    title: str,
    summary: str,
    source_refs: list[str],
) -> dict[str, Any]:
    return _proposal(
        kind="personal.inbox.v1.capture",
        input_id=capture_id,
        target="personal.inbox.v1",
        operation="capture",
        payload={
            "capture_id": capture_id,
            "item_kind": item_kind,
            "title": title,
            "summary": summary,
            "source_refs": source_refs,
        },
        source_refs=source_refs,
    )


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


def build_inbox_capture_proposals(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Capture one evidenced item for the generic personal inbox contract."""
    capture_id = _required(payload, "capture_id")
    title = _required(payload, "title")
    summary = _required(payload, "summary")
    source_refs = _source_refs(payload)
    item_kind = str(payload.get("item_kind") or "note").strip() or "note"
    return _bundle(
        "personal_inbox_capture",
        capture_id,
        source_refs,
        [
            _inbox_capture(
                capture_id=capture_id,
                item_kind=item_kind,
                title=title,
                summary=summary,
                source_refs=source_refs,
            )
        ],
    )


def build_mail_triage_proposals(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Create inbox-capture and policy-bound mail-triage proposals.

    Persona classifies supplied evidence only. Relay remains the authority for
    the email identity, mailbox state, draft lifecycle, and any later action.
    """
    email_ref = _required(payload, "email_ref")
    if not email_ref.startswith(EMAIL_STORE_REF_PREFIX):
        raise ValueError("email_ref must use a stable email-store:// identity")
    source_refs = _email_store_source_refs(payload)
    if email_ref not in source_refs:
        raise ValueError("email_ref must also be present in source_refs")
    policy_refs, policy_digest = _policy_provenance(payload)
    subject = _required(payload, "subject")
    summary = _required(payload, "summary")
    triage_payload = {
        "email_ref": email_ref,
        "classification": _required(payload, "classification"),
        "priority": _required(payload, "priority"),
        "rationale": _required(payload, "rationale"),
        "uncertainty": _required(payload, "uncertainty"),
        "recommended_action": _required(payload, "recommended_action"),
    }
    triage = _proposal(
        kind="mail.triage",
        input_id=email_ref,
        target="communications.mail.v1#triage",
        operation="classify",
        payload=triage_payload,
        source_refs=source_refs,
    )
    triage.update(
        {
            "policy_refs": policy_refs,
            "policy_digest": policy_digest,
            "decision_scope": "proposal_only",
        }
    )
    return _bundle(
        "mail",
        email_ref,
        source_refs,
        [
            _inbox_capture(
                capture_id=email_ref,
                item_kind="mail",
                title=subject,
                summary=summary,
                source_refs=source_refs,
            ),
            triage,
        ],
    )


def _obsidian_target_path(payload: Mapping[str, Any]) -> str:
    target_path = _required(payload, "target_path")
    path = PurePosixPath(target_path)
    if (
        path.is_absolute()
        or path.suffix.casefold() != ".md"
        or any(part in {"", ".", "..", ".obsidian"} for part in path.parts)
        or target_path != path.as_posix()
    ):
        raise ValueError("target_path must be a safe, precise relative Markdown path")
    return target_path


def _expected_digest(payload: Mapping[str, Any], operation: str) -> str:
    expected_digest = _required(payload, "expected_digest")
    if operation == "create" and expected_digest == "absent":
        return expected_digest
    if operation == "update" and re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest):
        return expected_digest
    raise ValueError("expected_digest must be absent for create or a sha256 digest for update")


def build_obsidian_note_proposals(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Create a proposal for an owner adapter to create or update one note.

    The proposal has a target precondition but does not read or write a vault.
    The Obsidian adapter must re-check ``expected_digest`` before any user-
    approved external mutation.
    """
    operation = _required(payload, "operation")
    if operation not in {"create", "update"}:
        raise ValueError("operation must be create or update")
    target_path = _obsidian_target_path(payload)
    expected_digest = _expected_digest(payload, operation)
    evidence_refs = _string_list(payload, "evidence_refs", required=True)
    frontmatter = payload.get("frontmatter", {})
    if not isinstance(frontmatter, Mapping):
        raise ValueError("frontmatter must be an object")
    body = _required(payload, "body")
    links = _string_list(payload, "links")
    tags = _string_list(payload, "tags")
    note_payload = {
        "target_path": target_path,
        "frontmatter": dict(frontmatter),
        "body": body,
        "links": links,
        "tags": tags,
        "evidence_refs": evidence_refs,
        "expected_digest": expected_digest,
    }
    proposal = _proposal(
        kind=OBSIDIAN_NOTE_CONTRACT,
        input_id=target_path,
        target=OBSIDIAN_NOTE_CONTRACT,
        operation=operation,
        payload=note_payload,
        source_refs=evidence_refs,
    )
    proposal.update(
        {
            "target_path": target_path,
            "expected_digest": expected_digest,
            "allowed_outputs": ["reviewable_proposal"],
            "forbidden_outputs": [
                "knowledge.obsidian.note.v1.apply",
                "filesystem.write",
                "communications.mail.v1#draft.create",
                "gflab_web.content.apply",
            ],
        }
    )
    return _bundle(
        "obsidian_note",
        target_path,
        evidence_refs,
        [proposal],
    )


def dump_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
