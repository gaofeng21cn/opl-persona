"""Persona-owned Markdown policy loading for judgment-only workflows.

Policy files are private workspace inputs.  The repository and installed
Package contain only this loader; they never contain the user's Markdown
rules.  A snapshot records the selected files and hashes their bytes so a
proposal can be reproduced and audited even after the workspace changes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .paths import PersonaPaths


POLICY_DIGEST_ALGORITHM = "sha256"
DEFAULT_POLICY_REF = "policy://persona/mail-triage/v1"
_POLICY_ROOT = "policies"
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PROFILE_FIELD = re.compile(r"^-\s*([^:]+):\s*(.+?)\s*$")
_TABLE_ROW = re.compile(r"^\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")


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


@dataclass(frozen=True)
class MailContextSnapshot:
    """Private Profile facts used only for conservative mail routing."""

    refs: tuple[str, ...]
    digest: str
    user_addresses: tuple[str, ...]
    team_members: tuple[dict[str, str], ...]
    projects: tuple[dict[str, str], ...]


def _markdown_files(workspace: Path, roots: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for root_name in roots:
        root = workspace / root_name
        if root.is_dir():
            files.extend(root.rglob("*.md"))
    return sorted(set(files), key=lambda item: item.relative_to(workspace).as_posix())


def _content_digest(paths: Iterable[Path], *, workspace: Path) -> str:
    return _canonical_digest(paths, workspace=workspace)


def _markdown_fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in block.splitlines():
        match = _PROFILE_FIELD.match(line.strip())
        if match:
            fields[match.group(1).strip().casefold()] = match.group(2).strip()
    return fields


def _project_records(text: str) -> list[dict[str, str]]:
    sections = re.split(r"(?m)^##\s+", text)
    records: list[dict[str, str]] = []
    for section in sections[1:]:
        heading, _, body = section.partition("\n")
        fields = _markdown_fields(body)
        if not fields:
            continue
        record = {"alias": heading.strip(), **fields}
        records.append(record)
    return records


def _team_records(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for line in text.splitlines():
        match = _TABLE_ROW.match(line.strip())
        if not match:
            continue
        name, _role, address = (item.strip() for item in match.groups())
        if name.casefold() in {"name", "---"} or address in {"", "-", "---"}:
            continue
        if not _EMAIL.fullmatch(address):
            continue
        records.append({"name": name, "email": address.casefold()})
    unique: dict[str, dict[str, str]] = {}
    for record in records:
        unique.setdefault(record["email"], record)
    return list(unique.values())


def load_mail_context(*, workspace: Path | None = None) -> MailContextSnapshot:
    """Load Profile-owned identity, manuscript, and roster facts."""

    selected = (workspace or PersonaPaths.resolve().workspace).expanduser().resolve()
    files = _markdown_files(selected, ("profile", "context"))
    user_addresses: list[str] = []
    team_members: list[dict[str, str]] = []
    projects: list[dict[str, str]] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(selected).as_posix()
        if relative.startswith("profile/"):
            fields = _markdown_fields(text)
            for name, value in fields.items():
                if name in {"address", "addresses", "email", "emails", "mail addresses"}:
                    user_addresses.extend(match.casefold() for match in _EMAIL.findall(value))
        if relative == "context/people.md":
            team_members.extend(_team_records(text))
        if relative == "context/projects.md":
            projects.extend(_project_records(text))
    return MailContextSnapshot(
        refs=tuple(f"profile://persona/{path.relative_to(selected).as_posix()}" for path in files),
        digest=_content_digest(files, workspace=selected),
        user_addresses=tuple(dict.fromkeys(user_addresses)),
        team_members=tuple(team_members),
        projects=tuple(projects),
    )


def resolve_manuscript_context(
    snapshot: MailContextSnapshot,
    *,
    subject: str,
    body: str,
) -> dict[str, object]:
    """Resolve one manuscript record only when Profile evidence matches."""

    haystack = f"{subject}\n{body}".casefold()
    ranked: list[tuple[int, dict[str, str]]] = []
    match_fields = {
        "alias",
        "manuscript id",
        "recent manuscript id",
        "recent submission id",
        "article id/doi",
        "title",
    }
    for record in snapshot.projects:
        candidates = [
            value.strip()
            for key, value in record.items()
            if key in match_fields and len(value.strip()) >= 6
        ]
        score = max((len(value) for value in candidates if value.casefold() in haystack), default=0)
        if score:
            ranked.append((score, record))
    if not ranked:
        return {}
    ranked.sort(key=lambda item: item[0], reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return {}
    record = ranked[0][1]
    author = next(
        (
            record[key]
            for key in (
                "actual first author",
                "actual first/corresponding author",
                "first listed author",
            )
            if record.get(key)
        ),
        "",
    )
    address = next(
        (
            match
            for key in (
                "verified routing address",
                "verified first-author address",
            )
            for match in _EMAIL.findall(record.get(key, ""))
        ),
        "",
    )
    result: dict[str, object] = {"manuscript_alias": record["alias"]}
    if author:
        result["actual_first_author"] = {"name": author, "email": address.casefold()} if address else {"name": author}
    return result


def load_markdown_policies(
    *,
    workspace: Path | None = None,
) -> PolicySnapshot:
    """Load every Markdown rule from one Profile Workspace's policies directory."""

    selected_workspace = (workspace or PersonaPaths.resolve().workspace).expanduser().resolve()
    policy_root = selected_workspace / _POLICY_ROOT
    unique = sorted(policy_root.rglob("*.md")) if policy_root.is_dir() else []
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


class MarkdownPolicyLoader:
    """Convenience owner-bound loader for callers that reuse one workspace."""

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = (workspace or PersonaPaths.resolve().workspace).expanduser()

    def load(self) -> PolicySnapshot:
        return load_markdown_policies(workspace=self.workspace)


# Short aliases keep the runtime surface discoverable without duplicating logic.
load_policy = load_markdown_policies
