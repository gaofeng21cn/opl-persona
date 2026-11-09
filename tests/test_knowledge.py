import hashlib
import json
import stat
import subprocess
from pathlib import Path

import pytest

from opl_persona.knowledge import read_knowledge_source, source_dependencies, verify_knowledge_dependencies
from opl_persona.paths import PersonaPaths
from opl_persona.workspace import WORKSPACE_SCHEMA, WorkspaceStore


VERSIONS = {"owner.research.design": "sha256:" + "a" * 64}


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "profile"))
    return WorkspaceStore()


def create_memory(store, identifier="research-memory", versions=None):
    return store.update_memory(memory_id=identifier, title="Research summary", summary="Private derived summary",
        memory_kind="research", person_ids=[], context_ids=["research-writing"], source_refs=["knowledge://research"],
        source_versions=versions or VERSIONS, expected_digest="absent")


def test_source_read_uses_framework_identity_and_checks_exact_revision(store, monkeypatch):
    content = "# 用户知识\n证据与解释分开。\n"
    source = {"knowledge_id": "owner.research.design", "content": content,
              "sha256": "sha256:" + hashlib.sha256(content.encode()).hexdigest(),
              "source_ref": "knowledge-source://owner.notes/research.md"}
    def run(argv, **kwargs):
        assert argv == ["opl", "knowledge", "read-source", "--workspace", str(store.paths.workspace),
                        "--domain", "persona", "--id", source["knowledge_id"], "--json"]
        assert kwargs["env"]["OPL_PROFILE_WORKSPACE"] == str(store.paths.workspace)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"version": "g2", "knowledge_source": source}), "")
    monkeypatch.setattr(subprocess, "run", run)
    assert read_knowledge_source(source["knowledge_id"], store.paths) == source


@pytest.mark.parametrize("mutation", [
    {"knowledge_id": "owner.other"}, {"sha256": "sha256:" + "0" * 64},
    {"content": ""}, {"content": "x" * (256 * 1024 + 1)}, {"source_ref": ""},
])
def test_source_read_rejects_wrong_identity_or_revision_without_exposing_content(store, monkeypatch, mutation):
    content = "private identity body"
    source = {"knowledge_id": "owner.research.design", "content": content,
              "sha256": "sha256:" + hashlib.sha256(content.encode()).hexdigest(), "source_ref": "knowledge://owner"}
    source.update(mutation)
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs:
        subprocess.CompletedProcess(argv, 0, json.dumps({"version": "g2", "knowledge_source": source}), ""))
    with pytest.raises(ValueError, match="requires current Framework readback") as error:
        read_knowledge_source("owner.research.design", store.paths)
    assert content not in str(error.value)


def test_framework_verification_uses_body_free_public_contract_and_private_temporary_request(store, monkeypatch):
    seen = []
    def run(argv, **kwargs):
        request = Path(argv[argv.index("--dependencies") + 1])
        seen.append(request)
        assert stat.S_IMODE(request.stat().st_mode) == 0o600
        assert json.loads(request.read_text()) == [{"knowledge_id": "owner.research.design", "sha256": "sha256:" + "a" * 64}]
        assert argv[:3] == ["opl", "knowledge", "verify-dependencies"]
        assert argv[argv.index("--domain") + 1] == "persona"
        assert argv[argv.index("--workspace") + 1] == str(store.paths.workspace)
        assert kwargs["env"]["OPL_PROFILE_WORKSPACE"] == str(store.paths.workspace)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"version": "g2", "knowledge_dependencies": {"valid": True, "issues": []}}), "")
    monkeypatch.setattr(subprocess, "run", run)
    assert verify_knowledge_dependencies(VERSIONS, store.paths) == {"valid": True, "issues": []}
    assert all(not path.exists() for path in seen)


@pytest.mark.parametrize("response", [
    {}, {"version": "v1", "knowledge_dependencies": {"valid": True, "issues": []}},
    {"version": "g2", "knowledge_dependencies": {"valid": 1, "issues": []}},
    {"version": "g2", "knowledge_dependencies": {"valid": True, "issues": ["revoked"]}},
])
def test_verification_rejects_invalid_or_inconsistent_responses(store, monkeypatch, response):
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, json.dumps(response), ""))
    assert verify_knowledge_dependencies(VERSIONS, store.paths)["valid"] is False


@pytest.mark.parametrize("value", [None, {}, [], {"../outside": "sha256:" + "a" * 64},
    {"owner.research.design": "latest"}, {"owner.research.design": {"root": "/private"}}])
def test_source_versions_cannot_redirect_to_arbitrary_paths_or_unversioned_content(value):
    with pytest.raises(ValueError):
        source_dependencies(value)


