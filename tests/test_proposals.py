import copy
import hashlib
import json

import pytest

from opl_persona.app_contributions import REQUEST_SCHEMA, handle_request
from opl_persona.bindings import set_resource_binding
from opl_persona.core import (
    build_inbox_capture_proposals,
    build_memo_proposals,
    build_obsidian_note_proposals,
    build_publication_proposals,
)
from opl_persona.inbox import InboxStore
from opl_persona.paths import PersonaPaths
from opl_persona.obsidian_apply import render_obsidian_note
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


def read_proposals(value=None):
    code, response = handle_request({"schema_version": REQUEST_SCHEMA, "operation": "read",
                                     "ref": "personal.context.v1#proposals", "input": value or {}})
    assert code == 0, response
    return response["result"]["data"]


def update_note(store, before):
    return propose(store, note_input() | {"operation": "update",
        "expected_digest": "sha256:" + hashlib.sha256(before).hexdigest()})


def test_note_preview_shows_actual_rendered_after_and_unknown_before_without_granting_authority(store):
    item = propose(store)
    persisted = store.path.read_bytes()
    data = read_proposals()
    row = data["items"][0]
    assert row["preview"] == {
        "title": "New note", "target": "Research/new-note.md", "body": note_input()["body"],
        "before": None, "after": render_obsidian_note(item["proposal"]["payload"]).decode("utf-8"),
        "evidence_refs": ["source://research/1"],
    }
    assert row["approval"]["external_write_allowed"] is False
    assert "external_approval" not in row
    assert store.path.read_bytes() == persisted
    for action in row["actions"][1:]:
        assert action["input"] == {"proposal_id": item["id"], "expected_digest": item["proposal_digest"]}
    assert not any(action["action_ref"].endswith(("approve", "reject", "authorize", "apply", "inspect"))
                   for action in data["collection_actions"])
    create = next(action for action in data["collection_actions"] if action["action_ref"].endswith("note.propose"))
    assert create["input"] == {"operation": "create", "expected_digest": "absent", "frontmatter": {}, "links": [], "tags": []}


def test_update_preview_reads_only_exact_safe_bound_before_and_never_persists_it(store, tmp_path):
    before = b"---\r\ntitle: Old note\r\n---\r\n\r\nOriginal bound content.\r\n"
    item = update_note(store, before)
    vault = tmp_path / "vault"
    binding(store, vault)
    target = vault / "Research/new-note.md"
    target.parent.mkdir()
    target.write_bytes(before)
    persisted = store.path.read_bytes()
    binding_bytes = (store.paths.data_root / "resource-bindings.json").read_bytes()
    row = read_proposals()["items"][0]
    assert row["preview"]["before"] == before.decode("utf-8")
    assert row["preview"]["after"] == render_obsidian_note(item["proposal"]["payload"]).decode("utf-8")
    assert target.read_bytes() == before
    assert store.path.read_bytes() == persisted
    assert (store.paths.data_root / "resource-bindings.json").read_bytes() == binding_bytes
    assert store.inspect(item["id"])["status"] == "pending"


@pytest.mark.parametrize("reason", ["unbound", "write_only", "missing", "stale", "symlink", "parent_symlink", "binary"])
def test_unavailable_or_unsafe_before_is_explicit_null_and_does_not_suppress_after(store, tmp_path, reason):
    before = b"Original synthetic content.\n" if reason != "binary" else b"\xff\xfe\x00"
    item = update_note(store, before)
    vault = tmp_path / "vault"
    vault.mkdir()
    if reason != "unbound":
        set_resource_binding(store.paths.workspace, binding_id="knowledge", capability_id="knowledge.obsidian.v1",
                             provider_id="obsidian", resource_ref=vault.as_uri(),
                             scopes=["notes.write"] if reason == "write_only" else ["notes.read"])
    outside = tmp_path / "outside.md"
    outside.write_bytes(before)
    target = vault / "Research/new-note.md"
    if reason == "parent_symlink":
        directory = tmp_path / "outside"
        directory.mkdir()
        (directory / "new-note.md").write_bytes(before)
        target.parent.symlink_to(directory, target_is_directory=True)
    else:
        target.parent.mkdir()
        if reason == "symlink":
            target.symlink_to(outside)
        elif reason != "missing":
            target.write_bytes(b"Changed authority content" if reason == "stale" else before)
    persisted = store.path.read_bytes()
    preview = read_proposals()["items"][0]["preview"]
    assert preview["before"] is None
    assert preview["after"] == render_obsidian_note(item["proposal"]["payload"]).decode("utf-8")
    assert store.path.read_bytes() == persisted
    assert outside.read_bytes() == before


