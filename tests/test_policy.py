from pathlib import Path

from opl_persona.core import build_mail_triage_proposals
from opl_persona.policy import DEFAULT_POLICY_REF, load_markdown_policies

from relay_v2 import relay_v2_evidence

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


def test_mail_triage_reloads_selector_workspace_policy(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    policy = workspace / "policies" / "mail-triage.md"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        "# Mail rules\n\n投稿论文及杂志社提醒是第一优先级。",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(workspace))
    evidence = relay_v2_evidence(
        subject="Manuscript revision reminder",
        body="The journal requests an author response.",
    )
    result = build_mail_triage_proposals(
        {
            "relay_evidence": evidence,
        }
    )

    triage = result["proposals"][1]
    assert triage["policy_refs"] == [DEFAULT_POLICY_REF]
    assert triage["policy_digest"] == load_markdown_policies(workspace=workspace).digest
    assert triage["payload"]["classification"] == "needs_user_reply"
    assert triage["policy_digest"] != evidence["policy"]["policy_digest"]
    assert triage["approval"]["external_write_allowed"] is False


def test_relay_refs_digest_is_not_reused_as_persona_content_digest(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    policy = workspace / "policies" / "mail-triage.md"
    policy.parent.mkdir(parents=True)
    policy.write_text("# Mail rules\n\nKeep manuscript reminders.", encoding="utf-8")
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(workspace))
    evidence = relay_v2_evidence()
    relay_digest = evidence["policy"]["policy_digest"]
    result = build_mail_triage_proposals(
        {
            "relay_evidence": evidence,
        }
    )
    triage = result["proposals"][1]
    assert triage["policy_digest"] != relay_digest
    assert triage["policy_digest_kind"] == "content"
    assert triage["relay_policy_digest"] == relay_digest
