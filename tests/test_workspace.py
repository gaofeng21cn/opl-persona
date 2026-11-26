import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from opl_persona.app_contributions import ACTION_CONTRACTS, DATA_CONTRACTS, REQUEST_SCHEMA, handle_request
from opl_persona.paths import PersonaPaths
from opl_persona.workspace import CONTEXT_MODES, WorkspaceStore, relay_read


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "profile"))
    monkeypatch.setattr("opl_persona.workspace.verify_knowledge_dependencies", lambda value, paths:
                        {"valid": bool(value), "issues": [] if value else ["missing_source_versions"]})
    return WorkspaceStore()


def person_input(identifier="person:demo"):
    return {"person_id": identifier, "display_name": "Demo researcher", "summary": "Research collaborator",
            "aliases": ["demo@example.test"], "source_refs": ["obsidian://people/demo.md"],
            "source_versions": {"owner.people.demo": "sha256:" + "a" * 64}, "expected_digest": "absent"}


def memory_input(identifier="memory:demo"):
    return {"memory_id": identifier, "title": "Research meeting", "summary": "An evidence-backed relationship summary",
            "memory_kind": "relationship", "person_ids": ["person:demo"], "context_ids": ["academic-mail"],
            "source_refs": ["obsidian://people/demo.md", "website://lab/research"],
            "source_versions": {"owner.research.summary": "sha256:" + "b" * 64}, "expected_digest": "absent"}


def v2_relay_response(ref):
    memory = {"id": "relay-person", "name": "Researcher", "status": "approved",
              "source_refs": ["email-store://demo/source"], "summary": "Prior correspondence",
              "source_currentness": {"status": "current", "checked_at": "2026-11-09T00:00:00Z", "reasons": []}}
    item = memory if ref.endswith("#search") else {
        "id": "relay-person", "name": "Researcher", "summary": memory["summary"],
        "source_refs": memory["source_refs"], "approved_memories": [memory]}
    return {
        "package_id": "opl-relay",
        "ref": ref,
        "kind": "data",
        "state": "ready",
        "data": {
            "items": [item],
            "source_policy": {"source_currentness_checked": True, "only_approved_memory_included": True},
        },
    }


def test_four_working_modes_and_persistent_selection(store):
    contexts = store.list("contexts")
    assert {item["mode"] for item in contexts} == set(CONTEXT_MODES)
    assert all(set(item["label_i18n"]) == {"zh-CN", "en-US"} for item in contexts)
    assert all(set(item["summary_i18n"]) == {"zh-CN", "en-US"} for item in contexts)
    assert all(item["summary_i18n"]["en-US"] == item["summary"] for item in contexts)
    assert all(item["source_refs"] for item in contexts)
    selected = store.select_context("research-writing")
    assert selected["external_write_allowed"] is False
    assert WorkspaceStore().context()["context"]["id"] == "research-writing"
    item = next(item for item in contexts if item["id"] == "research-writing")
    updated = store.update_context(context_id=item["id"], title=item["title"], summary="Updated writing context",
                                   guidance={"language": "English"}, source_refs=["profile://writing"],
                                   source_versions={"owner.writing.policy": "sha256:" + "c" * 64}, expected_digest=item["digest"])
    assert WorkspaceStore().context()["context"]["summary"] == updated["summary"]
    assert updated["summary_i18n"] == {"en-US": "Updated writing context"}
    with pytest.raises(ValueError, match="expected_digest"):
        store.update_context(context_id=item["id"], title=item["title"], summary="Stale edit", guidance={},
                             source_refs=item["source_refs"], source_versions={"owner.writing.policy": "sha256:" + "c" * 64},
                             expected_digest=item["digest"])


def test_existing_default_summaries_gain_locale_metadata_without_overwriting_custom_text(store):
    store.select_context("academic-mail")
    state = json.loads(store.path.read_text())
    for context in state["contexts"]:
        context.pop("summary_i18n")
    state["contexts"][0]["summary"] = "User-authored summary"
    store.path.write_text(json.dumps(state))
    before = store.path.read_bytes()
    contexts = store.list("contexts")
    assert contexts[0]["summary_i18n"] == {}
    assert contexts[0]["source_verification"]["valid"] is False
    assert all(set(item["summary_i18n"]) == {"zh-CN", "en-US"} for item in contexts[1:])
    assert store.path.read_bytes() == before


