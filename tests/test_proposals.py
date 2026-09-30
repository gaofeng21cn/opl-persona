import copy
import json

import pytest

from opl_persona.app_contributions import REQUEST_SCHEMA, handle_request
from opl_persona.bindings import set_resource_binding
from opl_persona.core import build_inbox_capture_proposals, build_obsidian_note_proposals
from opl_persona.inbox import InboxStore
from opl_persona.paths import PersonaPaths
from opl_persona.proposals import ProposalStore


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "profile"))
    return ProposalStore()


def note_input():
    return {"operation": "create", "target_path": "Research/new-note.md", "frontmatter": {"title": "New note"},
            "body": "# New note\n\nSynthetic evidence-backed content.", "links": [], "tags": ["research"],
            "evidence_refs": ["source://research/1"], "expected_digest": "absent"}


def capture_input():
    return {"capture_id": "capture:demo", "item_kind": "note", "title": "Synthetic note", "summary": "Bounded summary",
            "source_refs": ["source://research/1"]}


def propose(store, value=None):
    bundle = store.persist_bundle(build_obsidian_note_proposals(value or note_input()))
    return bundle["stored_items"][0]


@pytest.mark.parametrize("note_title,expected_title", [
    ("  Evidence-backed memo  ", "Evidence-backed memo"),
    ("  ", "Research/new-note.md"),
    (42, "Research/new-note.md"),
    (None, "Research/new-note.md"),
])
def test_note_presentation_uses_frontmatter_title_and_target_path(store, note_title, expected_title):
    item = propose(store, note_input() | {"frontmatter": {"title": note_title}})
    assert item["title"] == expected_title
    assert item["summary"] == "Research/new-note.md"
    assert ProposalStore().inspect(item["id"])["title"] == expected_title
    assert item["proposal"]["payload"]["body"] == note_input()["body"]


def review_input(item, approval_ref="approval://user/review"):
    return {"proposal_id": item["id"], "expected_digest": item["proposal_digest"], "approval_ref": approval_ref}


def binding(store, vault, identifier="knowledge"):
    vault.mkdir(parents=True, exist_ok=True)
    return set_resource_binding(store.paths.workspace, binding_id=identifier, capability_id="knowledge.obsidian.v1",
                                provider_id="obsidian", resource_ref=vault.as_uri(), scopes=["notes.read", "notes.write"])


def test_persistence_real_inspect_approve_and_reject(store):
    item = propose(store)
    assert ProposalStore().inspect(item["id"])["proposal"] == item["proposal"]
    with pytest.raises(ValueError, match="expected_digest"):
        store.review(**(review_input(item) | {"expected_digest": "sha256:" + "0" * 64}), decision="approved")
    approved = store.review(**review_input(item), decision="approved")
    assert approved["status"] == "approved"
    assert approved["approval"]["external_write_allowed"] is False
    assert approved["approval"]["proposal_digest"] == item["proposal_digest"]
    assert ProposalStore().inspect(item["id"])["approval"] == approved["approval"]
    assert store.review(**review_input(item), decision="approved") == approved
    with pytest.raises(ValueError, match="already reviewed"):
        store.review(**review_input(item), decision="rejected")
    other = propose(store, note_input() | {"target_path": "Research/other.md"})
    rejected = store.review(**review_input(other), decision="rejected")
    assert ProposalStore().inspect(other["id"])["status"] == "rejected"
    assert rejected["approval"]["external_write_allowed"] is False


def test_propose_persists_and_stages_capture_idempotently(store):
    bundle = build_inbox_capture_proposals(capture_input())
    result = store.persist_bundle(bundle)
    assert len(result["stored_items"]) == 1
    store.persist_bundle(bundle)
    assert len(store.list()) == 1
    assert len(InboxStore.from_paths(PersonaPaths.resolve()).list()) == 1
    assert all(path.is_relative_to(store.paths.data_root) for path in store.paths.data_root.rglob("*.json"))
    bad = copy.deepcopy(bundle)
    bad["proposals"][0]["source_refs"] = []
    with pytest.raises(ValueError, match="source_refs"):
        store.persist_bundle(bad)


def test_persisted_digest_tampering_fails_closed(store):
    item = propose(store)
    raw = json.loads(store.path.read_text())
    raw["items"][0]["proposal"]["payload"]["body"] = "Changed without approval"
    store.path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="digest mismatch"):
        store.inspect(item["id"])


