from __future__ import annotations

from pathlib import Path

from .core import build_memo_proposals
from .paths import PersonaPaths


def _title(path: Path, body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").strip() or path.name


def memo_proposals_from_file(
    path: Path,
    *,
    vault: Path | None = None,
) -> dict[str, object]:
    """Read one Markdown note and turn it into reviewable output proposals."""
    vault_root = (vault or PersonaPaths.default_obsidian_vault()).expanduser().resolve()
    note = path.expanduser().resolve()
    if not vault_root.is_dir():
        raise FileNotFoundError(f"Obsidian vault not found: {vault_root}")
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