def test_only_approved_memory_enters_context_and_edit_requires_reapproval(store):
    store.update_person(**person_input())
    memory = store.update_memory(**memory_input())
    assert store.context()["memories"] == []
    approved = store.review_memory(memory_id=memory["id"], status="approved", approval_ref="approval://user/memory",
                                   expected_digest=memory["digest"])
    context = WorkspaceStore().context()
    assert context["memories"][0]["id"] == memory["id"]
    assert context["people"][0]["id"] == "person:demo"
    assert "website://lab/research" in context["source_refs"]
    assert store.context("research-writing")["memories"] == []
    edited = store.update_memory(**(memory_input() | {"summary": "Revised relationship", "expected_digest": approved["digest"]}))
    assert edited["status"] == "candidate" and edited["review"] is None
    with pytest.raises(ValueError, match="expected_digest"):
        store.review_memory(memory_id=memory["id"], status="approved", approval_ref="approval://user/stale",
                            expected_digest=approved["digest"])
    forgotten = store.review_memory(memory_id=memory["id"], status="forgotten", approval_ref="approval://user/forget",
                                    expected_digest=edited["digest"])
    assert forgotten["source_refs"]
    assert store.context()["memories"] == []


def test_missing_provenance_and_unknown_relationship_fail_closed(store):
    with pytest.raises(ValueError, match="source_refs"):
        store.update_person(**(person_input() | {"source_refs": []}))
    with pytest.raises(ValueError, match="unknown person_ids"):
        store.update_memory(**memory_input())
    assert not store.path.exists()


@pytest.mark.parametrize("collection", ["people", "search"])
def test_relay_uses_exact_public_read_abi_and_never_copies_state(store, monkeypatch, collection):
    ref = f"personal.memory.v1#{collection}"
    captured = []

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def call(self, method, params):
            captured.append((method, params))
            return v2_relay_response(ref)

    monkeypatch.setattr("opl_persona.workspace.connect", lambda: FakeClient())
    evidence = store.relay(collection, query="Researcher", entity="relay-person")
    assert evidence == {"state": "ready", "package_id": "opl-relay", "ref": ref,
                        "source_policy": {"source_currentness_checked": True, "only_approved_memory_included": True},
                        "items": v2_relay_response(ref)["data"]["items"]}
    method, params = captured[0]
    assert method == "app.contribution.read"
    expected_input = {"query": "Researcher"}
    if collection == "search":
        expected_input["entity"] = "relay-person"
    assert params == {"package_id": "opl-relay", "ref": ref, "input": expected_input}
    assert not store.path.exists()
    with pytest.raises(ValueError):
        relay_read("communications.mail.v1#send", {}, store.paths)


@pytest.mark.parametrize(("mutation_kind", "mutated"), [
    ("package_id", {"package_id": "opl-persona"}),
    ("ref", {"ref": "personal.memory.v1#search"}),
    ("ok_false", {"ok": False}),
    ("kind_action", {"kind": "action"}),
    ("state_unavailable", {"state": "unavailable"}),
    ("data_none", {"data": None}),
    ("data_empty", {"data": {}}),
    ("items_dict", {"data": {"items": {}}}),
    ("policy_empty", {"data": {"items": [], "source_policy": {}}}),
    ("policy_partial", {"data": {"items": [], "source_policy": {"source_currentness_checked": True}}}),
    ("v1_wrapper", {"opl_app_contribution": {"package_id": "opl-relay"}}),
    ("non_dict", None),
])
def test_relay_framework_and_package_identity_must_match_before_reading_data(store, monkeypatch, mutation_kind, mutated):
    del mutation_kind
    ref = "personal.memory.v1#people"
    payload = v2_relay_response(ref)
    if mutated is None:
        response = "not-an-object"
    elif "opl_app_contribution" in mutated:
        response = mutated
    else:
        response = {**payload, **mutated}

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def call(self, method, params):
            return response

    monkeypatch.setattr("opl_persona.workspace.connect", lambda: FakeClient())
    assert relay_read(ref, {}, store.paths) == {
        "state": "unavailable", "items": [], "package_id": "opl-relay", "ref": ref,
        "reason": "Relay public memory ABI unavailable"}
    assert not store.path.exists()


@pytest.mark.parametrize("collection", ["people", "search"])
@pytest.mark.parametrize("mutation", [
    {"status": "candidate"}, {"source_currentness": None},
    {"source_currentness": {"status": "needs_review", "checked_at": "2026-11-09T00:00:00Z", "reasons": ["source_revision_changed"]}},
    {"source_currentness": {"status": "current", "checked_at": "", "reasons": []}},
])
def test_relay_rejects_stale_or_unverified_approved_summaries(store, monkeypatch, collection, mutation):
    ref = f"personal.memory.v1#{collection}"
    wire = v2_relay_response(ref)
    item = wire["data"]["items"][0]
    memory = item if collection == "search" else item["approved_memories"][0]
    memory.update(mutation)

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def call(self, method, params):
            return wire

    monkeypatch.setattr("opl_persona.workspace.connect", lambda: FakeClient())
    result = relay_read(ref, {}, store.paths)
    assert result["state"] == "ready"
    if collection == "search":
        assert result["items"] == []
    else:
        assert result["items"][0]["summary"] == ""
        assert result["items"][0]["source_refs"] == []
        assert result["items"][0]["approved_memories"] == []


