"""Persona-owned Markdown policy loading for judgment-only workflows.

Policy files are private workspace inputs.  The repository and installed
Package contain only this loader; they never contain the user's Markdown
rules.  A snapshot records the selected files and hashes their bytes so a
proposal can be reproduced and audited even after the workspace changes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .paths import PersonaPaths


POLICY_DIGEST_ALGORITHM = "sha256"
DEFAULT_POLICY_REF = "policy://persona/mail-triage/v1"
_POLICY_ROOT = "policies"


def _digest_path(path: Path, *, workspace: Path) -> str:
    relative = path.relative_to(workspace).as_posix()
    digest = hashlib.sha256()
    digest.update(relative.encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    return f"{POLICY_DIGEST_ALGORITHM}:{digest.hexdigest()}"


def _canonical_digest(paths: Iterable[Path], *, workspace: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(workspace).as_posix()):
        relative = path.relative_to(workspace).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return f"{POLICY_DIGEST_ALGORITHM}:{digest.hexdigest()}"


def _canonical_ref(path: Path, *, workspace: Path) -> str:
    relative = path.relative_to(workspace).as_posix()
    if relative == f"{_POLICY_ROOT}/mail-triage.md":
        return DEFAULT_POLICY_REF
    if relative.endswith(".md"):
        relative = relative[:-3]
    return f"policy://persona/{relative}"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_ref(ref: str, *, workspace: Path) -> Path:
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError("policy reference must be a non-empty string")
    value = ref.strip()
    prefix = "policy://persona/"
    if not value.startswith(prefix):
        raise ValueError("policy references must use policy://persona/ identities")
    tail = value[len(prefix) :].strip("/")
    if not tail:
        raise ValueError("policy reference must identify a Markdown file")
    candidates: list[Path] = []
    if tail.endswith("/v1"):
        tail = tail[: -len("/v1")].rstrip("/")
    raw = Path(tail)
    candidates.extend(
        [
            workspace / raw,
            workspace / f"{tail}.md",
            workspace / _POLICY_ROOT / raw,
            workspace / _POLICY_ROOT / f"{tail}.md",
        ]
    )
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if (
            resolved.is_file()
            and resolved.suffix.casefold() == ".md"
            and _inside(resolved, workspace.resolve())
        ):
            return resolved
    raise FileNotFoundError(f"policy reference does not resolve to Markdown: {value}")


@dataclass(frozen=True)
class PolicyDocument:
    """One selected private Markdown policy file."""

    path: Path
    ref: str
    content: str
    digest: str


@dataclass(frozen=True)
class PolicySnapshot:
    """Immutable policy evidence attached to a Persona proposal."""

    workspace: Path
    documents: tuple[PolicyDocument, ...]
    refs: tuple[str, ...]
    digest: str

    @property
    def text(self) -> str:
        return "\n\n".join(document.content for document in self.documents)

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace": str(self.workspace),
            "policy_refs": list(self.refs),
            "policy_digest": self.digest,
            "files": [
                {
                    "path": str(document.path),
                    "ref": document.ref,
                    "digest": document.digest,
                }
                for document in self.documents
            ],
        }


def load_markdown_policies(
    *,
    workspace: Path | None = None,
    refs: Iterable[str] | None = None,
    paths: Iterable[str | Path] | None = None,
) -> PolicySnapshot:
    """Load selected Markdown rules from a Persona workspace.

    ``refs`` uses stable ``policy://persona/...`` identities.  ``paths`` is
    useful for a migration or an explicitly reviewed local policy set; relative
    paths are resolved below ``workspace``.  When neither is supplied, all
    Markdown files below ``<workspace>/policies`` are selected in lexical
    order.
    """

    selected_workspace = (workspace or PersonaPaths.resolve().workspace).expanduser().resolve()
    selected: list[Path] = []
    if refs is not None:
        for ref in refs:
            selected.append(_resolve_ref(ref, workspace=selected_workspace))
    if paths is not None:
        for raw_path in paths:
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = selected_workspace / candidate
            resolved = candidate.expanduser().resolve()
            if not _inside(resolved, selected_workspace):
                raise ValueError("policy paths must stay inside the Persona workspace")
            if not resolved.is_file() or resolved.suffix.casefold() != ".md":
                raise FileNotFoundError(f"policy path is not a Markdown file: {candidate}")
            selected.append(resolved)
    if refs is None and paths is None:
        policy_root = selected_workspace / _POLICY_ROOT
        if policy_root.is_dir():
            selected.extend(sorted(policy_root.rglob("*.md")))
    unique = sorted(set(selected), key=lambda item: item.relative_to(selected_workspace).as_posix())
    if not unique:
        raise FileNotFoundError(f"no Markdown policies found in Persona workspace: {selected_workspace}")
    documents = tuple(
        PolicyDocument(
            path=path,
            ref=_canonical_ref(path, workspace=selected_workspace),
            content=path.read_text(encoding="utf-8"),
            digest=_digest_path(path, workspace=selected_workspace),
        )
        for path in unique
    )
    return PolicySnapshot(
        workspace=selected_workspace,
        documents=documents,
        refs=tuple(document.ref for document in documents),
        digest=_canonical_digest(unique, workspace=selected_workspace),
    )


def policy_digest_for_files(
    paths: Iterable[str | Path],
    *,
    workspace: Path,
) -> str:
    """Return the same digest used by :func:`load_markdown_policies`."""

    selected_workspace = workspace.expanduser().resolve()
    selected: list[Path] = []
    for raw_path in paths:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = selected_workspace / candidate
        resolved = candidate.expanduser().resolve()
        if not _inside(resolved, selected_workspace) or not resolved.is_file():
            raise FileNotFoundError(f"policy path is not a file in workspace: {candidate}")
        selected.append(resolved)
    if not selected:
        raise ValueError("at least one policy path is required")
    return _canonical_digest(set(selected), workspace=selected_workspace)


class MarkdownPolicyLoader:
    """Convenience owner-bound loader for callers that reuse one workspace."""

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = (workspace or PersonaPaths.resolve().workspace).expanduser()

    def load(
        self,
        *,
        refs: Iterable[str] | None = None,
        paths: Iterable[str | Path] | None = None,
    ) -> PolicySnapshot:
        return load_markdown_policies(workspace=self.workspace, refs=refs, paths=paths)


# Short aliases keep the runtime surface discoverable without duplicating logic.
load_policy = load_markdown_policies
