import hashlib
import json
from email.utils import getaddresses
from typing import Any


def relay_policy_digest(refs: list[str]) -> str:
    normalized = sorted(refs)
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def relay_v2_evidence(
    *,
    source_ref: str = "email-store://sysu/INBOX/123/0123456789abcdef",
    subject: str = "Manuscript revision reminder",
    body: str = "The journal requests an author response.",
    to: str = "Feng Gao <gaof57@mail.sysu.edu.cn>",
    cc: str = "",
    bcc: str = "",
    policy_refs: list[str] | None = None,
) -> dict[str, Any]:
    refs = policy_refs or ["policy://relay/mail-facts/v2"]
    def addresses(value: str) -> list[dict[str, str]]:
        return [
            {"name": name, "address": address}
            for name, address in getaddresses([value])
            if address
        ]

    to_addresses = addresses(to)
    cc_addresses = addresses(cc)
    bcc_addresses = addresses(bcc)
    recipient_count = len({item["address"] for item in [*to_addresses, *cc_addresses, *bcc_addresses]})
    return {
        "schema_version": "opl-relay-mail-triage-evidence.v2",
        "source_refs": [source_ref],
        "mail": {
            "source_ref": source_ref,
            "headers": {
                "subject": subject,
                "from": "Editor <editor@example.org>",
                "to": to,
                "cc": cc,
                "bcc": bcc,
            },
            "routing_facts": {
                "to_addresses": to_addresses,
                "cc_addresses": cc_addresses,
                "bcc_addresses": bcc_addresses,
                "recipient_count": recipient_count,
                "is_unique_recipient": recipient_count == 1,
            },
            "raw_readback": {
                "status": "available",
                "raw_sha256": "a" * 64,
                "raw_eml_sha256": "b" * 64,
                "body_text": body,
            },
        },
        "freshness": {
            "status": "local_store_readback",
            "observed_at": "2026-07-28T09:02:00+00:00",
            "ingested_at": "2026-07-28T09:01:00+00:00",
            "message_date": "2026-07-28T09:00:00+00:00",
        },
        "policy": {
            "policy_refs": refs,
            "policy_digest": relay_policy_digest(refs),
        },
        "triage": {"mode": "evidence_only", "personal_judgment": "not_provided"},
        "risk": {
            "requires_human_review": True,
            "external_write_allowed": False,
            "provider_write_reachable": False,
        },
        "provider_write": {"status": "unreachable"},
    }
