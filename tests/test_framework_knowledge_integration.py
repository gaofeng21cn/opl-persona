"""Actual cross-package source validation; enabled with OPL_FRAMEWORK_ROOT."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from opl_persona.workspace import WorkspaceStore
from opl_persona.knowledge import read_knowledge_source
from opl_persona.bindings import set_resource_binding
from opl_persona.core import build_obsidian_note_proposals
from opl_persona.proposals import ProposalStore


LAUNCHER = Path(__file__).parents[1] / "bin/opl-persona"


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
            "source_id": "synthetic.notes", "root": str(source), "status": "active", "writable": True,
            "grants": [{"workspace_root": str(workspace), "domains": ["persona"], "write_domains": ["persona"],
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
    # An exact owner-reviewed write updates both canonical body and accepted revision.
    set_resource_binding(workspace, binding_id="authoring", capability_id="knowledge.obsidian.v1",
                         provider_id="obsidian", resource_ref=source.as_uri(), scopes=["notes.read", "notes.write"])
    proposals = ProposalStore(store.paths)
    writeback = {
        "knowledge_id": "synthetic.research.principle",
        "target_scope": {"kind": "topic", "id": "synthetic.research"},
        "content_kind": "policy",
        "proposed_rule_or_mechanism": "Separate evidence from interpretation",
        "evidence_class": "synthetic",
        "review_requirement": "owner review",
    }
    note_change = {
        "operation": "update", "target_path": note.name, "expected_digest": digest,
        "frontmatter": {}, "body": "# Changed principle\nSource requires another review.\nClose conference follow-ups with よろしくお願いいたします。",
        "links": [], "tags": [], "evidence_refs": ["knowledge://synthetic.research.principle"],
        "knowledge_writeback": writeback,
    }
    if external:
        (store.paths.data_root / "knowledge-inputs.json").write_text(json.dumps({
            "schema_version": "opl-persona-knowledge-inputs.v1",
            "roles": {"mail_policy": [writeback["knowledge_id"]]},
        }))
        context_input = {"purpose": "mail-drafting"}
        feedback = {
            "draft_ref": "relay-draft://synthetic/reply?revision=1",
            "draft_fingerprint": "sha256:" + "1" * 64,
            "final_ref": "relay-draft://synthetic/reply?revision=2",
            "final_fingerprint": "sha256:" + "2" * 64,
        }

        def cli(*arguments, payload):
            result = subprocess.run([str(LAUNCHER), "--json", *arguments, "--input", "-"],
                                    input=json.dumps(payload), text=True, capture_output=True, timeout=45)
            assert result.returncode == 0, result.stdout or result.stderr
            return json.loads(result.stdout)["result"]

        baseline = cli("context", "list", payload=context_input)["data"]["active_context"]
        assert baseline["drafting_policy"]["source_versions"] == {writeback["knowledge_id"]: digest}
        assert not baseline["external_write_allowed"]
        once = cli("proposal", "mail-feedback", payload=feedback | {"disposition": "this-draft"})
        assert once["status"] == "this-draft"
        assert proposals.list() == []
        reusable = cli("proposal", "mail-feedback", payload=feedback | {
            "disposition": "reuse",
            "note": {key: note_change[key] for key in ("target_path", "body", "expected_digest", "knowledge_writeback")},
        })
        item = reusable["proposal_bundle"]["stored_items"][0]
        assert item["status"] == "pending"
        assert item["proposal"]["payload"]["draft_feedback"] == feedback
        pending = cli("context", "list", payload=context_input)["data"]["active_context"]
        assert pending["drafting_policy"] == baseline["drafting_policy"]
    else:
        item = proposals.persist_bundle(build_obsidian_note_proposals(note_change))["stored_items"][0]
    identity = {"proposal_id": item["id"], "expected_digest": item["proposal_digest"]}
    proposals.review(**identity, decision="approved", approval_ref="approval://synthetic/review")
    proposals.authorize_obsidian(**identity, binding_id="authoring", approval_ref="approval://synthetic/write", confirmation="confirmed", knowledge_review={"reviewer": "synthetic.owner", "reviewed_at": "2026-11-09T00:00:00Z", "next_review_at": "2099-01-01T00:00:00Z"})
    proposals.apply_obsidian(**identity, binding_id="authoring", external_approval_ref="approval://synthetic/write")
    assert "Changed principle" in note.read_text()
    accepted = "sha256:" + hashlib.sha256(note.read_bytes()).hexdigest()
    assert json.loads(registry_path.read_text())["items"][0]["body_ref"]["sha256"] == accepted
    if external:
        recalled = cli("context", "list", payload=context_input)["data"]["active_context"]["drafting_policy"]
        assert recalled["source_versions"] == {writeback["knowledge_id"]: accepted}
        assert recalled["documents"][0]["content"] == note.read_text()
        assert "よろしくお願いいたします。" in recalled["documents"][0]["content"]
    assert store.context("research-writing")["memories"] == []
    assert read_knowledge_source("synthetic.research.principle", store.paths)["content"] == note.read_text()
    # Reverting bytes cannot bypass an explicit source grant withdrawal.
    note.write_text("# Research principle\nKeep evidence and interpretation separate.\n")
    registry["sources"][0]["status"] = "revoked"
    registry_path.write_text(json.dumps(registry))
    revoked = store.context("research-writing")
    assert revoked["memories"] == []
    assert any("revoked" in issue for item in revoked["excluded_knowledge"] for issue in item["issues"])
    with pytest.raises(ValueError, match="requires current Framework readback"):
        read_knowledge_source("synthetic.research.principle", store.paths)
