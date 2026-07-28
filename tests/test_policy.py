from pathlib import Path

import pytest

from opl_persona.core import build_mail_triage_proposals
from opl_persona.policy import DEFAULT_POLICY_REF, load_markdown_policies


def test_markdown_policy_snapshot_hashes_content_and_exposes_stable_ref(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    policy = workspace / "policies" / "mail-triage.md"
    policy.parent.mkdir(parents=True)
    policy.write_text("# Mail rules\n\nPrioritize submissions.", encoding="utf-8")

    first = load_markdown_policies(workspace=workspace)
    assert first.refs == (DEFAULT_POLICY_REF,)
    assert first.documents[0].content.startswith("# Mail rules")
    assert first.digest.startswith("sha256:")

    policy.write_text("# Mail rules\n\nPrioritize submissions and proofs.", encoding="utf-8")
    second = load_markdown_policies(workspace=workspace)
    assert second.digest != first.digest


def test_mail_triage_can_derive_routing_from_workspace_policy(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    policy = workspace / "policies" / "mail-triage.md"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        "# Mail rules\n\n投稿论文及杂志社提醒是第一优先级。",
        encoding="utf-8",
    )
    email_ref = "email-store://sysu/inbox/1"
    result = build_mail_triage_proposals(
        {
            "email_ref": email_ref,
            "source_refs": [email_ref],
            "subject": "Manuscript revision reminder",
            "summary": "The journal requests an author response.",
            "policy_workspace": str(workspace),
            "to": ["gaof57@mail.sysu.edu.cn"],
            "cc": [],
            "bcc": [],
            "user_addresses": ["gaof57@mail.sysu.edu.cn"],
            "actual_first_author": {
                "name": "Student One",
                "email": "student@example.edu",
            },
            "team_members": [
                {"name": "Student One", "email": "student@example.edu"},
            ],
        }
    )

    triage = result["proposals"][1]
    assert triage["policy_refs"] == [DEFAULT_POLICY_REF]
    assert triage["policy_digest"] == load_markdown_policies(workspace=workspace).digest
    assert triage["payload"]["classification"] == "needs_user_reply"
    assert triage["payload"]["priority"] == "highest"
    assert triage["payload"]["is_unique_recipient"] is True
    assert triage["payload"]["forward_to"]["email"] == "student@example.edu"
    assert triage["payload"]["team_member_match"]["matched"] is True
    assert triage["approval"]["external_write_allowed"] is False


def test_mail_triage_rejects_policy_ref_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "policies").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        load_markdown_policies(
            workspace=workspace,
            refs=["policy://persona/not-in-workspace/v1"],
        )


def test_relay_refs_digest_is_not_reused_as_persona_content_digest(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    policy = workspace / "policies" / "mail-triage.md"
    policy.parent.mkdir(parents=True)
    policy.write_text("# Mail rules\n\nKeep manuscript reminders.", encoding="utf-8")
    email_ref = "email-store://sysu/inbox/2"
    relay_digest = "sha256:" + "f" * 64
    result = build_mail_triage_proposals(
        {
            "email_ref": email_ref,
            "source_refs": [email_ref],
            "subject": "Manuscript reminder",
            "summary": "A journal deadline is approaching.",
            "policy_workspace": str(workspace),
            "policy_refs": [DEFAULT_POLICY_REF],
            "policy_digest_kind": "refs_set",
            "policy_digest": relay_digest,
            "to": ["gaof57@mail.sysu.edu.cn"],
            "user_addresses": ["gaof57@mail.sysu.edu.cn"],
        }
    )
    triage = result["proposals"][1]
    assert triage["policy_digest"] != relay_digest
    assert triage["policy_digest_kind"] == "content"
    assert triage["relay_policy_digest"] == relay_digest
