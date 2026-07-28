from pathlib import Path

import pytest

from opl_persona.approvals import approve_proposal
from opl_persona.bindings import binding_for_resource, read_binding_health
from opl_persona.core import build_memo_proposals


def test_relay_approval_preserves_proposal_shape_without_send_authority() -> None:
    proposal = next(
        item
        for item in build_memo_proposals(
            {
                "memo_id": "obsidian://vault/memo.md",
                "title": "A technical memo",
                "body": "Evidence-backed body.",
                "source_refs": ["obsidian://vault/memo.md"],
            }
        )["proposals"]
        if item["proposal_kind"] == "mail.draft_context"
    )

    approved = approve_proposal(
        proposal,
        approval_ref="approval://user/relay-draft-1",
    )

    assert approved["schema_version"] == "opl-persona-proposal.v1"
    assert approved["proposal_kind"] == "mail.draft_context"
    assert approved["target"] == "opl-relay.draft.context"
    assert approved["operation"] == "prepare"
    assert approved["proposal_id"]
    assert approved["source_refs"] == ["obsidian://vault/memo.md"]
    assert approved["approval"]["required"] is True
    assert approved["approval"]["status"] == "approved"
    assert approved["approval"]["external_write_allowed"] is False
    assert approved["approval"]["approval_ref"] == "approval://user/relay-draft-1"
    assert approved["approval"]["proposal_digest"].startswith("sha256:")


def test_binding_is_refs_only_and_health_probe_is_read_back(tmp_path: Path) -> None:
    resource_ref = (tmp_path / "vault").resolve().as_uri()
    binding = binding_for_resource(
        capability_id="knowledge.documents.v1",
        provider_id="obsidian",
        resource_ref=resource_ref,
        scopes=["notes.read", "notes.write"],
        policy={"approval_required": True},
    )

    value = binding.to_dict()
    assert value["resource_ref"] == resource_ref
    assert set(value) == {
        "schema_version",
        "capability_id",
        "provider_id",
        "resource_ref",
        "scopes",
        "policy",
        "health",
    }
    health = read_binding_health(
        binding,
        probe=lambda ref: {
            "status": "healthy",
            "reason": "vault_reachable",
            "revision_ref": "filesystem-stat://123",
        },
    )
    assert health["status"] == "healthy"
    assert health["resource_ref"] == resource_ref
    assert health["revision_ref"] == "filesystem-stat://123"


@pytest.mark.parametrize("key", ["token", "api_key", "nested"])
def test_binding_rejects_credential_shaped_policy(key: str, tmp_path: Path) -> None:
    policy = {key: "secret"} if key != "nested" else {"nested": {"access_token": "secret"}}
    with pytest.raises(ValueError, match="credential"):
        binding_for_resource(
            capability_id="knowledge.documents.v1",
            provider_id="obsidian",
            resource_ref=(tmp_path / "vault").resolve().as_uri(),
            scopes=["notes.read"],
            policy=policy,
        )
