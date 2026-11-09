"""Actual cross-package source validation; enabled with OPL_FRAMEWORK_ROOT."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from opl_persona.workspace import WorkspaceStore
from opl_persona.knowledge import read_knowledge_source
from opl_persona.bindings import set_resource_binding
from opl_persona.core import build_obsidian_note_proposals
from opl_persona.proposals import ProposalStore


FRAMEWORK = os.environ.get("OPL_FRAMEWORK_ROOT")
pytestmark = pytest.mark.skipif(not FRAMEWORK, reason="OPL_FRAMEWORK_ROOT is required for the real Framework CLI")


@pytest.mark.parametrize("external", [False, True], ids=["workspace-markdown", "external-markdown"])
def test_actual_framework_roundtrip_source_change_and_revocation(tmp_path, monkeypatch, external):
    workspace = tmp_path / "profile"
    source = tmp_path / "external-vault" if external else workspace / "shared" / "memory" / "notes"
    source.mkdir(parents=True)
    note = source / "research.md"
    note.write_text("# Research principle\nKeep evidence and interpretation separate.\n")
    digest = "sha256:" + hashlib.sha256(note.read_bytes()).hexdigest()
    registry_path = workspace / "shared" / "memory" / "sources.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry = {
        "surface_kind": "opl_knowledge_source_registry", "version": "knowledge-source-registry.v2",
        "registry_id": "synthetic.owner", "owner": "synthetic.owner", "sources": [{
            "source_id": "synthetic.notes", "root": str(source), "status": "active", "writable": False,
            "grants": [{"workspace_root": str(workspace), "domains": ["persona"], "write_domains": [],
                        "scope_ids": ["synthetic.research"]}]}],
        "items": [{"surface_kind": "opl_durable_knowledge_item", "version": "durable-knowledge-item.v2",
            "knowledge_id": "synthetic.research.principle", "title": "Research principle", "owner": "synthetic.owner",
            "scope": {"kind": "topic", "id": "synthetic.research"}, "content_kind": "policy",
            "body_ref": {"kind": "source_path", "source_id": "synthetic.notes", "ref": note.name, "sha256": digest},
            "applicability": {"domains": ["persona"], "stages": ["research-writing"]}, "status": "active",
            "reviewed_at": "2026-01-01T00:00:00Z", "next_review_at": "2099-01-01T00:00:00Z",
            "authority_boundary": {"semantic_body_owner": "synthetic.owner", "opl_role": "catalog_recall_and_receipt_projection_only"}}],
    }
    registry_path.write_text(json.dumps(registry))
    (registry_path.parent / "knowledge-bindings.json").write_text(json.dumps({
        "surface_kind": "opl_knowledge_source_bindings", "version": "knowledge-source-bindings.v2",
        "registries": [{"registry_ref": str(registry_path), "source_ids": ["synthetic.notes"], "scope_ids": ["synthetic.research"]}],
    }))
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(workspace))
    monkeypatch.setenv("OPL_STATE_DIR", str(tmp_path / "opl-state"))
    monkeypatch.setenv("PATH", str(Path(FRAMEWORK) / "bin") + os.pathsep + os.environ["PATH"])
    store = WorkspaceStore()
    accepted_source = read_knowledge_source("synthetic.research.principle", store.paths)
    assert accepted_source["content"] == note.read_text()
    assert accepted_source["sha256"] == digest
    candidate = store.update_memory(memory_id="derived", title="Derived research principle", summary="Evidence precedes interpretation.",
        memory_kind="method", person_ids=[], context_ids=["research-writing"], source_refs=["knowledge://synthetic.research.principle"],
        source_versions={"synthetic.research.principle": digest}, expected_digest="absent")
    assert candidate["source_verification"] == {"valid": True, "issues": []}
    store.review_memory(memory_id="derived", status="approved", approval_ref="review://synthetic-owner/accept",
                        expected_digest=candidate["digest"])
    assert store.context("research-writing")["memories"][0]["id"] == "derived"
    # A separately authorized author write does not accept a new knowledge revision.
    set_resource_binding(workspace, binding_id="authoring", capability_id="knowledge.obsidian.v1",
                         provider_id="obsidian", resource_ref=source.as_uri(), scopes=["notes.read", "notes.write"])
    proposals = ProposalStore(store.paths)
    item = proposals.persist_bundle(build_obsidian_note_proposals({
        "operation": "update", "target_path": note.name, "expected_digest": digest,
        "frontmatter": {}, "body": "# Changed principle\nSource requires another review.",
        "links": [], "tags": [], "evidence_refs": ["knowledge://synthetic.research.principle"],
    }))["stored_items"][0]
    identity = {"proposal_id": item["id"], "expected_digest": item["proposal_digest"]}
    proposals.review(**identity, decision="approved", approval_ref="approval://synthetic/review")
    proposals.authorize_obsidian(**identity, binding_id="authoring", approval_ref="approval://synthetic/write", confirmation="confirmed")
    proposals.apply_obsidian(**identity, binding_id="authoring", external_approval_ref="approval://synthetic/write")
    assert "Changed principle" in note.read_text()
    assert json.loads(registry_path.read_text())["items"][0]["body_ref"]["sha256"] == digest
    assert store.context("research-writing")["memories"] == []
    with pytest.raises(ValueError, match="requires current Framework readback"):
        read_knowledge_source("synthetic.research.principle", store.paths)
    # Reverting bytes cannot bypass an explicit source grant withdrawal.
    note.write_text("# Research principle\nKeep evidence and interpretation separate.\n")
    registry["sources"][0]["status"] = "revoked"
    registry_path.write_text(json.dumps(registry))
    revoked = store.context("research-writing")
    assert revoked["memories"] == []
    assert any("revoked" in issue for item in revoked["excluded_knowledge"] for issue in item["issues"])
    with pytest.raises(ValueError, match="requires current Framework readback"):
        read_knowledge_source("synthetic.research.principle", store.paths)
