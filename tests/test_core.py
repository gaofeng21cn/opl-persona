import copy
from pathlib import Path

import pytest

from opl_persona.core import (
    build_inbox_capture_proposals,
    build_mail_triage_proposals,
    build_memo_proposals,
    build_obsidian_note_proposals,
    build_publication_proposals,
)
from opl_persona.policy import load_markdown_policies

from relay_v2 import relay_v2_evidence


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


def _write_policy(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    policy = profile / "policies" / "mail-triage.md"
    policy.parent.mkdir(parents=True)
    policy.write_text("# Mail rules\n\nPrioritize manuscript matters.", encoding="utf-8")
    return profile


def _write_routing_context(profile: Path) -> None:
    mail_profile = profile / "profile" / "mail-profile.md"
    mail_profile.parent.mkdir(parents=True)
    mail_profile.write_text(
        "# Mail Profile\n\n- owner: Feng Gao\n"
        "- addresses: gaof57@mail.sysu.edu.cn, gaofeng21cn@gmail.com\n",
        encoding="utf-8",
    )
    people = profile / "context" / "people.md"
    people.parent.mkdir(parents=True)
    people.write_text(
        "# People\n\n"
        "| Name | Group | Public email |\n"
        "| --- | --- | --- |\n"
        "| Yin-Meng Zhang | Student | ymzhang1997@outlook.com |\n",
        encoding="utf-8",
    )
    projects = profile / "context" / "projects.md"
    projects.write_text(
        "# Projects\n\n"
        "## Spectrum00815-26R1\n\n"
        "- title: Integrative Multi-Omics Profiling of Insomnia-Related Molecular Features\n"
        "- actual first author: Yin-Meng Zhang\n"
        "- verified routing address: yinmeng23@mails.jlu.edu.cn\n",
        encoding="utf-8",
    )


def test_mail_triage_captures_personal_inbox_and_policy_bound_decision(
    monkeypatch, tmp_path: Path
) -> None:
    profile = _write_policy(tmp_path)
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(profile))
    evidence = relay_v2_evidence()
    email_ref = evidence["source_refs"][0]
    result = build_mail_triage_proposals(
        {
            "relay_evidence": evidence,
        }
    )

    capture, triage = result["proposals"]
    assert capture["proposal_kind"] == "personal.inbox.v1.capture"
    assert capture["target"] == "personal.inbox.v1"
    assert capture["payload"]["source_refs"] == [email_ref]
    assert triage["proposal_kind"] == "mail.triage"
    assert triage["source_refs"] == [email_ref]
    assert triage["policy_refs"] == ["policy://persona/mail-triage/v1"]
    assert triage["policy_digest"] == load_markdown_policies(workspace=profile).digest
    assert triage["policy_digest"] != evidence["policy"]["policy_digest"]
    assert triage["relay_policy_digest"] == evidence["policy"]["policy_digest"]
    assert triage["relay_evidence_schema"] == evidence["schema_version"]
    assert triage["payload"]["email_ref"] == email_ref
    assert triage["payload"]["classification"] == "needs_user_reply"
    assert triage["payload"]["priority"] == "high"
    assert triage["payload"]["to"] == [{"email": "gaof57@mail.sysu.edu.cn", "name": "Feng Gao"}]
    assert all(item["approval"]["external_write_allowed"] is False for item in result["proposals"])


@pytest.mark.parametrize(
    ("cc", "expected_action"),
    [
        ("", "forward_to_first_author"),
        ("Yin-Meng Zhang <yinmeng23@mails.jlu.edu.cn>", "notify_user_with_follow_up"),
    ],
)
def test_mail_triage_resolves_first_author_routing_from_profile_context(
    monkeypatch,
    tmp_path: Path,
    cc: str,
    expected_action: str,
) -> None:
    profile = _write_policy(tmp_path)
    _write_routing_context(profile)
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(profile))
    evidence = relay_v2_evidence(
        subject="Spectrum00815-26R1 production query",
        body="Please answer the Figure 1 licensing query.",
        cc=cc,
    )

    triage = build_mail_triage_proposals({"relay_evidence": evidence})["proposals"][1]

    assert triage["manuscript_alias"] == "Spectrum00815-26R1"
    assert triage["context_digest"].startswith("sha256:")
    assert triage["payload"]["recommended_action"] == expected_action
    assert triage["payload"]["actual_first_author"] == {
        "name": "Yin-Meng Zhang",
        "email": "yinmeng23@mails.jlu.edu.cn",
    }
    if cc:
        assert triage["payload"]["forward_to"] is None
        assert triage["payload"]["notification"]["required"] is True
        assert triage["payload"]["follow_up_by"]["email"] == "yinmeng23@mails.jlu.edu.cn"
    else:
        assert triage["payload"]["is_unique_recipient"] is True
        assert triage["payload"]["forward_to"]["email"] == "yinmeng23@mails.jlu.edu.cn"


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda evidence: evidence.__setitem__("schema_version", "opl-relay-mail-triage-evidence.v1"),
            "schema_version",
        ),
        (
            lambda evidence: evidence["policy"].__setitem__("policy_digest", sha256("f")),
            "policy_digest",
        ),
        (
            lambda evidence: evidence["risk"].__setitem__("external_write_allowed", True),
            "forbid external writes",
        ),
        (
            lambda evidence: evidence["mail"]["routing_facts"].__setitem__("recipient_count", 2),
            "recipient_count",
        ),
    ],
)
def test_mail_triage_fails_closed_for_invalid_relay_v2_bridge(
    monkeypatch, tmp_path: Path, mutate, message: str
) -> None:
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(_write_policy(tmp_path)))
    evidence = relay_v2_evidence()
    mutate(evidence)
    with pytest.raises(ValueError, match=message):
        build_mail_triage_proposals({"relay_evidence": evidence})


def test_mail_triage_rejects_scattered_headers_and_external_digest(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(_write_policy(tmp_path)))
    with pytest.raises(ValueError, match="relay_evidence bridge input"):
        build_mail_triage_proposals(
            {
                "email_ref": "email-store://sysu/INBOX/123/0123456789abcdef",
                "policy_digest": sha256("a"),
            }
        )


def test_mail_triage_fails_closed_without_persona_markdown(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "empty-profile"))
    with pytest.raises(FileNotFoundError, match="no Markdown policies"):
        build_mail_triage_proposals({"relay_evidence": relay_v2_evidence()})


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
