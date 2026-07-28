from __future__ import annotations

import hashlib
import json
import re
from email.utils import getaddresses, parseaddr
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping
from urllib.parse import urlsplit

from .paths import PersonaPaths
from .policy import PolicySnapshot, load_markdown_policies

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
    for ref in refs:
        parsed = urlsplit(ref)
        if (
            parsed.scheme != "email-store"
            or not parsed.netloc
            or len([part for part in parsed.path.split("/") if part]) < 2
            or parsed.query
            or parsed.fragment
            or any(char.isspace() for char in ref)
        ):
            raise ValueError("mail triage source_refs must use stable email-store:// identities")
    return refs


def _policy_provenance(
    payload: Mapping[str, Any],
) -> tuple[list[str], str, PolicySnapshot | None, str | None]:
    policy_refs = _string_list(payload, "policy_refs")
    digest_kind = str(payload.get("policy_digest_kind") or "").strip()
    if digest_kind and digest_kind not in {"content", "refs_set"}:
        raise ValueError("policy_digest_kind must be content or refs_set")
    policy_digest = str(
        payload.get("persona_policy_digest") or payload.get("policy_digest") or ""
    ).strip()
    relay_policy_digest = str(payload.get("relay_policy_digest") or "").strip() or None
    if digest_kind == "refs_set" and relay_policy_digest is None:
        relay_policy_digest = policy_digest or None
        policy_digest = str(payload.get("persona_policy_digest") or "").strip()
    if relay_policy_digest and not re.fullmatch(r"sha256:[0-9a-f]{64}", relay_policy_digest):
        raise ValueError("relay_policy_digest must be a sha256 digest")
    explicit_workspace = str(payload.get("policy_workspace") or "").strip()
    explicit_paths = payload.get("policy_paths") or payload.get("policy_files")
    should_load = bool(explicit_workspace or explicit_paths)
    if relay_policy_digest and not should_load:
        workspace = PersonaPaths.resolve().workspace
        should_load = (workspace / "policies").is_dir()
        if not should_load:
            raise ValueError("Persona Markdown policy workspace is required for mail triage")
    if not policy_digest and not should_load:
        workspace = PersonaPaths.resolve().workspace
        should_load = (workspace / "policies").is_dir()
    if should_load:
        if explicit_paths is not None and not isinstance(explicit_paths, (list, tuple)):
            raise ValueError("policy_paths must be a list of strings")
        workspace = Path(explicit_workspace).expanduser() if explicit_workspace else None
        snapshot = load_markdown_policies(
            workspace=workspace,
            refs=policy_refs or None,
            paths=explicit_paths,
        )
        if policy_digest and policy_digest != snapshot.digest:
            raise ValueError("policy_digest does not match the selected Markdown policy content")
        return list(policy_refs or snapshot.refs), snapshot.digest, snapshot, relay_policy_digest
    if not policy_refs:
        raise ValueError("policy_refs is required when no Markdown policy workspace is configured")
    if not policy_digest:
        raise ValueError("policy_digest is required")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", policy_digest):
        raise ValueError("policy_digest must be a sha256 digest")
    return policy_refs, policy_digest, None, relay_policy_digest


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


def _addresses(value: object) -> list[dict[str, str]]:
    """Normalize To/Cc/Bcc values without guessing missing addresses."""

    if value is None:
        return []
    values = value if isinstance(value, (list, tuple)) else [value]
    records: list[dict[str, str]] = []
    for item in values:
        if isinstance(item, Mapping):
            address = str(item.get("email") or item.get("address") or "").strip()
            name = str(item.get("name") or "").strip()
        elif (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and all(isinstance(part, str) for part in item)
        ):
            name, address = (part.strip() for part in item)
        elif isinstance(item, str):
            name, address = parseaddr(item.strip())
            address = address.strip()
            name = name.strip()
            if not address and item.strip():
                address = item.strip()
        else:
            continue
        if not address:
            continue
        record = {"email": address.casefold()}
        if name:
            record["name"] = name
        records.append(record)
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        key = record["email"]
        if key not in seen:
            seen.add(key)
            unique.append(record)
    return unique


