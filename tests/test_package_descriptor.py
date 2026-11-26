import json
import tomllib
from pathlib import Path

from opl_persona.app_contributions import ACTION_CONTRACTS, DATA_CONTRACTS


ROOT = Path(__file__).parents[1]
PACKAGE_PATH = ROOT / "opl-package.json"
LEGACY_PACKAGE_PATH = ROOT / "packages" / "opl-persona" / "package.json"
ICON_PATH = ROOT / "assets" / "icon.png"
SKILL_PATH = ROOT / "skills" / "opl-persona" / "SKILL.md"
ENTRYPOINT_PATH = ROOT / "bin" / "opl-persona"
RUNTIME_ROOT = ROOT / "runtime" / "opl_persona"

ACTION_REFS = set(ACTION_CONTRACTS)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_package_descriptor_has_one_root_v2_authority() -> None:
    assert PACKAGE_PATH.is_file()
    assert not LEGACY_PACKAGE_PATH.exists()
    assert not (ROOT / "plugins").exists()
    assert not (ROOT / ".agents" / "plugins" / "marketplace.json").exists()


def test_package_identity_capabilities_and_version_are_aligned() -> None:
    package = load_json(PACKAGE_PATH)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert package["schema_version"] == "opl.package.v2"
    identity = package["identity"]
    assert identity["id"] == "opl-persona"
    assert identity["intent"] == "extension"
    assert identity["version"] == project["project"]["version"]
    assert package["dependencies"]["opl_base"] == "^2.0.0"
    assert any(rt["name"] == "python" for rt in package["dependencies"]["runtimes"])
    assert package["permissions"]["workspace"]["access"] == "read_write"
    assert package["provides"]["cli_bin"] == [{"name": "opl-persona", "path": "bin/opl-persona"}]
    assert package["provides"]["skills"] == [
        {"id": "opl-persona", "path": "./skills/opl-persona", "exposure": "opt_in"}
    ]
    assert package["distribution"] == {
        "oci": "ghcr.io/gaofeng21cn/one-person-lab-packages/opl-persona",
        "visibility": "public",
    }
    assert package["host_hints"]["codex"]["plugin_name"] == "opl-persona"
    assert SKILL_PATH.is_file()
    assert ENTRYPOINT_PATH.is_file()
    assert RUNTIME_ROOT.is_dir()


def test_plugin_default_prompts_fit_codex_limits() -> None:
    prompts = load_json(PACKAGE_PATH)["identity"]["default_prompts"]
    assert isinstance(prompts, list) and 1 <= len(prompts) <= 3
    assert all(isinstance(prompt, str) and 0 < len(prompt) <= 128 for prompt in prompts)


def test_plugin_uses_family_brand_artwork() -> None:
    package = load_json(PACKAGE_PATH)
    identity = package["identity"]
    codex = package["host_hints"]["codex"]
    icon = ICON_PATH.read_bytes()

    assert identity["icon"] == "assets/icon.png"
    assert identity["repository"] == "https://github.com/gaofeng21cn/opl-persona"
    assert codex["brand_color"] == "#BE304A"
    assert icon.startswith(b"\x89PNG\r\n\x1a\n")
    assert icon == (ROOT / "assets/branding/opl-persona-logo.png").read_bytes()


def test_app_contributions_are_role_neutral_and_reference_persona_actions() -> None:
    declarative = load_json(PACKAGE_PATH)["ui"]["declarative"]
    assert set(declarative) <= {"navigation", "views", "settings_forms"}

    navigation_ids = [item["id"] for item in declarative["navigation"]]
    view_ids = [item["id"] for item in declarative["views"]]
    action_refs = {
        action["action_ref"]
        for view in declarative["views"]
        for action in view.get("actions", [])
    }
    assert len(navigation_ids) == len(set(navigation_ids))
    assert len(view_ids) == len(set(view_ids))
    assert {item["view_id"] for item in declarative["navigation"]} <= set(view_ids)
    assert action_refs == ACTION_REFS
    actions_by_id = {
        action["id"]: action
        for view in declarative["views"]
        for action in view.get("actions", [])
    }
    assert actions_by_id["persona.proposal.approve"]["confirm"] is True

    serialized = json.dumps(declarative)
    assert "standard_agent" not in serialized
    for view in declarative["views"]:
        assert view["slot"] == "workbench.panel"
    assert {view["view_type"] for view in declarative["views"]} <= {"list_detail", "activity_log", "approval_diff"}


def test_app_contribution_abi_is_package_owned_and_matches_declared_refs() -> None:
    package = load_json(PACKAGE_PATH)
    handler = package["provides"]["contribution_handler"]
    assert handler == {
        "kind": "cli",
        "argv": ["./bin/opl-persona", "--json", "app-contribution"],
        "transport": "stdin_json_stdout_json",
    }
    views = package["ui"]["declarative"]["views"]
    assert {view["data_ref"] for view in views} == set(DATA_CONTRACTS)


def test_local_install_runs_copied_carrier_without_source_checkout(tmp_path):
    import os
    import subprocess
    prefix = tmp_path / "installed"
    subprocess.run(["make", "install-local", "INSTALL_MODE=standalone", f"PREFIX={prefix}"], cwd=ROOT, check=True, capture_output=True)
    launcher = prefix / "bin" / "opl-persona"
    assert str(ROOT) not in launcher.read_text()
    result = subprocess.run([str(launcher), "--json", "doctor"], check=True, capture_output=True, text=True,
        env=os.environ | {"OPL_PROFILE_WORKSPACE": str(tmp_path / "profile")})
    assert json.loads(result.stdout)["ok"] is True
    assert (prefix / "share" / "opl-persona" / "runtime" / "opl_persona" / "cli.py").is_file()


def test_native_launcher_selects_only_enabled_matching_installed_package(tmp_path):
    import importlib.util
    import pytest
    spec = importlib.util.spec_from_file_location("persona_launcher", ROOT / "scripts" / "launch-installed-persona.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    pkg_cache = tmp_path / "packages/opl-persona"
    for version, pkg_id in [("0.4.0", "opl-persona"), ("0.5.0", "foreign")]:
        root = pkg_cache / version
        (root / "bin").mkdir(parents=True)
        (root / "bin/opl-persona").write_text("pass")
        (root / "opl-package.json").write_text(json.dumps({
            "schema_version": "opl.package.v2",
            "identity": {"id": pkg_id, "version": version},
        }))
    assert launcher.installed_entrypoint(tmp_path) == pkg_cache / "0.4.0/bin/opl-persona"
    (pkg_cache / "0.4.0/opl-package.json").write_text(json.dumps({
        "schema_version": "opl.package.v1",
        "identity": {"id": "opl-persona", "version": "0.4.0"},
    }))
    with pytest.raises(ValueError, match="no valid installed Persona v2 package"):
        launcher.installed_entrypoint(tmp_path)
