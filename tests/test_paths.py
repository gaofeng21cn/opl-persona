import json
from pathlib import Path

from opl_persona.paths import PersonaPaths


def write_obsidian_binding(profile: Path, vault: Path) -> None:
    path = profile / "data" / "persona" / "resource-bindings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "opl-persona-resource-bindings.v1",
                "bindings": {
                    "my-knowledge": {
                        "schema_version": "opl-persona-resource-binding.v1",
                        "capability_id": "knowledge.documents.v1",
                        "provider_id": "obsidian",
                        "resource_ref": vault.resolve().as_uri(),
                        "scopes": ["notes.read"],
                        "policy": {"approval_required": True},
                        "health": {"status": "unknown"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_paths_prefer_persona_environment(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    paths = PersonaPaths.resolve(
        environ={
            "OPL_PROFILE_WORKSPACE": str(profile),
        }
    )
    assert paths.data_root == profile / "data" / "persona"
    assert paths.workspace == profile


def test_paths_default_to_user_profile_workspace(monkeypatch, tmp_path: Path) -> None:
    from opl_persona import paths as paths_module

    home = tmp_path / "home"
    monkeypatch.setattr(paths_module.Path, "home", staticmethod(lambda: home))
    paths = PersonaPaths.resolve(
        environ={}
    )
    assert paths.workspace == home / "OPL" / "profiles" / home.name
    assert paths.data_root == paths.workspace / "data" / "persona"


def test_paths_share_profile_workspace_when_selected(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    paths = PersonaPaths.resolve(
        environ={
            "OPL_PROFILE_WORKSPACE": str(profile),
        }
    )
    assert paths.workspace == profile
    assert paths.data_root == profile / "data" / "persona"


def test_workspace_init_creates_profile_skeleton(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    paths = PersonaPaths.resolve(environ={"OPL_PROFILE_WORKSPACE": str(profile)})
    result = paths.init_workspace()

    assert result["workspace_ready"] is True
    assert (profile / ".opl-profile-workspace.json").is_file()
    assert (profile / "profile").is_dir()
    assert (profile / "data" / "relay").is_dir()
    assert (profile / "data" / "persona").is_dir()
    assert (profile / "profile" / "identity.md").is_file()
    assert (profile / "policies" / "mail-triage.md").is_file()
    assert (profile / "data" / "persona" / "resource-bindings.json").is_file()
    assert result["readiness"] == "partial"
    assert result["created"]


def test_workspace_init_does_not_overwrite_profile_templates(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    paths = PersonaPaths.resolve(environ={"OPL_PROFILE_WORKSPACE": str(profile)})
    paths.init_workspace()
    identity = profile / "profile" / "identity.md"
    identity.write_text("# My identity\n", encoding="utf-8")

    result = paths.init_workspace()

    assert identity.read_text(encoding="utf-8") == "# My identity\n"
    assert result["created"] == []


def test_setup_status_exposes_actionable_steps_before_init(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    paths = PersonaPaths.resolve(environ={"OPL_PROFILE_WORKSPACE": str(profile)})

    status = paths.setup_status()

    assert status["readiness"] == "unconfigured"
    assert {step["id"] for step in status["steps"]} == {
        "workspace",
        "profile.identity",
        "profile.preferences",
        "policy.mail",
        "binding.obsidian",
    }
    assert status["next_actions"][0] == "opl-persona --json setup init"


def test_obsidian_note_is_read_only_and_scoped(tmp_path: Path) -> None:
    from opl_persona.obsidian import memo_proposals_from_file

    profile = tmp_path / "profile"
    vault = tmp_path / "vault"
    vault.mkdir()
    write_obsidian_binding(profile, vault)
    note = vault / "memo.md"
    note.write_text("# Memo\n\nContent.", encoding="utf-8")
    result = memo_proposals_from_file(note, workspace=profile)
    assert result["input_id"] == "obsidian://default/memo.md"
    assert note.read_text(encoding="utf-8") == "# Memo\n\nContent."


def test_obsidian_note_requires_profile_resource_binding(tmp_path: Path) -> None:
    from opl_persona.obsidian import memo_proposals_from_file

    note = tmp_path / "memo.md"
    note.write_text("# Memo", encoding="utf-8")
    try:
        memo_proposals_from_file(note, workspace=tmp_path / "profile")
    except FileNotFoundError as exc:
        assert "resource binding store not found" in str(exc)
    else:
        raise AssertionError("Obsidian access without a Profile Resource Binding must fail")
