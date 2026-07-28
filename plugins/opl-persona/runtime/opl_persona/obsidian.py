from __future__ import annotations

from pathlib import Path

from .bindings import (
    DEFAULT_OBSIDIAN_BINDING_ID,
    binding_file_root,
    load_resource_binding,
)
from .core import build_memo_proposals
from .paths import PersonaPaths


_CAPABILITY_IDS = {"knowledge.obsidian.v1", "knowledge.documents.v1"}


def _title(path: Path, body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").strip() or path.name


def memo_proposals_from_file(
    path: Path,
    *,
    binding_id: str = DEFAULT_OBSIDIAN_BINDING_ID,
    workspace: Path | None = None,
) -> dict[str, object]:
    """Read one Markdown note and turn it into reviewable output proposals."""
    selected_workspace = (workspace or PersonaPaths.resolve().workspace).expanduser().resolve()
    binding = load_resource_binding(selected_workspace, binding_id)
    vault_root = binding_file_root(
        binding,
        provider_id="obsidian",
        capability_ids=_CAPABILITY_IDS,
        required_scope="notes.read",
    )
    note = path.expanduser().resolve()
    if note == vault_root or vault_root not in note.parents:
        raise ValueError("note must be inside the configured Obsidian vault")
    if note.name.startswith(".") or ".obsidian" in note.parts or note.suffix.casefold() != ".md":
        raise ValueError("only non-hidden Obsidian Markdown notes are supported")
    body = note.read_text(encoding="utf-8")
    relative = note.relative_to(vault_root).as_posix()
    return build_memo_proposals(
        {
            "memo_id": f"obsidian://default/{relative}",
            "title": _title(note, body),
            "body": body,
            "source_refs": [f"obsidian://default/{relative}"],
        }
    )