def test_preview_uses_exact_authorized_binding_and_never_guesses_between_multiple_resources(store, tmp_path):
    before = b"Original synthetic note.\n"
    item = update_note(store, before)
    vault = tmp_path / "vault"
    binding(store, vault)
    binding(store, tmp_path / "other-vault", "other")
    target = vault / "Research/new-note.md"
    target.parent.mkdir()
    target.write_bytes(before)
    assert read_proposals()["items"][0]["preview"]["before"] is None
    store.review(**review_input(item), decision="approved")
    identity = {"proposal_id": item["id"], "expected_digest": item["proposal_digest"], "binding_id": "knowledge"}
    store.authorize_obsidian(**identity, approval_ref="approval://user/external", confirmation="confirmed")
    row = read_proposals()["items"][0]
    assert row["preview"]["before"] == before.decode("utf-8")
    apply = next(action for action in row["actions"] if action["action_ref"].endswith("note.apply"))
    assert apply["input"] == identity | {"external_approval_ref": "approval://user/external"}
    rebound = tmp_path / "rebound"
    binding(store, rebound)
    (rebound / "Research").mkdir()
    (rebound / "Research/new-note.md").write_bytes(before)
    assert read_proposals()["items"][0]["preview"]["before"] is None
    assert target.read_bytes() == before


def test_non_note_previews_expose_semantic_payload_and_evidence_not_invented_before(store):
    store.persist_bundle(build_inbox_capture_proposals(capture_input()))
    store.persist_bundle(build_publication_proposals({"publication_id": "publication:synthetic", "title": "Synthetic paper",
        "abstract": "The proposed abstract.", "venue": "Synthetic journal", "source_refs": ["source://paper/1"]}))
    store.persist_bundle(build_memo_proposals({"memo_id": "memo:synthetic", "title": "Synthetic memo",
        "body": "# The proposed memo", "source_refs": ["source://memo/1"]}))
    rows = read_proposals()["items"]
    assert len(rows) == 5
    for row in rows:
        preview = row["preview"]
        assert preview["target"] == row["proposal"]["target"]
        assert preview["evidence_refs"] == row["source_refs"]
        assert preview["before"] is None
        assert preview["after"] == row["proposal"]["payload"]
        assert preview["body"] in {"Bounded summary", "The proposed abstract.", "# The proposed memo"}


def test_proposal_search_filters_the_complete_payload_collection_before_paging_and_previews_only_the_page(store, monkeypatch):
    proposals = [build_obsidian_note_proposals(note_input() | {"target_path": f"Research/note-{index}.md",
        "body": "# Late searchable body" if index >= 60 else "# Earlier body"})["proposals"][0] for index in range(65)]
    stored = store.persist_bundle({"proposals": proposals})["stored_items"]
    store.review(**review_input(stored[60]), decision="rejected")
    calls = []
    original = ProposalStore.preview
    def preview(self, item):
        calls.append(item["id"])
        return original(self, item)
    monkeypatch.setattr(ProposalStore, "preview", preview)
    data = read_proposals({"query": "LATE SEARCHABLE", "status": "pending", "offset": 1, "limit": 2})
    assert [row["id"] for row in data["items"]] == [stored[62]["id"], stored[63]["id"]]
    assert data["pagination"] == {"offset": 1, "limit": 2, "total": 4, "has_more": True}
    assert calls == [stored[62]["id"], stored[63]["id"]]
    calls.clear()
    empty = read_proposals({"query": "Late searchable", "status": "pending", "offset": 4, "limit": 2})
    assert empty["items"] == [] and empty["pagination"]["total"] == 4 and not empty["pagination"]["has_more"]
    assert calls == []
    assert empty["collection_actions"] == data["collection_actions"]
