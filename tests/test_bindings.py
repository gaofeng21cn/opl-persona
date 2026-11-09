import json
from pathlib import Path

import pytest

from opl_persona.bindings import (
    binding_file_root,
    check_resource_binding,
    list_resource_bindings,
    load_resource_binding,
    set_resource_binding,
)
from opl_persona.paths import PersonaPaths


def test_set_list_and_check_obsidian_binding(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    vault = tmp_path / "vault"
    vault.mkdir()
    PersonaPaths.resolve(environ={"OPL_PROFILE_WORKSPACE": str(profile)}).init_workspace()

    binding = set_resource_binding(
        profile,
        binding_id="my-knowledge",
        capability_id="knowledge.obsidian.v1",
        provider_id="obsidian",
        resource_ref=vault.resolve().as_uri(),
        scopes=["notes.read"],
        policy={"approval_required": True},
    )

    assert binding.resource_ref == vault.resolve().as_uri()
    assert set(list_resource_bindings(profile)) == {"my-knowledge"}
    result = check_resource_binding(profile, "my-knowledge")
    assert result["status"] == "healthy"
    assert result["root_exists"] is True
    assert load_resource_binding(profile, "my-knowledge").provider_id == "obsidian"


def test_plain_markdown_source_uses_same_scoped_binding_mechanics(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    notes = profile / "shared" / "memory"
    notes.mkdir(parents=True)
    note = notes / "policy.md"
    note.write_text("# Local policy\n", encoding="utf-8")
    binding = set_resource_binding(
        profile, binding_id="local-notes", capability_id="knowledge.documents.v1",
        provider_id="markdown", resource_ref=notes.resolve().as_uri(), scopes=["notes.read"],
    )

    result = check_resource_binding(profile, "local-notes")

    assert result["status"] == "healthy"
    assert binding_file_root(binding, provider_id="markdown", capability_ids={"knowledge.documents.v1"},
                             required_scope="notes.read") == notes
    assert note.read_text(encoding="utf-8") == "# Local policy\n"
    with pytest.raises(ValueError, match="not a obsidian resource binding"):
        binding_file_root(binding, provider_id="obsidian", capability_ids={"knowledge.documents.v1"},
                          required_scope="notes.read")
    with pytest.raises(ValueError, match="does not grant"):
        binding_file_root(binding, provider_id="markdown", capability_ids={"knowledge.documents.v1"},
                          required_scope="notes.write")


def test_markdown_binding_cannot_claim_obsidian_capability(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not provide"):
        set_resource_binding(tmp_path, binding_id="local-notes", capability_id="knowledge.obsidian.v1",
                             provider_id="markdown", resource_ref=tmp_path.as_uri(), scopes=["notes.read"])


def test_binding_store_never_accepts_secret_shaped_policy_keys(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    PersonaPaths.resolve(environ={"OPL_PROFILE_WORKSPACE": str(profile)}).init_workspace()

    try:
        set_resource_binding(
            profile,
            binding_id="bad",
            capability_id="knowledge.obsidian.v1",
            provider_id="obsidian",
            resource_ref=(tmp_path / "vault").as_uri(),
            scopes=["notes.read"],
            policy={"api_token": "must-not-persist"},
        )
    except ValueError as exc:
        assert "credential material" in str(exc)
    else:
        raise AssertionError("secret-shaped binding metadata must fail closed")

    store = profile / "data" / "persona" / "resource-bindings.json"
    assert json.loads(store.read_text(encoding="utf-8"))["bindings"] == {}