@pytest.mark.parametrize("reason", ["source_revoked", "source_unauthorized", "source_expired", "source_drifted", "source_missing"])
def test_source_change_removes_approved_summary_without_destroying_review_evidence(store, monkeypatch, reason):
    current = {"valid": True, "issues": []}
    monkeypatch.setattr("opl_persona.workspace.verify_knowledge_dependencies", lambda value, paths: dict(current))
    candidate = create_memory(store)
    accepted = store.review_memory(memory_id=candidate["id"], status="approved", approval_ref="review://owner/accepted",
                                  expected_digest=candidate["digest"])
    assert store.context("research-writing")["memories"][0]["summary"] == "Private derived summary"
    original = store.path.read_bytes()
    current.update(valid=False, issues=[reason])
    context = store.context("research-writing")
    assert context["memories"] == []
    assert context["excluded_knowledge"] == [{"id": candidate["id"], "issues": [reason]}]
    projected = store.list("memories")[0]
    assert projected["summary"] == "" and projected["title"] == ""
    assert projected["digest"] == accepted["digest"]
    with pytest.raises(ValueError, match="sources require review"):
        store.review_memory(memory_id=candidate["id"], status="approved", approval_ref="review://owner/retry",
                            expected_digest=accepted["digest"])
    assert store.path.read_bytes() == original


def test_invalid_optional_memory_does_not_hide_other_current_memory(store, monkeypatch):
    invalid = set()
    def verify(value, paths):
        bad = next((identifier for identifier in value if identifier in invalid), None)
        return {"valid": not bad, "issues": ["source_revoked:" + bad] if bad else []}
    monkeypatch.setattr("opl_persona.workspace.verify_knowledge_dependencies", verify)
    for identifier, versions in (("old", VERSIONS), ("current", {"owner.other": "sha256:" + "b" * 64})):
        record = create_memory(store, identifier, versions)
        store.review_memory(memory_id=identifier, status="approved", approval_ref="review://owner/" + identifier,
                            expected_digest=record["digest"])
    invalid.add("owner.research.design")
    assert [item["id"] for item in store.context("research-writing")["memories"]] == ["current"]


def test_people_and_custom_context_are_revalidated_too(store, monkeypatch):
    active = True
    monkeypatch.setattr("opl_persona.workspace.verify_knowledge_dependencies", lambda value, paths:
                        {"valid": active, "issues": [] if active else ["source_expired"]})
    person = store.update_person(person_id="researcher", display_name="Private name", summary="Private profile",
                                aliases=[], source_refs=["knowledge://person"], source_versions=VERSIONS, expected_digest="absent")
    mode = next(item for item in store.list("contexts") if item["id"] == "research-writing")
    store.update_context(context_id=mode["id"], title=mode["title"], summary="Private writing preference",
                         guidance={"tone": "private"}, source_refs=["knowledge://policy"], source_versions=VERSIONS,
                         expected_digest=mode["digest"])
    active = False
    assert store.list("people")[0]["display_name"] == ""
    result = store.context("research-writing")
    assert result["context"]["guidance"] == {}
    assert result["excluded_knowledge"][0]["id"] == "research-writing"
    assert person["id"] == "researcher"


def test_unavailable_framework_excludes_summary_and_cannot_approve_it(store, monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("not installed")
    monkeypatch.setattr(subprocess, "run", unavailable)
    candidate = create_memory(store)
    assert candidate["source_verification"]["valid"] is False
    with pytest.raises(ValueError, match="framework_knowledge_verification_unavailable"):
        store.review_memory(memory_id=candidate["id"], status="approved", approval_ref="review://owner/retry",
                            expected_digest=candidate["digest"])


def test_explicit_migration_preserves_bytes_and_quarantines_unsupported_old_approvals(store):
    old = store._load()
    old["schema_version"] = "opl-persona-workspace.v1"
    old["memories"] = [{"id": "legacy", "title": "Historical title", "summary": "Keep original content",
        "memory_kind": "fact", "person_ids": [], "context_ids": [], "source_refs": ["obsidian://note"],
        "status": "approved", "review": {"approval_ref": "old-review"}}]
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps(old))
    original = store.path.read_bytes()
    with pytest.raises(ValueError, match="workspace-migrate"):
        store.context()
    migrated = store.migrate_workspace()
    assert Path(migrated["backup_ref"]).read_bytes() == original
    state = json.loads(store.path.read_text())
    assert state["schema_version"] == WORKSPACE_SCHEMA
    assert state["memories"][0]["summary"] == "Keep original content"
    assert state["memories"][0]["status"] == "candidate"
    assert state["memories"][0]["source_versions"] == {}
    assert store.context()["memories"] == []
    assert store.context()["context"]["summary"]
    before_second_migration = store.path.read_bytes()
    assert store.migrate_workspace()["reason"] == "already_current"
    assert store.path.read_bytes() == before_second_migration


@pytest.mark.parametrize("field,value", [
    ("label_i18n", {"zh-CN": "Private role", "en-US": "Academic mail"}),
    ("summary_i18n", {"zh-CN": "Private fact", "en-US": "Relationship-aware academic correspondence"}),
    ("mode", "private-mode"), ("private_note", "Private fact"),
])
def test_modified_default_fields_cannot_bypass_source_review_during_migration(store, monkeypatch, field, value):
    old = store._load()
    old["schema_version"] = "opl-persona-workspace.v1"
    old["contexts"][0][field] = value
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps(old))
    monkeypatch.setattr("opl_persona.workspace.verify_knowledge_dependencies", lambda value, paths:
                        {"valid": False, "issues": ["missing_source_versions"]})
    store.migrate_workspace()
    item = json.loads(store.path.read_text())["contexts"][0]
    assert item["knowledge_origin"] == "derived"
    assert item["migration_review_required"] is True
    assert item[field] == value
    assert store.context()["context"]["guidance"] == {}
    assert store.context()["excluded_knowledge"][0]["id"] == item["id"]
