import json
from pathlib import Path

from opl_persona.bindings import (
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
