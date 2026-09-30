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
    return WorkspaceStore()


def person_input(identifier="person:demo"):
    return {"person_id": identifier, "display_name": "Demo researcher", "summary": "Research collaborator",
            "aliases": ["demo@example.test"], "source_refs": ["obsidian://people/demo.md"], "expected_digest": "absent"}


def memory_input(identifier="memory:demo"):
    return {"memory_id": identifier, "title": "Research meeting", "summary": "An evidence-backed relationship summary",
            "memory_kind": "relationship", "person_ids": ["person:demo"], "context_ids": ["academic-mail"],
            "source_refs": ["obsidian://people/demo.md", "website://lab/research"], "expected_digest": "absent"}


def framework_relay_response(ref):
    return {"opl_app_contribution": {
        "surface_kind": "opl_app_package_contribution.v1", "package_id": "opl-relay",
        "ref": ref, "operation": "read", "confirmation_required": False,
        "response": {"schema_version": "opl-package-app-contribution-response.v1", "ok": True,
            "ref": ref, "operation": "read", "result": {
                "kind": "data", "state": "ready", "data": {"items": [{"id": "relay-person", "name": "Researcher",
                    "source_refs": ["email-store://demo/source"], "summary": "Prior correspondence"}]}}}}}


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
                                   guidance={"language": "English"}, source_refs=["profile://writing"], expected_digest=item["digest"])
    assert WorkspaceStore().context()["context"]["summary"] == updated["summary"]
    assert updated["summary_i18n"] == {"en-US": "Updated writing context"}
    with pytest.raises(ValueError, match="expected_digest"):
        store.update_context(context_id=item["id"], title=item["title"], summary="Stale edit", guidance={},
                             source_refs=item["source_refs"], expected_digest=item["digest"])


def test_existing_default_summaries_gain_locale_metadata_without_overwriting_custom_text(store):
    store.select_context("academic-mail")
    state = json.loads(store.path.read_text())
    for context in state["contexts"]:
        context.pop("summary_i18n")
    state["contexts"][0]["summary"] = "User-authored summary"
    store.path.write_text(json.dumps(state))
    before = store.path.read_bytes()
    contexts = store.list("contexts")
    assert contexts[0]["summary_i18n"] == {"en-US": "User-authored summary"}
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
    def read(argv, **kwargs):
        captured.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, json.dumps(framework_relay_response(ref)), "")
    monkeypatch.setattr(subprocess, "run", read)
    evidence = store.relay(collection, query="Researcher", entity="relay-person")
    assert evidence == {"state": "ready", "package_id": "opl-relay", "ref": ref,
                        "items": framework_relay_response(ref)["opl_app_contribution"]["response"]["result"]["data"]["items"]}
    argv, kwargs = captured[0]
    assert argv[:7] == ["opl", "app", "contribution", "read", "--package-id", "opl-relay", "--ref"]
    assert argv[7] == ref
    expected_input = {"query": "Researcher"}
    if collection == "search":
        expected_input["entity"] = "relay-person"
    assert json.loads(argv[argv.index("--input") + 1]) == expected_input
    assert kwargs["env"]["OPL_PROFILE_WORKSPACE"] == str(store.paths.workspace)
    assert not store.path.exists()
    with pytest.raises(ValueError):
        relay_read("communications.mail.v1#send", {}, store.paths)


@pytest.mark.parametrize(("section", "field", "value"), [
    ("outer", "surface_kind", "opl_app_package_contribution.v2"),
    ("outer", "package_id", "opl-persona"),
    ("outer", "ref", "personal.memory.v1#search"),
    ("outer", "operation", "execute"),
    ("outer", "response", None),
    ("inner", "schema_version", "opl-package-app-contribution-response.v2"),
    ("inner", "ok", False),
    ("inner", "ok", 1),
    ("inner", "ref", "personal.memory.v1#search"),
    ("inner", "operation", "execute"),
    ("inner", "result", None),
    ("result", "kind", "action"),
    ("result", "state", "unavailable"),
    ("result", "data", None),
    ("result", "data", {}),
    ("result", "data", {"items": {}}),
])
def test_relay_framework_and_package_identity_must_match_before_reading_data(store, monkeypatch, section, field, value):
    ref = "personal.memory.v1#people"
    wire = framework_relay_response(ref)
    outer = wire["opl_app_contribution"]
    inner = outer["response"]
    {"outer": outer, "inner": inner, "result": inner["result"]}[section][field] = value
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs:
                        subprocess.CompletedProcess(argv, 0, json.dumps(wire), "private diagnostics"))
    assert relay_read(ref, {}, store.paths) == {
        "state": "unavailable", "items": [], "package_id": "opl-relay", "ref": ref,
        "reason": "Relay public memory ABI unavailable"}
    assert not store.path.exists()


@pytest.mark.parametrize("shape", ["data", "package", "root-result", "wrapped-framework", "missing-outer", "null-outer"])
def test_relay_rejects_direct_responses_and_non_framework_wrappers(store, monkeypatch, shape):
    ref = "personal.memory.v1#people"
    wire = framework_relay_response(ref)
    response = wire["opl_app_contribution"]["response"]
    invalid_wire = {"data": response["result"], "package": response, "root-result": {"result": response},
                    "wrapped-framework": {"result": wire}, "missing-outer": {},
                    "null-outer": {"opl_app_contribution": None}}[shape]
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs:
                        subprocess.CompletedProcess(argv, 0, json.dumps(invalid_wire), "private diagnostics"))
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
    descriptor = json.loads((root / "plugins/opl-persona/opl-package.json").read_text())
    commands = {item["command_id"]: item["action_ref"] for item in descriptor["app_contributions"]["commands"]}
    for view in descriptor["app_contributions"]["views"]:
        ref = view["data_ref"]
        assert ref in DATA_CONTRACTS
        code, response = handle_request({"schema_version": REQUEST_SCHEMA, "operation": "read", "ref": ref, "input": {}})
        assert code == 0
        result = response["result"]
        assert result["kind"] == "data" and result["state"] == "ready"
        forms = result["data"]["command_inputs"]
        assert set(forms) == {commands[identifier] for identifier in view.get("command_ids", [])}
        for action_ref, form in forms.items():
            assert form["input_schema"] == ACTION_CONTRACTS[action_ref]["input"]
            assert isinstance(form["defaults"], dict)
        for item in result["data"]["items"]:
            assert {action["action_ref"] for action in item.get("actions", [])} <= set(forms)


def test_parallel_cli_updates_do_not_lose_people_or_inbox_proposals(store):
    root = Path(__file__).parents[1]
    environment = os.environ | {"PYTHONPATH": str(root / "plugins/opl-persona/runtime")}
    requests = []
    for number in range(12):
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
    assert len(store.list("people")) == 12
    from opl_persona.proposals import ProposalStore
    from opl_persona.inbox import InboxStore
    assert len(ProposalStore().list()) == 12
    assert len(InboxStore.from_paths(PersonaPaths.resolve()).list()) == 12
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
