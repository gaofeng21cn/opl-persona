from __future__ import annotations

import hashlib
import json
import re
from email.utils import getaddresses, parseaddr
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Mapping

from .paths import PersonaPaths
from .policy import (
    MailContextSnapshot,
    PolicySnapshot,
    load_mail_context,
    load_markdown_policies,
    resolve_manuscript_context,
)

SCHEMA_VERSION = "opl-persona-proposal.v1"
RELAY_TRIAGE_EVIDENCE_SCHEMA = "opl-relay-mail-triage-evidence.v2"
RELAY_POLICY_DIGEST_SCOPE = "relay_policy_refs.v1"
_EMAIL_STORE_REF = re.compile(r"^email-store://[^/\s]+/[^/\s]+/[1-9][0-9]*/[0-9a-f]{16}$")
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


def _email_store_source_refs(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) != 1:
        raise ValueError("Relay triage evidence must contain exactly one source_refs entry")
    refs = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(refs) != 1 or not _EMAIL_STORE_REF.fullmatch(refs[0]):
        raise ValueError("Relay triage evidence source_refs must use canonical email-store identities")
    return refs


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError(f"{name} must be a sha256 digest")
    return value


def _relay_policy_digest(refs: list[str]) -> str:
    encoded = json.dumps(sorted(refs), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _hex_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _relay_v2_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Verify Relay's facts-only envelope before Persona interprets it."""

    if set(payload) != {"relay_evidence"}:
        raise ValueError("mail triage accepts only a relay_evidence bridge input")
    evidence = payload.get("relay_evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("relay_evidence must be an object")
    if evidence.get("schema_version") != RELAY_TRIAGE_EVIDENCE_SCHEMA:
        raise ValueError(f"relay_evidence.schema_version must be {RELAY_TRIAGE_EVIDENCE_SCHEMA}")
    source_refs = _email_store_source_refs(evidence.get("source_refs"))
    mail = evidence.get("mail")
    if not isinstance(mail, Mapping) or mail.get("source_ref") != source_refs[0]:
        raise ValueError("relay_evidence.mail.source_ref must match source_refs[0]")
    headers = mail.get("headers")
    if not isinstance(headers, Mapping):
        raise ValueError("relay_evidence.mail.headers is required")
    subject = headers.get("subject")
    if not isinstance(subject, str):
        raise ValueError("relay_evidence.mail.headers.subject must be a string")
    sender = headers.get("from")
    if not isinstance(sender, str):
        raise ValueError("relay_evidence.mail.headers.from must be a string")
    for name in ("to", "cc", "bcc"):
        if not isinstance(headers.get(name), str):
            raise ValueError(f"relay_evidence.mail.headers.{name} must be a string")
    raw_readback = mail.get("raw_readback")
    if not isinstance(raw_readback, Mapping) or raw_readback.get("status") != "available":
        raise ValueError("relay_evidence.mail.raw_readback must be available")
    _hex_digest(raw_readback.get("raw_sha256"), "relay_evidence.mail.raw_readback.raw_sha256")
    _hex_digest(raw_readback.get("raw_eml_sha256"), "relay_evidence.mail.raw_readback.raw_eml_sha256")
    body = raw_readback.get("body_text")
    if not isinstance(body, str):
        raise ValueError("relay_evidence.mail.raw_readback.body_text must be a string")
    freshness = evidence.get("freshness")
    if not isinstance(freshness, Mapping) or freshness.get("status") != "local_store_readback":
        raise ValueError("relay_evidence.freshness must record a local_store_readback")
    for field in ("observed_at", "ingested_at", "message_date"):
        if not isinstance(freshness.get(field), str) or not freshness[field].strip():
            raise ValueError(f"relay_evidence.freshness.{field} is required")
    policy = evidence.get("policy")
    if not isinstance(policy, Mapping):
        raise ValueError("relay_evidence.policy is required")
    relay_policy_refs = _string_list(policy, "policy_refs", required=True)
    relay_policy_digest = _sha256(policy.get("policy_digest"), "relay_evidence.policy.policy_digest")
    if relay_policy_digest != _relay_policy_digest(relay_policy_refs):
        raise ValueError("relay_evidence.policy.policy_digest does not match policy_refs")
    triage = evidence.get("triage")
    if not isinstance(triage, Mapping) or triage.get("mode") != "evidence_only":
        raise ValueError("relay_evidence.triage must remain evidence_only")
    risk = evidence.get("risk")
    if not isinstance(risk, Mapping) or risk.get("external_write_allowed") is not False:
        raise ValueError("relay_evidence.risk must forbid external writes")
    if risk.get("provider_write_reachable") is not False:
        raise ValueError("relay_evidence.risk must not expose provider writes")
    provider_write = evidence.get("provider_write")
    if not isinstance(provider_write, Mapping) or provider_write.get("status") != "unreachable":
        raise ValueError("relay_evidence.provider_write must remain unreachable")
    routing_facts = mail.get("routing_facts")
    if not isinstance(routing_facts, Mapping):
        raise ValueError("relay_evidence.mail.routing_facts must be an object")
    allowed_routing_fields = {
        "to_addresses",
        "cc_addresses",
        "bcc_addresses",
        "recipient_count",
        "is_unique_recipient",
    }
    unexpected = sorted(set(routing_facts) - allowed_routing_fields)
    if unexpected:
        raise ValueError("relay_evidence.mail.routing_facts contains unsupported fields: " + ", ".join(unexpected))
    normalized_headers = {}
    for name in ("to", "cc", "bcc"):
        fact_name = f"{name}_addresses"
        values = routing_facts.get(fact_name)
        if not isinstance(values, list):
            raise ValueError(f"relay_evidence.mail.routing_facts.{fact_name} must be an array")
        if not all(
            isinstance(item, Mapping)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("address"), str)
            and item["address"].strip()
            for item in values
        ):
            raise ValueError(f"relay_evidence.mail.routing_facts.{fact_name} contains an invalid recipient")
        parsed_header = _address_strings(headers[name])
        parsed_facts = _addresses(values)
        if parsed_header != parsed_facts:
            raise ValueError(f"relay_evidence.mail.routing_facts.{fact_name} must match mail.headers.{name}")
        normalized_headers[name] = parsed_facts
    recipient_count = routing_facts.get("recipient_count")
    unique_recipient = routing_facts.get("is_unique_recipient")
    if isinstance(recipient_count, bool) or not isinstance(recipient_count, int) or recipient_count < 0:
        raise ValueError("relay_evidence.mail.routing_facts.recipient_count must be a non-negative integer")
    observed_count = len(
        {
            item["email"]
            for recipients in normalized_headers.values()
            for item in recipients
        }
    )
    if recipient_count != observed_count:
        raise ValueError("relay_evidence.mail.routing_facts.recipient_count must match mail.headers")
    if not isinstance(unique_recipient, bool):
        raise ValueError("relay_evidence.mail.routing_facts.is_unique_recipient must be a boolean")
    if unique_recipient != (recipient_count == 1):
        raise ValueError("relay_evidence.mail.routing_facts.is_unique_recipient must match recipient_count")
    return {
        "email_ref": source_refs[0],
        "source_refs": source_refs,
        "subject": subject.strip(),
        "summary": body.strip()[:_MAX_TRIAGE_SUMMARY] or subject.strip(),
        "body": body,
        "from": sender.strip(),
        "to": normalized_headers["to"],
        "cc": normalized_headers["cc"],
        "bcc": normalized_headers["bcc"],
        "user_addresses": [],
        "actual_first_author": None,
        "team_members": [],
        "follow_up_by": None,
        "relay_policy_refs": relay_policy_refs,
        "relay_policy_digest": relay_policy_digest,
        "relay_evidence_schema": RELAY_TRIAGE_EVIDENCE_SCHEMA,
    }


_MAX_TRIAGE_SUMMARY = 4096


def _policy_provenance() -> tuple[list[str], str, PolicySnapshot]:
    """Load every Markdown rule from the one Profile Workspace or fail closed."""

    snapshot = load_markdown_policies(workspace=PersonaPaths.resolve().workspace)
    return list(snapshot.refs), snapshot.digest, snapshot


def _mail_context_provenance() -> MailContextSnapshot:
    """Load identity and routing facts from the same selected Profile."""

    return load_mail_context(workspace=PersonaPaths.resolve().workspace)


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
    forwarded = (
        first_author
        if unique_recipient and matched_team_member and first_author and first_author.get("email")
        else matched_team_member if unique_recipient and matched_team_member else None
    )
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

    Persona accepts only a verified Relay v2 facts-only envelope. Relay remains
    the authority for the email identity, mailbox state, draft lifecycle, and
    any later action; Persona reloads its own Markdown policy before judging it.
    """
    relay = _relay_v2_evidence(payload)
    email_ref = relay["email_ref"]
    source_refs = relay["source_refs"]
    policy_refs, policy_digest, policy_snapshot = _policy_provenance()
    subject = relay["subject"]
    summary = relay["summary"]
    mail_context = _mail_context_provenance()
    manuscript_context = resolve_manuscript_context(
        mail_context,
        subject=subject,
        body=relay["body"],
    )
    relay["user_addresses"] = list(mail_context.user_addresses)
    relay["team_members"] = [dict(item) for item in mail_context.team_members]
    relay.update(manuscript_context)
    routing = _recipient_analysis(relay)
    derived = _policy_classification(relay, routing=routing, policy=policy_snapshot)
    classification = derived["classification"]
    priority = derived["priority"]
    rationale = derived["rationale"]
    default_uncertainty = "未发现额外不确定性。"
    if not routing["recipient_identity_known"] and (
        routing["to"] or routing["cc"] or routing["bcc"]
    ):
        default_uncertainty = "缺少用户自身邮箱 identity，无法确认是否为唯一收件人。"
    elif routing.get("actual_first_author") and not routing["team_member_match"]["matched"]:
        default_uncertainty = "实际第一作者或团队成员匹配信息不完整。"
    uncertainty = default_uncertainty
    recommended_action = derived["recommended_action"]
    triage_payload = {
        "email_ref": email_ref,
        "classification": _required({"value": classification}, "value"),
        "priority": _required({"value": priority}, "value"),
        "rationale": _required({"value": rationale}, "value"),
        "uncertainty": _required({"value": uncertainty}, "value"),
        "recommended_action": _required({"value": recommended_action}, "value"),
    }
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
            "relay_policy_refs": relay["relay_policy_refs"],
            "relay_policy_digest": relay["relay_policy_digest"],
            "relay_policy_digest_scope": RELAY_POLICY_DIGEST_SCOPE,
            "relay_evidence_schema": relay["relay_evidence_schema"],
            "context_refs": list(mail_context.refs),
            "context_digest": mail_context.digest,
            "context_digest_kind": "content",
            "manuscript_alias": manuscript_context.get("manuscript_alias"),
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