def test_authorize_requires_distinct_confirmation_resource_and_note(store, tmp_path):
    item = propose(store)
    binding(store, tmp_path / "vault")
    params = {"proposal_id": item["id"], "expected_digest": item["proposal_digest"], "binding_id": "knowledge",
              "approval_ref": "approval://user/external", "confirmation": "confirmed"}
    with pytest.raises(ValueError, match="approved Obsidian"):
        store.authorize_obsidian(**params)
    store.review(**review_input(item), decision="approved")
    with pytest.raises(ValueError, match="explicit confirmation"):
        store.authorize_obsidian(**(params | {"confirmation": "pending"}))
    with pytest.raises(ValueError, match="separate"):
        store.authorize_obsidian(**(params | {"approval_ref": "approval://user/review"}))
    authorized = store.authorize_obsidian(**params)
    assert authorized["approval"]["external_write_allowed"] is False
    external = authorized["external_approval"]
    assert external["external_write_allowed"] is True
    assert external["scope"] == "notes.write" and external["binding_id"] == "knowledge"
    assert not (tmp_path / "vault/Research/new-note.md").exists()


def test_scope_bound_external_apply_returns_persistent_authority_readback(store, tmp_path):
    vault = tmp_path / "vault"
    item = propose(store)
    binding(store, vault)
    store.review(**review_input(item), decision="approved")
    identity = {"proposal_id": item["id"], "expected_digest": item["proposal_digest"], "binding_id": "knowledge"}
    with pytest.raises(ValueError, match="exactly one"):
        store.apply_obsidian(**identity)
    store.authorize_obsidian(**identity, approval_ref="approval://user/external", confirmation="confirmed")
    applied = store.apply_obsidian(**identity, external_approval_ref="approval://user/external")
    receipt = applied["receipt"]
    assert applied["status"] == "applied"
    assert receipt["readback"]["matches_written_bytes"] is True
    assert receipt["readback"]["bytes"] == len((vault / "Research/new-note.md").read_bytes())
    assert receipt["authority_ref"].startswith(vault.as_uri())
    assert ProposalStore().inspect(item["id"])["receipt"] == receipt
    with pytest.raises(ValueError, match="already applied"):
        store.apply_obsidian(**identity, external_approval_ref="approval://user/external")


def test_stale_target_and_binding_reassignment_do_not_write(store, tmp_path):
    vault = tmp_path / "vault"
    item = propose(store)
    binding(store, vault)
    store.review(**review_input(item), decision="approved")
    identity = {"proposal_id": item["id"], "expected_digest": item["proposal_digest"], "binding_id": "knowledge"}
    store.authorize_obsidian(**identity, approval_ref="approval://user/external", confirmation="confirmed")
    binding(store, tmp_path / "other-vault")
    with pytest.raises(ValueError, match="exact Obsidian resource"):
        store.apply_obsidian(**identity, external_approval_ref="approval://user/external")
    binding(store, vault)
    target = vault / "Research/new-note.md"
    target.parent.mkdir()
    target.write_text("User content changed after approval")
    with pytest.raises(ValueError, match="absent target"):
        store.apply_obsidian(**identity, external_approval_ref="approval://user/external")
    assert target.read_text() == "User content changed after approval"
    assert store.inspect(item["id"])["receipt"] is None


def test_proposal_read_model_contains_review_and_external_forms(store, tmp_path):
    item = propose(store)
    binding(store, tmp_path / "vault")
    store.review(**review_input(item), decision="approved")
    code, response = handle_request({"schema_version": REQUEST_SCHEMA, "operation": "read",
                                     "ref": "personal.context.v1#proposals", "input": {}})
    assert code == 0
    data = response["result"]["data"]
    assert data["bindings"][0]["binding_id"] == "knowledge"
    row = data["items"][0]
    assert set(("id", "title", "summary", "status", "source_refs", "proposal_digest", "proposal", "approval", "receipt")) <= set(row)
    authorize = next(action for action in row["actions"] if action["action_ref"].endswith("note.authorize"))
    assert authorize["input"]["binding_id"] == "knowledge"
    assert "confirmation" not in authorize["input"]
    assert "external_approval" not in row
    assert not any(action["action_ref"].endswith("note.apply") for action in row["actions"])


def test_app_workflow_is_persistent_and_rejects_foreign_actions(store):
    def execute(ref, value):
        return handle_request({"schema_version": REQUEST_SCHEMA, "operation": "execute", "ref": ref, "input": value})
    code, response = execute("knowledge.obsidian.v1#note.propose", note_input())
    assert code == 0
    item = response["result"]["proposal_bundle"]["stored_items"][0]
    code, response = execute("personal.context.v1#proposal.inspect", {"proposal_id": item["id"]})
    assert code == 0 and response["result"]["item"]["proposal_digest"] == item["proposal_digest"]
    code, response = execute("personal.context.v1#proposal.reject", review_input(item))
    assert code == 0 and response["result"]["item"]["status"] == "rejected"
    code, response = execute("communications.mail.v1#send", {"proposal_id": item["id"]})
    assert code == 2 and response["ok"] is False
