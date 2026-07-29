import hashlib
import json
import struct
import tomllib
from pathlib import Path

from opl_persona.app_contributions import ACTION_CONTRACTS, DATA_CONTRACTS


ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "opl-persona"
PACKAGE_PATH = PLUGIN_ROOT / "opl-package.json"
LEGACY_PACKAGE_PATH = ROOT / "packages" / "opl-persona" / "package.json"
PLUGIN_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
ICON_PATH = PLUGIN_ROOT / "assets" / "icon.png"
SKILL_PATH = PLUGIN_ROOT / "skills" / "opl-persona" / "SKILL.md"
ENTRYPOINT_PATH = PLUGIN_ROOT / "bin" / "opl-persona"
RUNTIME_ROOT = PLUGIN_ROOT / "runtime" / "opl_persona"

CAPABILITY_IDS = {
    "personal.context.v1",
    "personal.memory.v1",
    "personal.inbox.v1",
    "knowledge.obsidian.v1",
    "communications.mail.v1",
    "website.publication.v1",
}
ACTION_REFS = {
    "personal.context.v1#proposal.inspect",
    "personal.context.v1#proposal.approve",
    "communications.mail.v1#triage.propose",
    "personal.inbox.v1#capture.propose",
    "knowledge.obsidian.v1#note.propose",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_package_descriptor_has_one_carrier_root_authority() -> None:
    assert PACKAGE_PATH.is_file()
    assert not LEGACY_PACKAGE_PATH.exists()


def test_package_identity_capabilities_and_plugin_version_are_aligned() -> None:
    package = load_json(PACKAGE_PATH)
    plugin = load_json(PLUGIN_PATH)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert package["surface_kind"] == "opl_capability_package_manifest.v2"
    assert package["package_id"] == "opl-persona"
    assert package["package_role"] == "capability_package"
    assert package["version"] == plugin["version"] == project["project"]["version"]
    assert set(package["exports"]["core_module_ids"]) == CAPABILITY_IDS
    assert package["exports"]["core_skill_ids"] == ["opl-persona"]
    assert package["exports"]["optional_skill_policy_ref"] == "opl-package.json#/exports"
    assert package["codex_surface"]["plugin_id"] == plugin["name"] == "opl-persona"
    assert package["codex_surface"]["plugin_source_path"] == "."

    assert SKILL_PATH.is_file()
    assert ENTRYPOINT_PATH.is_file()
    assert RUNTIME_ROOT.is_dir()
    assert "app_contributions" not in plugin


def test_package_content_lock_matches_carrier_bytes() -> None:
    package = load_json(PACKAGE_PATH)
    content_lock = package["content_lock"]
    digest = hashlib.sha256()

    assert content_lock["algorithm"] == "sha256"
    assert content_lock["canonicalization"] == "ordered_path_length_file_length_bytes"
    assert "opl-package.json" not in content_lock["paths"]
    for relative_path in content_lock["paths"]:
        locked_path = PLUGIN_ROOT / relative_path
        assert locked_path.is_file()
        assert locked_path.resolve().is_relative_to(PLUGIN_ROOT.resolve())
        path_bytes = relative_path.encode("utf-8")
        file_bytes = locked_path.read_bytes()
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(len(file_bytes).to_bytes(8, "big"))
        digest.update(file_bytes)

    assert content_lock["digest"] == f"sha256:{digest.hexdigest()}"


def test_plugin_uses_a_dedicated_small_format_icon() -> None:
    plugin = load_json(PLUGIN_PATH)
    interface = plugin["interface"]
    icon = ICON_PATH.read_bytes()

    assert interface["composerIcon"] == "./assets/icon.png"
    assert interface["logo"] == "./assets/icon.png"
    assert interface["websiteURL"] == "https://github.com/gaofeng21cn/opl-persona"
    assert interface["brandColor"] == "#BE304A"
    assert icon.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", icon[16:24]) == (512, 512)
    assert icon[25] in {4, 6} or (icon[25] == 3 and b"tRNS" in icon)
    assert "assets/icon.png" in load_json(PACKAGE_PATH)["content_lock"]["paths"]


def test_app_contributions_are_role_neutral_and_reference_persona_actions() -> None:
    contributions = load_json(PACKAGE_PATH)["app_contributions"]

    assert contributions["schema_version"] == "opl-app-contributions.v1"
    assert set(contributions) <= {
        "schema_version",
        "navigation",
        "views",
        "commands",
        "badges",
    }

    navigation_ids = [item["navigation_id"] for item in contributions["navigation"]]
    view_ids = [item["view_id"] for item in contributions["views"]]
    command_ids = [item["command_id"] for item in contributions["commands"]]
    assert len(navigation_ids) == len(set(navigation_ids))
    assert len(view_ids) == len(set(view_ids))
    assert len(command_ids) == len(set(command_ids))
    assert {item["view_id"] for item in contributions["navigation"]} <= set(view_ids)
    assert {
        command_id
        for view in contributions["views"]
        for command_id in view.get("command_ids", [])
    } <= set(command_ids)
    assert {item["action_ref"] for item in contributions["commands"]} == ACTION_REFS
    commands_by_id = {
        item["command_id"]: item for item in contributions["commands"]
    }
    assert commands_by_id["persona.proposal.approve"]["confirmation_required"] is True

    serialized = json.dumps(contributions)
    assert "standard_agent" not in serialized
    assert not ({"component", "code", "path", "url"} & set(contributions))


def test_app_contribution_abi_is_package_owned_and_matches_declared_refs() -> None:
    package = load_json(PACKAGE_PATH)
    abi = package["codex_surface"]["app_contribution_abi"]

    assert abi == {
        "schema_version": "opl-package-app-contribution-cli.v1",
        "transport": "stdin_json_stdout_json",
        "argv": ["./bin/opl-persona", "--json", "app-contribution"],
        "request_schema": "opl-package-app-contribution-request.v1",
        "response_schema": "opl-package-app-contribution-response.v1",
    }
    contributions = package["app_contributions"]
    assert {view["data_ref"] for view in contributions["views"]} == set(DATA_CONTRACTS)
    assert {command["action_ref"] for command in contributions["commands"]} == set(ACTION_CONTRACTS)
