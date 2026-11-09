import hashlib
import json
from pathlib import Path

import pytest

from opl_persona.core import build_mail_triage_proposals
from opl_persona.policy import load_mail_context, load_markdown_policies

from knowledge_inputs import POLICY_ID, POLICY_REF, configure_knowledge_inputs
from relay_v2 import mail_assessment, relay_v2_evidence


def test_policy_snapshot_hashes_accepted_content_and_exposes_source_identity(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bodies = configure_knowledge_inputs(monkeypatch, workspace)
    first = load_markdown_policies(workspace=workspace)
    assert first.refs == (POLICY_REF,)
    assert first.documents[0].content.startswith("# Mail rules")
    assert first.digest.startswith("sha256:")
    expected_revision = "sha256:" + hashlib.sha256(bodies[POLICY_ID].encode("utf-8")).hexdigest()
    assert first.source_versions == {POLICY_ID: expected_revision}
    assert first.to_dict()["source_versions"] == first.source_versions
    assert first.to_dict()["sources"] == [{
        "knowledge_id": POLICY_ID, "source_ref": POLICY_REF,
        "digest": first.documents[0].digest,
    }]
    assert "path" not in first.to_dict()["sources"][0]

    bodies[POLICY_ID] = "# Mail rules\n\nPrioritize submissions and proofs."
    second = load_markdown_policies(workspace=workspace)
    assert second.digest != first.digest
    assert second.documents[0].digest != first.documents[0].digest


def test_mail_triage_reloads_selector_workspace_policy(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    configure_knowledge_inputs(monkeypatch, workspace)
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(workspace))
    evidence = relay_v2_evidence(
        subject="Manuscript revision reminder",
        body="The journal requests an author response.",
    )
    result = build_mail_triage_proposals({
        "relay_evidence": evidence, "assessment": mail_assessment(evidence),
    })
    triage = result["proposals"][1]
    assert triage["policy_refs"] == [POLICY_REF]
    assert triage["policy_digest"] == load_markdown_policies(workspace=workspace).digest
    assert triage["payload"]["classification"] == "needs_user_reply"
    assert triage["policy_digest"] != evidence["policy"]["policy_digest"]
    assert triage["approval"]["external_write_allowed"] is False


def test_relay_refs_digest_is_not_reused_as_persona_content_digest(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    configure_knowledge_inputs(monkeypatch, workspace)
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(workspace))
    evidence = relay_v2_evidence()
    triage = build_mail_triage_proposals({
        "relay_evidence": evidence, "assessment": mail_assessment(evidence),
    })["proposals"][1]
    assert triage["policy_digest"] != evidence["policy"]["policy_digest"]
    assert triage["policy_digest_kind"] == "content"
    assert triage["relay_policy_digest"] == evidence["policy"]["policy_digest"]


def test_local_policy_directory_cannot_bypass_accepted_sources(tmp_path: Path) -> None:
    policy = tmp_path / "policies" / "mail-triage.md"
    policy.parent.mkdir()
    policy.write_text("# Existing local rules", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="knowledge inputs are not configured"):
        load_markdown_policies(workspace=tmp_path)


def test_mail_policy_role_is_required_but_context_roles_are_optional(monkeypatch, tmp_path: Path) -> None:
    configure_knowledge_inputs(monkeypatch, tmp_path, roles={})
    with pytest.raises(ValueError, match="mail_policy knowledge inputs are required"):
        load_markdown_policies(workspace=tmp_path)
    context = load_mail_context(workspace=tmp_path)
    assert context.refs == context.user_addresses == context.team_members == context.projects == ()
    assert context.source_versions == {}


@pytest.mark.parametrize("roles", [
    {"unrecognized": [POLICY_ID]},
    {"mail_policy": POLICY_ID},
    {"mail_policy": ["/arbitrary/path.md"]},
    {"mail_policy": [{"knowledge_id": POLICY_ID}]},
    {"mail_policy": [POLICY_ID, POLICY_ID]},
])
def test_knowledge_inputs_reject_paths_unknown_roles_and_malformed_ids(monkeypatch, tmp_path: Path, roles) -> None:
    configure_knowledge_inputs(monkeypatch, tmp_path, roles=roles)
    with pytest.raises(ValueError, match="invalid schema or role|unique knowledge IDs"):
        load_markdown_policies(workspace=tmp_path)


def test_knowledge_inputs_cannot_embed_source_roots_or_grants(monkeypatch, tmp_path: Path) -> None:
    configure_knowledge_inputs(monkeypatch, tmp_path)
    inputs = tmp_path / "data" / "persona" / "knowledge-inputs.json"
    value = json.loads(inputs.read_text())
    value["root"] = "/some/other/place"
    inputs.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="invalid schema or role"):
        load_markdown_policies(workspace=tmp_path)


@pytest.mark.parametrize("role", ["mail_policy", "identity", "team", "projects"])
def test_selected_invalid_source_fails_without_local_fallback(monkeypatch, tmp_path: Path, role: str) -> None:
    configure_knowledge_inputs(monkeypatch, tmp_path, roles={role: ["owner.revoked"]}, bodies={})
    local = tmp_path / "policies" / "mail-triage.md"
    local.parent.mkdir()
    local.write_text("# Old local fallback", encoding="utf-8")
    loader = load_markdown_policies if role == "mail_policy" else load_mail_context
    with pytest.raises(ValueError, match="current Framework readback"):
        loader(workspace=tmp_path)


def test_policy_snapshot_is_stable_across_selection_order_and_physical_location(monkeypatch, tmp_path: Path) -> None:
    bodies = {"owner.a": "A", "owner.b": "B"}
    configure_knowledge_inputs(monkeypatch, tmp_path, roles={"mail_policy": ["owner.b", "owner.a"]}, bodies=bodies)
    first = load_markdown_policies(workspace=tmp_path)
    other = tmp_path / "other"
    configure_knowledge_inputs(monkeypatch, other, roles={"mail_policy": ["owner.a", "owner.b"]}, bodies=bodies)
    second = load_markdown_policies(workspace=other)
    assert first.digest == second.digest
    assert first.refs == second.refs


def test_context_roles_use_only_explicit_accepted_inputs(monkeypatch, tmp_path: Path) -> None:
    body = "# Identity\n\n- addresses: Owner@Example.com\n"
    configure_knowledge_inputs(monkeypatch, tmp_path, roles={"identity": ["owner.identity"]}, bodies={"owner.identity": body})
    unselected = tmp_path / "profile" / "identity.md"
    unselected.parent.mkdir()
    unselected.write_text("- addresses: unrelated@example.com", encoding="utf-8")
    first = load_mail_context(workspace=tmp_path)
    assert first.user_addresses == ("owner@example.com",)
    assert first.refs == ("knowledge://owner.identity",)
    assert first.source_versions == {
        "owner.identity": "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    configure_knowledge_inputs(monkeypatch, tmp_path, roles={"projects": ["owner.identity"]}, bodies={"owner.identity": body})
    second = load_mail_context(workspace=tmp_path)
    assert second.user_addresses == ()
    assert second.digest != first.digest
