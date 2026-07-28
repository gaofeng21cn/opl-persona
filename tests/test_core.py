import pytest

from opl_persona.core import (
    build_inbox_capture_proposals,
    build_mail_triage_proposals,
    build_memo_proposals,
    build_obsidian_note_proposals,
    build_publication_proposals,
)


def sha256(value: str) -> str:
    return f"sha256:{value * 64}"


def test_publication_creates_knowledge_and_website_proposals() -> None:
    result = build_publication_proposals(
        {
            "publication_id": "doi:10.1000/example",
            "title": "A publication",
            "authors": ["Feng Gao"],
            "doi": "10.1000/example",
            "source_refs": ["paper://sha256:abc"],
        }
    )
    assert result["schema_version"] == "opl-persona-proposal.v1"
    assert [item["proposal_kind"] for item in result["proposals"]] == [
        "knowledge.ingest",
        "website.publication",
    ]
    assert all(item["approval"]["external_write_allowed"] is False for item in result["proposals"])


def test_memo_creates_website_and_relay_context_proposals() -> None:
    result = build_memo_proposals(
        {
            "memo_id": "obsidian://vault/memo.md",
            "title": "A technical memo",
            "body": "Evidence-backed memo.",
            "tags": ["OPL"],
            "source_refs": ["obsidian://vault/memo.md"],
        }
    )
    assert [item["target"] for item in result["proposals"]] == [
        "gflab_web.content.post",
        "opl-relay.draft.context",
    ]


def test_inputs_require_provenance() -> None:
    try:
        build_publication_proposals({"publication_id": "p", "title": "t"})
    except ValueError as exc:
        assert "source_ref" in str(exc)
    else:
        raise AssertionError("missing provenance must fail closed")


def test_mail_triage_captures_personal_inbox_and_policy_bound_decision() -> None:
    email_ref = "email-store://account/inbox/123"
    result = build_mail_triage_proposals(
        {
            "email_ref": email_ref,
            "source_refs": [email_ref],
            "subject": "Review request",
            "summary": "A manuscript review request needs a decision.",
            "classification": "needs_decision",
            "priority": "high",
            "rationale": "The invitation has a short response window.",
            "uncertainty": "Deadline has not been independently verified.",
            "recommended_action": "Read the message and decide whether to accept.",
            "policy_refs": ["policy://persona/mail-triage/v1"],
            "policy_digest": sha256("a"),
        }
    )

    capture, triage = result["proposals"]
    assert capture["proposal_kind"] == "personal.inbox.v1.capture"
    assert capture["target"] == "personal.inbox.v1"
    assert capture["payload"]["source_refs"] == [email_ref]
    assert triage["proposal_kind"] == "mail.triage"
    assert triage["source_refs"] == [email_ref]
    assert triage["policy_refs"] == ["policy://persona/mail-triage/v1"]
    assert triage["policy_digest"] == sha256("a")
    assert triage["payload"] == {
        "email_ref": email_ref,
        "classification": "needs_decision",
        "priority": "high",
        "rationale": "The invitation has a short response window.",
        "uncertainty": "Deadline has not been independently verified.",
        "recommended_action": "Read the message and decide whether to accept.",
    }
    assert all(item["approval"]["external_write_allowed"] is False for item in result["proposals"])


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            {
                "email_ref": "email-store://account/inbox/123",
                "subject": "Review request",
                "summary": "Summary",
                "classification": "needs_decision",
                "priority": "high",
                "rationale": "Reason",
                "uncertainty": "Unknown",
                "recommended_action": "Read",
                "policy_refs": ["policy://persona/mail-triage/v1"],
                "policy_digest": sha256("b"),
            },
            "source_ref",
        ),
        (
            {
                "email_ref": "email-store://account/inbox/123",
                "source_refs": ["mailbox://account/inbox/123"],
                "subject": "Review request",
                "summary": "Summary",
                "classification": "needs_decision",
                "priority": "high",
                "rationale": "Reason",
                "uncertainty": "Unknown",
                "recommended_action": "Read",
                "policy_refs": ["policy://persona/mail-triage/v1"],
                "policy_digest": sha256("b"),
            },
            "email-store",
        ),
        (
            {
                "email_ref": "email-store://account/inbox/123",
                "source_refs": ["email-store://account/inbox/123"],
                "subject": "Review request",
                "summary": "Summary",
                "classification": "needs_decision",
                "priority": "high",
                "rationale": "Reason",
                "uncertainty": "Unknown",
                "recommended_action": "Read",
                "policy_refs": ["policy://persona/mail-triage/v1"],
            },
            "policy_digest",
        ),
    ],
)
def test_mail_triage_fails_closed_without_stable_evidence_and_policy_provenance(payload, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_mail_triage_proposals(payload)


def test_generic_inbox_capture_is_evidence_backed_and_review_gated() -> None:
    result = build_inbox_capture_proposals(
        {
            "capture_id": "knowledge://memo/1",
            "item_kind": "knowledge",
            "title": "New technical memo",
            "summary": "A memo ready for review.",
            "source_refs": ["obsidian://vault/memos/new.md"],
        }
    )

    proposal = result["proposals"][0]
    assert proposal["target"] == "personal.inbox.v1"
    assert proposal["operation"] == "capture"
    assert proposal["approval"]["external_write_allowed"] is False


def test_obsidian_note_proposal_has_exact_precondition_and_forbids_apply() -> None:
    result = build_obsidian_note_proposals(
        {
            "operation": "update",
            "target_path": "Knowledge/triage-policy.md",
            "frontmatter": {"title": "Triage policy"},
            "body": "# Triage policy\n\nUse evidence.",
            "links": ["[[Mail triage]]"],
            "tags": ["policy", "mail"],
            "evidence_refs": ["email-store://account/inbox/123"],
            "expected_digest": sha256("c"),
        }
    )

    proposal = result["proposals"][0]
    assert proposal["proposal_kind"] == "knowledge.obsidian.note.v1"
    assert proposal["target"] == "knowledge.obsidian.note.v1"
    assert proposal["operation"] == "update"
    assert proposal["target_path"] == "Knowledge/triage-policy.md"
    assert proposal["payload"] == {
        "target_path": "Knowledge/triage-policy.md",
        "frontmatter": {"title": "Triage policy"},
        "body": "# Triage policy\n\nUse evidence.",
        "links": ["[[Mail triage]]"],
        "tags": ["policy", "mail"],
        "evidence_refs": ["email-store://account/inbox/123"],
        "expected_digest": sha256("c"),
    }
    assert proposal["allowed_outputs"] == ["reviewable_proposal"]
    assert "knowledge.obsidian.note.v1.apply" in proposal["forbidden_outputs"]
    assert proposal["approval"]["external_write_allowed"] is False


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            {
                "operation": "create",
                "target_path": "../outside.md",
                "body": "Body",
                "evidence_refs": ["obsidian://vault/source.md"],
                "expected_digest": "absent",
            },
            "target_path",
        ),
        (
            {
                "operation": "create",
                "target_path": "Knowledge/new.md",
                "body": "Body",
                "evidence_refs": [],
                "expected_digest": "absent",
            },
            "evidence_refs",
        ),
        (
            {
                "operation": "create",
                "target_path": "Knowledge/new.md",
                "body": "Body",
                "evidence_refs": ["obsidian://vault/source.md"],
                "expected_digest": sha256("d"),
            },
            "expected_digest",
        ),
    ],
)
def test_obsidian_note_fails_closed_for_unsafe_target_or_missing_precondition(payload, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_obsidian_note_proposals(payload)