def test_relay_rejects_empty_and_broken_client(store, monkeypatch):
    ref = "personal.memory.v1#people"

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def call(self, method, params):
            return {}

    monkeypatch.setattr("opl_persona.workspace.connect", lambda: FakeClient())
    assert relay_read(ref, {}, store.paths)["state"] == "unavailable"
    assert not store.path.exists()


def test_management_default_candidates_approved_and_forgotten_explicit(store, monkeypatch):
    monkeypatch.setattr("opl_persona.workspace.relay_read", lambda ref, value, paths: {
        "state": "unavailable", "items": [], "ref": ref, "package_id": "opl-relay"})
    store.update_person(**person_input())
    candidate = store.update_memory(**memory_input())
    second = store.update_memory(**memory_input("memory:second"))
    store.review_memory(memory_id=second["id"], status="forgotten", approval_ref="approval://user/forget", expected_digest=second["digest"])
    def read(value):
        code, response = handle_request({"schema_version": REQUEST_SCHEMA, "operation": "read", "ref": "personal.memory.v1#memories", "input": value})
        assert code == 0
        return response["result"]["data"]
    assert [item["id"] for item in read({})["items"]] == [candidate["id"]]
    assert len(read({"status": "all"})["items"]) == 2
    row = read({})["items"][0]
    assert row["actions"][1]["input"]["expected_digest"] == candidate["digest"]
    assert row["actions"][1]["label_i18n"] == {"zh-CN": "确认记忆", "en-US": "Confirm memory"}
    assert row["actions"][2]["label_i18n"] == {"zh-CN": "忘记记忆", "en-US": "Forget memory"}


def test_every_read_has_forms_matching_descriptor_commands(store, monkeypatch):
    monkeypatch.setattr("opl_persona.workspace.relay_read", lambda ref, value, paths: {
        "state": "ready", "items": [], "ref": ref, "package_id": "opl-relay"})
    root = Path(__file__).parents[1]
    descriptor = json.loads((root / "opl-package.json").read_text())
    for view in descriptor["ui"]["declarative"]["views"]:
        ref = view["data_ref"]
        assert ref in DATA_CONTRACTS
        code, response = handle_request({"schema_version": REQUEST_SCHEMA, "operation": "read", "ref": ref, "input": {}})
        assert code == 0
        result = response["result"]
        assert result["kind"] == "data" and result["state"] == "ready"
        forms = result["data"]["command_inputs"]
        view_actions = {action["action_ref"] for action in view.get("actions", [])}
        assert set(forms) == view_actions
        for action_ref, form in forms.items():
            assert form["input_schema"] == ACTION_CONTRACTS[action_ref]["input"]
            assert isinstance(form["defaults"], dict)
        for item in result["data"]["items"]:
            assert {action["action_ref"] for action in item.get("actions", [])} <= set(forms)


def test_parallel_cli_updates_do_not_lose_people_or_inbox_proposals(store):
    root = Path(__file__).parents[1]
    environment = os.environ | {"PYTHONPATH": str(root / "runtime")}
    requests = []
    for number in range(4):
        requests.extend([
            ("personal.memory.v1#person.update", person_input(f"person:{number}")),
            ("personal.inbox.v1#capture.propose", {"capture_id": f"capture:{number}", "item_kind": "note", "title": f"Note {number}",
                "summary": "Synthetic summary", "source_refs": [f"source://{number}"]}),
        ])
    running = []
    for ref, value in requests:
        process = subprocess.Popen([sys.executable, "-m", "opl_persona", "app-contribution"], env=environment,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process.stdin.write(json.dumps({"schema_version": REQUEST_SCHEMA, "operation": "execute", "ref": ref, "input": value}))
        process.stdin.close()
        process.stdin = None
        running.append(process)
    for process in running:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, (stdout, stderr)
    assert len(store.list("people")) == 4
    from opl_persona.proposals import ProposalStore
    from opl_persona.inbox import InboxStore
    assert len(ProposalStore().list()) == 4
    assert len(InboxStore.from_paths(PersonaPaths.resolve()).list()) == 4
    assert not list(store.paths.data_root.rglob(".persona-*.tmp"))


def test_windows_lock_and_atomic_json_without_posix_imports(store, monkeypatch):
    import types
    import opl_persona.workspace as workspace
    calls = []
    fake_os = types.SimpleNamespace(**vars(os))
    fake_os.name = "nt"
    fake_os.open = lambda *args, **kwargs: pytest.fail("Windows must not open directories for fsync")
    fake_msvcrt = types.SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2,
                                       locking=lambda fd, mode, size: calls.append((mode, size)))
    monkeypatch.setattr(workspace, "os", fake_os)
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    with workspace.workspace_lock(store.paths):
        workspace.atomic_json(store.path, {"synthetic": True})
    assert calls == [(1, 1), (2, 1)]
    assert json.loads(store.path.read_text()) == {"synthetic": True}