def _address_strings(value: object) -> list[dict[str, str]]:
    """Parse comma-separated RFC 5322 recipient headers and list values."""

    if isinstance(value, str) and "," in value:
        return _addresses(getaddresses([value]))
    if isinstance(value, (list, tuple)) and any(isinstance(item, str) and "," in item for item in value):
        return _addresses(getaddresses([str(item) for item in value]))
    return _addresses(value)


def _first_author(payload: Mapping[str, Any]) -> dict[str, str] | None:
    value = (
        payload.get("actual_first_author")
        or payload.get("article_first_author")
        or payload.get("first_author")
    )
    normalized = _addresses(value)
    if normalized:
        return normalized[0]
    if isinstance(value, str) and value.strip():
        return {"name": value.strip()}
    return None


def _team_members(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    value = payload.get("team_members") or payload.get("lab_members") or []
    return _addresses(value)


def _recipient_analysis(payload: Mapping[str, Any]) -> dict[str, Any]:
    to = _address_strings(payload.get("to"))
    cc = _address_strings(payload.get("cc"))
    bcc = _address_strings(payload.get("bcc"))
    recipients = [*to, *cc, *bcc]
    recipient_emails = {item["email"] for item in recipients}
    self_addresses = _address_strings(
        payload.get("user_addresses")
        or payload.get("my_addresses")
        or payload.get("user_email")
    )
    self_emails = {item["email"] for item in self_addresses}
    first_author = _first_author(payload)
    team_members = _team_members(payload)
    team_by_email = {item["email"]: item for item in team_members}
    first_author_email = first_author.get("email") if first_author else None
    matched_team_member = team_by_email.get(first_author_email or "")
    if matched_team_member is None and first_author and first_author.get("name"):
        author_name = first_author["name"].casefold()
        matched_team_member = next(
            (
                item
                for item in team_members
                if item.get("name", "").casefold() == author_name
            ),
            None,
        )
    unique_recipient = bool(
        self_emails
        and len(recipient_emails) == 1
        and bool(recipient_emails & self_emails)
    )
    sent_to_first_author = bool(first_author_email and first_author_email in recipient_emails)
    forwarded = matched_team_member if unique_recipient and matched_team_member else None
    current_follow_up = (
        payload.get("current_follow_up")
        or payload.get("followed_up_by")
        or payload.get("follow_up_by")
    )
    follow_up = _addresses(current_follow_up)
    if not follow_up and sent_to_first_author and first_author:
        follow_up = [first_author]
    follow_up_person = follow_up[0] if follow_up else None
    notification: dict[str, Any] = {
        "required": bool(sent_to_first_author and matched_team_member),
        "recipient": "user" if sent_to_first_author and matched_team_member else None,
        "reason": (
            "actual first author is already a recipient; report who is following up"
            if sent_to_first_author and matched_team_member
            else None
        ),
    }
    return {
        "to": to,
        "cc": cc,
        "bcc": bcc,
        "recipient_identity_known": bool(self_emails),
        "is_unique_recipient": unique_recipient,
        "actual_first_author": first_author,
        "team_member_match": {
            "matched": bool(matched_team_member),
            "member": matched_team_member,
        },
        "forward_to": forwarded,
        "follow_up_by": follow_up_person,
        "notification": notification,
    }


def _policy_classification(
    payload: Mapping[str, Any],
    *,
    routing: Mapping[str, Any],
    policy: PolicySnapshot | None,
) -> dict[str, str]:
    """Derive conservative defaults from evidence and private Markdown text."""

    text = " ".join(
        str(payload.get(key) or "")
        for key in ("subject", "summary", "snippet", "body", "from", "sender")
    ).casefold()
    policy_text = policy.text.casefold() if policy else ""
    advertising = any(
        token in text
        for token in (
            "unsubscribe",
            "newsletter",
            "promotion",
            "promotional",
            "marketing",
            "webinar",
            "conference registration",
            "special issue invitation",
            "广告",
            "推广",
            "营销",
        )
    ) and not any(token in text for token in ("manuscript", "submission", "revision", "proof"))
    manuscript = any(
        token in text
        for token in (
            "manuscript",
            "submission",
            "editorial",
            "reviewer",
            "revision",
            "proof",
            "投稿",
            "论文",
            "杂志社",
            "编辑",
        )
    )
    if routing.get("forward_to"):
        return {
            "classification": "needs_user_reply",
            "priority": "highest" if manuscript else "high",
            "rationale": "唯一收件人是本人，实际第一作者为已匹配的团队成员，建议转发并由其跟进。",
            "recommended_action": "forward_to_first_author",
        }
    if routing.get("notification", {}).get("required"):
        return {
            "classification": "remind",
            "priority": "highest" if manuscript else "high",
            "rationale": "邮件已发给实际第一作者，需通知本人并注明当前跟进人。",
            "recommended_action": "notify_user_with_follow_up",
        }
    if advertising:
        return {
            "classification": "archive_candidate",
            "priority": "low",
            "rationale": "符合私有规则中的高置信广告或营销信号。",
            "recommended_action": "delete",
        }
    if manuscript:
        return {
            "classification": "needs_user_reply",
            "priority": "high",
            "rationale": "投稿、论文或编辑事务属于第一优先级，需要保留人工判断。",
            "recommended_action": "review_and_decide",
        }
    if "mailbox-triage" in policy_text or "triage" in policy_text:
        return {
            "classification": "fyi",
            "priority": "normal",
            "rationale": "未命中更高优先级规则，保留为低风险知会。",
            "recommended_action": "observe",
        }
    return {
        "classification": "needs_more_context",
        "priority": "normal",
        "rationale": "现有邮件证据不足以应用明确的私有规则。",
        "recommended_action": "read_with_more_context",
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
    policy_refs, policy_digest, policy_snapshot, relay_policy_digest = _policy_provenance(payload)
    subject = _required(payload, "subject")
    summary = _required(payload, "summary")
    routing = _recipient_analysis(payload)
    derived = _policy_classification(payload, routing=routing, policy=policy_snapshot)
    classification = str(payload.get("classification") or derived["classification"]).strip()
    priority = str(payload.get("priority") or derived["priority"]).strip()
    rationale = str(payload.get("rationale") or derived["rationale"]).strip()
    default_uncertainty = "未发现额外不确定性。"
    if not routing["recipient_identity_known"] and (
        routing["to"] or routing["cc"] or routing["bcc"]
    ):
        default_uncertainty = "缺少用户自身邮箱 identity，无法确认是否为唯一收件人。"
    elif routing.get("actual_first_author") and not routing["team_member_match"]["matched"]:
        default_uncertainty = "实际第一作者或团队成员匹配信息不完整。"
    uncertainty = str(payload.get("uncertainty") or default_uncertainty).strip()
    recommended_action = str(
        payload.get("recommended_action") or derived["recommended_action"]
    ).strip()
    triage_payload = {
        "email_ref": email_ref,
        "classification": _required({"value": classification}, "value"),
        "priority": _required({"value": priority}, "value"),
        "rationale": _required({"value": rationale}, "value"),
        "uncertainty": _required({"value": uncertainty}, "value"),
        "recommended_action": _required({"value": recommended_action}, "value"),
    }
    evidence_has_recipients = any(
        key in payload
        for key in (
            "to",
            "cc",
            "bcc",
            "user_addresses",
            "my_addresses",
            "user_email",
            "first_author",
            "actual_first_author",
            "article_first_author",
            "team_members",
            "lab_members",
            "current_follow_up",
            "followed_up_by",
            "follow_up_by",
        )
    )
    if evidence_has_recipients:
        triage_payload.update(routing)
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
            "policy_digest_kind": "content",
            "decision_scope": "proposal_only",
        }
    )
    if relay_policy_digest:
        triage["relay_policy_digest"] = relay_policy_digest
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
