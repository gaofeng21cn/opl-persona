from pathlib import Path

from opl_persona.paths import PersonaPaths


def test_paths_prefer_persona_environment(tmp_path: Path) -> None:
    paths = PersonaPaths.resolve(
        environ={
            "OPL_PERSONA_HOME": str(tmp_path / "data"),
            "OPL_PERSONA_WORKSPACE": str(tmp_path / "workspace"),
            "OPL_RELAY_HOME": str(tmp_path / "relay"),
        }
    )
    assert paths.data_root == tmp_path / "data"
    assert paths.workspace == tmp_path / "workspace"


def test_obsidian_note_is_read_only_and_scoped(tmp_path: Path) -> None:
    from opl_persona.obsidian import memo_proposals_from_file

    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "memo.md"
    note.write_text("# Memo\n\nContent.", encoding="utf-8")
    result = memo_proposals_from_file(note, vault=vault)
    assert result["input_id"] == "obsidian://default/memo.md"
    assert note.read_text(encoding="utf-8") == "# Memo\n\nContent."
