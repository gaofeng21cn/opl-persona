import hashlib
from pathlib import Path

import pytest

from opl_persona.approvals import approve_proposal
from opl_persona.bindings import binding_for_resource
from opl_persona.core import build_obsidian_note_proposals
from opl_persona.obsidian_apply import apply_approved_obsidian_note


def digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def binding(vault: Path):
    return binding_for_resource(
        capability_id="knowledge.documents.v1",
        provider_id="obsidian",
        resource_ref=vault.resolve().as_uri(),
        scopes=["notes.read", "notes.write"],
        policy={"approval_required": True},
    )


def proposal(*, operation: str, target_path: str, body: str, expected_digest: str):
    return build_obsidian_note_proposals(
        {
            "operation": operation,
            "target_path": target_path,
            "frontmatter": {"title": "Technical memo", "draft": False},
            "body": body,
            "links": ["[[Related note]]"],
            "tags": ["technical-memo"],
            "evidence_refs": ["paper://doi/10.1000/example"],
            "expected_digest": expected_digest,
        }
    )["proposals"][0]


def test_approved_create_is_atomic_and_returns_authority_readback(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note_proposal = proposal(
        operation="create",
        target_path="Knowledge/new-memo.md",
        body="# Technical memo\n\nEvidence-backed content.",
        expected_digest="absent",
    )
    approved = approve_proposal(
        note_proposal,
        approval_ref="approval://user/obsidian-create-1",
        external_write_allowed=True,
    )

    receipt = apply_approved_obsidian_note(
        approved,
        approved["approval"],
        binding=binding(vault),
    )

    note = vault / "Knowledge/new-memo.md"
    content = note.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert 'title: "Technical memo"' in content
    assert "tags: [\"technical-memo\"]" in content
    assert "source_refs: [\"paper://doi/10.1000/example\"]" in content
    assert "# Technical memo\n\nEvidence-backed content." in content
    assert "## Links\n\n- [[Related note]]" in content
    assert receipt["status"] == "applied"
    assert receipt["target_path"] == "Knowledge/new-memo.md"
    assert receipt["readback"] == {
        "digest": digest(note.read_bytes()),
        "bytes": len(note.read_bytes()),
        "matches_written_bytes": True,
    }
    assert not list(vault.rglob(".persona-note.*"))


def test_update_rechecks_expected_digest_and_preserves_file_on_mismatch(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "memo.md"
    original = b"# Existing\n"
    note.write_bytes(original)
    note_proposal = proposal(
        operation="update",
        target_path="memo.md",
        body="# Updated",
        expected_digest="sha256:" + "0" * 64,
    )
    approved = approve_proposal(
        note_proposal,
        approval_ref="approval://user/obsidian-update-1",
        external_write_allowed=True,
    )

    with pytest.raises(ValueError, match="expected_digest"):
        apply_approved_obsidian_note(
            approved,
            approved["approval"],
            binding=binding(vault),
        )
    assert note.read_bytes() == original


def test_update_rechecks_precondition_immediately_before_atomic_replace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import opl_persona.obsidian_apply as owner

    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "memo.md"
    original = b"# Existing\n"
    raced = b"# Changed concurrently\n"
    note.write_bytes(original)
    note_proposal = proposal(
        operation="update",
        target_path="memo.md",
        body="# Updated",
        expected_digest=digest(original),
    )
    approved = approve_proposal(
        note_proposal,
        approval_ref="approval://user/obsidian-update-race",
        external_write_allowed=True,
    )
    real_render = owner.render_obsidian_note

    def render_after_concurrent_change(payload):
        result = real_render(payload)
        note.write_bytes(raced)
        return result

    monkeypatch.setattr(owner, "render_obsidian_note", render_after_concurrent_change)
    with pytest.raises(ValueError, match="changed after approval"):
        owner.apply_approved_obsidian_note(
            approved,
            approved["approval"],
            binding=binding(vault),
        )
    assert note.read_bytes() == raced


def test_apply_rejects_tampered_proposal_wrong_binding_and_non_external_approval(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    other = tmp_path / "other"
    vault.mkdir()
    other.mkdir()
    note_proposal = proposal(
        operation="create",
        target_path="memo.md",
        body="# Memo",
        expected_digest="absent",
    )
    approved = approve_proposal(
        note_proposal,
        approval_ref="approval://user/obsidian-create-2",
        external_write_allowed=True,
    )
    approved["payload"]["body"] = "# Tampered"
    with pytest.raises(ValueError, match="proposal_digest"):
        apply_approved_obsidian_note(
            approved,
            approved["approval"],
            binding=binding(vault),
        )

    not_external = approve_proposal(
        note_proposal,
        approval_ref="approval://user/review-only",
    )
    with pytest.raises(ValueError, match="external_write_allowed"):
        apply_approved_obsidian_note(
            not_external,
            not_external["approval"],
            binding=binding(vault),
        )

    external = approve_proposal(
        note_proposal,
        approval_ref="approval://user/obsidian-create-3",
        external_write_allowed=True,
    )
    wrong_binding = binding_for_resource(
        capability_id="knowledge.documents.v1",
        provider_id="obsidian",
        resource_ref=other.resolve().as_uri(),
        scopes=["notes.read"],
    )
    with pytest.raises(ValueError, match="notes.write"):
        apply_approved_obsidian_note(
            external,
            external["approval"],
            binding=wrong_binding,
        )
    assert not (vault / "memo.md").exists()


def test_apply_rejects_symlink_escape(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    (vault / "Linked").symlink_to(outside, target_is_directory=True)
    note_proposal = proposal(
        operation="create",
        target_path="Linked/memo.md",
        body="# Memo",
        expected_digest="absent",
    )
    approved = approve_proposal(
        note_proposal,
        approval_ref="approval://user/obsidian-create-4",
        external_write_allowed=True,
    )

    with pytest.raises(ValueError, match="symlink"):
        apply_approved_obsidian_note(
            approved,
            approved["approval"],
            binding=binding(vault),
        )
    assert not (outside / "memo.md").exists()
