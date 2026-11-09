"""Load accepted knowledge sources for Persona's judgment-only mail workflows.

The Profile owns references and derived state. Framework resolves private source
bodies and validates current versions and grants; local folders never imply
accepted knowledge. Snapshots retain source identity and exact content revisions.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .knowledge import read_knowledge_source
from .paths import PersonaPaths


POLICY_DIGEST_ALGORITHM = "sha256"
KNOWLEDGE_INPUTS_SCHEMA = "opl-persona-knowledge-inputs.v1"
_KNOWLEDGE_ROLES = ("identity", "team", "projects", "mail_policy")
_KNOWLEDGE_ID = re.compile(r"[a-z][a-z0-9._-]*")
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PROFILE_FIELD = re.compile(r"^-\s*([^:]+):\s*(.+?)\s*$")
_TABLE_ROW = re.compile(r"^\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")


def _selected_paths(workspace: Path | None) -> PersonaPaths:
    selected = (workspace or PersonaPaths.resolve().workspace).expanduser().resolve()
    return PersonaPaths(selected / "data" / "persona", selected)


def _knowledge_roles(paths: PersonaPaths) -> dict[str, tuple[str, ...]]:
    """Read references only; source roots and grants remain Framework-owned."""
    inputs_path = paths.data_root / "knowledge-inputs.json"
    if not inputs_path.is_file():
        raise FileNotFoundError(f"Persona knowledge inputs are not configured: {inputs_path}")
    try:
        value = json.loads(inputs_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("Persona knowledge inputs must be valid JSON") from exc
    if (not isinstance(value, dict) or set(value) != {"schema_version", "roles"}
            or value.get("schema_version") != KNOWLEDGE_INPUTS_SCHEMA
            or not isinstance(value.get("roles"), dict)
            or set(value["roles"]) - set(_KNOWLEDGE_ROLES)):
        raise ValueError("Persona knowledge inputs have an invalid schema or role")
    roles: dict[str, tuple[str, ...]] = {}
    for role in _KNOWLEDGE_ROLES:
        identifiers = value["roles"].get(role, [])
        if (not isinstance(identifiers, list)
                or any(not isinstance(item, str) or not _KNOWLEDGE_ID.fullmatch(item)
                       for item in identifiers)
                or len(identifiers) != len(set(identifiers))):
            raise ValueError(f"Persona knowledge role {role} must contain unique knowledge IDs")
        roles[role] = tuple(sorted(identifiers))
    return roles


def _snapshot_digest(sources: list[dict[str, str]]) -> str:
    # Role and content revisions are semantic inputs; physical storage paths are not.
    inputs = [{key: source[key] for key in ("role", "knowledge_id", "sha256", "content")}
              for source in sources]
    canonical = json.dumps(inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{POLICY_DIGEST_ALGORITHM}:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _read_roles(paths: PersonaPaths, roles: dict[str, tuple[str, ...]],
                selected_roles: tuple[str, ...]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    resolved: dict[str, dict[str, str]] = {}
    for role in selected_roles:
        for identifier in roles[role]:
            if identifier not in resolved:
                resolved[identifier] = read_knowledge_source(identifier, paths)
            source = resolved[identifier]
            sources.append({"role": role, **source})
    return sources


@dataclass(frozen=True)
class PolicyDocument:
    """One accepted private Markdown source and its exact revision."""

    knowledge_id: str
    source_ref: str
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
    def source_versions(self) -> dict[str, str]:
        return {document.knowledge_id: document.digest for document in self.documents}

    @property
    def text(self) -> str:
        return "\n\n".join(document.content for document in self.documents)

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace": str(self.workspace),
            "policy_refs": list(self.refs),
            "policy_digest": self.digest,
            "source_versions": self.source_versions,
            "sources": [
                {
                    "knowledge_id": document.knowledge_id,
                    "source_ref": document.source_ref,
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
    source_versions: dict[str, str]
    user_addresses: tuple[str, ...]
    team_members: tuple[dict[str, str], ...]
    projects: tuple[dict[str, str], ...]


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
    """Resolve selected identity, team, and project sources through Framework."""
    paths = _selected_paths(workspace)
    sources = _read_roles(paths, _knowledge_roles(paths), ("identity", "team", "projects"))
    user_addresses: list[str] = []
    team_members: list[dict[str, str]] = []
    projects: list[dict[str, str]] = []
    for source in sources:
        text = source["content"]
        if source["role"] == "identity":
            for name, value in _markdown_fields(text).items():
                if name in {"address", "addresses", "email", "emails", "mail addresses"}:
                    user_addresses.extend(match.casefold() for match in _EMAIL.findall(value))
        elif source["role"] == "team":
            team_members.extend(_team_records(text))
        elif source["role"] == "projects":
            projects.extend(_project_records(text))
    return MailContextSnapshot(
        refs=tuple(dict.fromkeys(source["source_ref"] for source in sources)),
        digest=_snapshot_digest(sources),
        source_versions={source["knowledge_id"]: source["sha256"] for source in sources},
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
    """Read all accepted sources explicitly selected for the mail_policy role."""
    paths = _selected_paths(workspace)
    roles = _knowledge_roles(paths)
    if not roles["mail_policy"]:
        raise ValueError("Persona mail_policy knowledge inputs are required")
    sources = _read_roles(paths, roles, ("mail_policy",))
    documents = tuple(
        PolicyDocument(
            knowledge_id=source["knowledge_id"],
            source_ref=source["source_ref"],
            content=source["content"],
            digest=source["sha256"],
        )
        for source in sources
    )
    return PolicySnapshot(
        workspace=paths.workspace,
        documents=documents,
        refs=tuple(document.source_ref for document in documents),
        digest=_snapshot_digest(sources),
    )


class MarkdownPolicyLoader:
    """Convenience owner-bound loader for callers that reuse one workspace."""

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = (workspace or PersonaPaths.resolve().workspace).expanduser()

    def load(self) -> PolicySnapshot:
        return load_markdown_policies(workspace=self.workspace)


# Short aliases keep the runtime surface discoverable without duplicating logic.
load_policy = load_markdown_policies
