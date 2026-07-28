"""Persona-owned general Inbox staging.

The store is deliberately refs-only.  It keeps a short title/summary and
source identities, while mail, notes, and website content remain owned by
their respective authorities.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .paths import PersonaPaths


SCHEMA_VERSION = "opl-persona-inbox.v1"
_STORE_NAME = "inbox/items.json"
_STATUSES = {"staged", "routed", "consumed", "discarded"}
_MAX_TITLE = 512
_MAX_SUMMARY = 4096


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required_text(value: object, name: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    result = value.strip()
    if len(result) > max_length:
        raise ValueError(f"{name} exceeds the {max_length}-character staging limit")
    return result


def _refs(value: object, name: str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    result = list(dict.fromkeys(item.strip() for item in value if item.strip()))
    if not result:
        raise ValueError(f"{name} must contain at least one reference")
    return result


def _default_data_root(environ: Mapping[str, str] | None = None) -> Path:
    del environ
    return PersonaPaths.resolve().data_root


@dataclass(frozen=True)
class InboxItem:
    item_id: str
    capture_id: str
    item_kind: str
    title: str
    summary: str
    source_refs: tuple[str, ...]
    status: str
    route_refs: tuple[str, ...]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "capture_id": self.capture_id,
            "item_kind": self.item_kind,
            "title": self.title,
            "summary": self.summary,
            "source_refs": list(self.source_refs),
            "status": self.status,
            "route_refs": list(self.route_refs),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InboxItem":
        status = value.get("status", "")
        if status not in _STATUSES:
            raise ValueError(f"unsupported Inbox status: {status!r}")
        return cls(
            item_id=_required_text(value.get("item_id"), "item_id", max_length=256),
            capture_id=_required_text(value.get("capture_id"), "capture_id", max_length=2048),
            item_kind=_required_text(value.get("item_kind"), "item_kind", max_length=128),
            title=_required_text(value.get("title"), "title", max_length=_MAX_TITLE),
            summary=_required_text(value.get("summary"), "summary", max_length=_MAX_SUMMARY),
            source_refs=tuple(_refs(value.get("source_refs"), "source_refs")),
            status=status,
            route_refs=tuple(_refs(value.get("route_refs", []), "route_refs")) if value.get("route_refs") else (),
            created_at=_required_text(value.get("created_at"), "created_at", max_length=128),
            updated_at=_required_text(value.get("updated_at"), "updated_at", max_length=128),
        )


def _item_id(capture_id: str, source_refs: list[str]) -> str:
    material = "\0".join([capture_id, *source_refs]).encode("utf-8")
    return f"persona-inbox://{hashlib.sha256(material).hexdigest()[:24]}"


class InboxStore:
    """A tiny atomic JSON staging store under the Persona private data root."""

    def __init__(self, data_root: Path | None = None, *, environ: Mapping[str, str] | None = None) -> None:
        self.data_root = (data_root or _default_data_root(environ)).expanduser()
        self.path = self.data_root / _STORE_NAME

    @classmethod
    def from_paths(cls, paths: PersonaPaths) -> "InboxStore":
        return cls(paths.data_root)

    def _load(self) -> list[InboxItem]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping) or raw.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"invalid Inbox store schema: {self.path}")
        values = raw.get("items", [])
        if not isinstance(values, list):
            raise ValueError("Inbox store items must be a list")
        if not all(isinstance(value, Mapping) for value in values):
            raise ValueError("Inbox store items must contain objects only")
        return [InboxItem.from_dict(value) for value in values]

    def _save(self, items: list[InboxItem]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "items": [item.to_dict() for item in items],
        }
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        fd, temporary = tempfile.mkstemp(prefix=".items.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def list(self, *, status: str | None = None) -> list[InboxItem]:
        items = self._load()
        if status is not None and status not in _STATUSES:
            raise ValueError(f"unsupported Inbox status: {status!r}")
        return [item for item in items if status is None or item.status == status]

    def get(self, item_id: str) -> InboxItem | None:
        return next((item for item in self._load() if item.item_id == item_id), None)

    def capture(
        self,
        *,
        capture_id: str,
        item_kind: str,
        title: str,
        summary: str,
        source_refs: list[str] | tuple[str, ...],
    ) -> InboxItem:
        """Persist a user-triggered capture without reading any source body."""

        capture_id = _required_text(capture_id, "capture_id", max_length=2048)
        item_kind = _required_text(item_kind, "item_kind", max_length=128)
        title = _required_text(title, "title", max_length=_MAX_TITLE)
        summary = _required_text(summary, "summary", max_length=_MAX_SUMMARY)
        refs = _refs(source_refs, "source_refs")
        now = _now()
        identifier = _item_id(capture_id, refs)
        items = self._load()
        previous = next((item for item in items if item.item_id == identifier), None)
        item = InboxItem(
            item_id=identifier,
            capture_id=capture_id,
            item_kind=item_kind,
            title=title,
            summary=summary,
            source_refs=tuple(refs),
            status=previous.status if previous else "staged",
            route_refs=previous.route_refs if previous else (),
            created_at=previous.created_at if previous else now,
            updated_at=now,
        )
        if previous:
            items = [item if existing.item_id == identifier else existing for existing in items]
        else:
            items.append(item)
        self._save(items)
        return item

    def capture_proposal(self, proposal: Mapping[str, Any]) -> InboxItem:
        """Apply only a Persona-local capture proposal to this private store."""

        if proposal.get("proposal_kind") != "personal.inbox.v1.capture":
            raise ValueError("proposal is not a personal.inbox.v1.capture proposal")
        if proposal.get("target") != "personal.inbox.v1" or proposal.get("operation") != "capture":
            raise ValueError("Inbox proposal target/operation is invalid")
        approval = proposal.get("approval")
        if not isinstance(approval, Mapping) or approval.get("required") is not True:
            raise ValueError("Inbox capture proposal must remain review-gated")
        if approval.get("external_write_allowed") is not False:
            raise ValueError("Persona-local Inbox capture cannot authorize an external write")
        payload = proposal.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("Inbox capture proposal payload must be an object")
        refs = _refs(payload.get("source_refs"), "source_refs")
        top_refs = _refs(proposal.get("source_refs"), "proposal.source_refs")
        if refs != top_refs:
            raise ValueError("Inbox proposal source_refs mismatch")
        return self.capture(
            capture_id=payload.get("capture_id"),
            item_kind=payload.get("item_kind", "note"),
            title=payload.get("title"),
            summary=payload.get("summary"),
            source_refs=refs,
        )

    def route(self, item_id: str, route_ref: str, *, status: str = "routed") -> InboxItem:
        route_ref = _required_text(route_ref, "route_ref", max_length=2048)
        if status not in _STATUSES or status == "staged":
            raise ValueError("route status must be routed, consumed, or discarded")
        items = self._load()
        current = next((item for item in items if item.item_id == item_id), None)
        if current is None:
            raise KeyError(item_id)
        now = _now()
        updated = InboxItem(
            item_id=current.item_id,
            capture_id=current.capture_id,
            item_kind=current.item_kind,
            title=current.title,
            summary=current.summary,
            source_refs=current.source_refs,
            status=status,
            route_refs=tuple(dict.fromkeys((*current.route_refs, route_ref))),
            created_at=current.created_at,
            updated_at=now,
        )
        self._save([updated if item.item_id == item_id else item for item in items])
        return updated
