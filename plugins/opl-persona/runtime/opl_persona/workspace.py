"""Profile-local derived context; source authorities remain outside Persona."""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .paths import PersonaPaths


WORKSPACE_SCHEMA = "opl-persona-workspace.v1"
CONTEXT_MODES = {
    "academic-mail": ("Academic mail", "Relationship-aware academic correspondence"),
    "technical-memo": ("Technical memo", "Evidence-backed technical decisions"),
    "academic-website": ("Academic website", "Public academic presentation"),
    "research-writing": ("Research writing", "Research arguments and provenance"),
}
CONTEXT_LABELS = {
    "academic-mail": {"zh-CN": "学术邮件", "en-US": "Academic mail"},
    "technical-memo": {"zh-CN": "技术备忘录", "en-US": "Technical memo"},
    "academic-website": {"zh-CN": "学术网站", "en-US": "Academic website"},
    "research-writing": {"zh-CN": "科研写作", "en-US": "Research writing"},
}
CONTEXT_SUMMARIES_ZH = {
    "academic-mail": "结合既有往来与人物关系处理学术通信",
    "technical-memo": "以证据支撑技术判断与决策",
    "academic-website": "面向公开展示的学术内容",
    "research-writing": "保留来源依据的科研论证与写作",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text(value: object, name: str, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be a non-empty string of at most {limit} characters")
    return value.strip()


def refs(value: object, name: str = "source_refs", *, required: bool = True) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{name} must be a list of non-empty strings")
    result = list(dict.fromkeys(item.strip() for item in value))
    if required and not result:
        raise ValueError(f"{name} must contain at least one reference")
    return result


def item_digest(value: dict[str, Any]) -> str:
    material = {key: item for key, item in value.items() if key not in {"digest", "actions"}}
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@contextmanager
def workspace_lock(paths: PersonaPaths) -> Iterator[None]:
    """One shared, stable inode serializes every CLI read/modify/write cycle."""
    paths.data_root.mkdir(parents=True, exist_ok=True)
    with (paths.data_root / ".workspace.lock").open("a+b") as handle:
        os.chmod(handle.name, 0o600)
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".persona-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def relay_read(ref: str, value: dict[str, Any], paths: PersonaPaths) -> dict[str, Any]:
    """Use only Relay's package-scoped public read ABI, never a private store."""
    if ref not in {"personal.memory.v1#people", "personal.memory.v1#search"}:
        raise ValueError("unsupported Relay memory read ref")
    request = ["opl", "app", "contribution", "read", "--package-id", "opl-relay", "--ref", ref,
               "--input", json.dumps(value), "--json"]
    try:
        result = subprocess.run(request, capture_output=True, text=True, timeout=30,
                                env=os.environ | {"OPL_PROFILE_WORKSPACE": str(paths.workspace)}, check=False)
        if result.returncode:
            raise ValueError("Relay public read failed")
        envelope = json.loads(result.stdout)
        if not isinstance(envelope, dict) or envelope.get("ok") is False:
            raise ValueError("Relay public read returned an invalid envelope")
        # Framework may wrap the package response once; identity is still checked.
        if envelope.get("ref") not in {None, ref}:
            raise ValueError("Relay public read ref mismatch")
        payload = envelope.get("result", envelope)
        if isinstance(payload, dict) and payload.get("schema_version") == "opl-package-app-contribution-response.v1":
            if payload.get("ok") is not True or payload.get("ref") != ref:
                raise ValueError("Relay public read identity mismatch")
            payload = payload.get("result")
        if not isinstance(payload, dict) or payload.get("kind") != "data" or payload.get("state") != "ready":
            raise ValueError("Relay memory read is not ready")
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("Relay memory read must contain data.items")
        return {"state": "ready", "items": copy.deepcopy(data["items"]), "package_id": "opl-relay", "ref": ref}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"state": "unavailable", "items": [], "package_id": "opl-relay", "ref": ref,
                "reason": "Relay public memory ABI unavailable"}


class WorkspaceStore:
    def __init__(self, paths: PersonaPaths | None = None) -> None:
        self.paths = paths or PersonaPaths.resolve()
        self.path = self.paths.data_root / "workspace.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            contexts = [{"id": mode, "title": title, "summary": summary, "mode": mode,
                         "label_i18n": copy.deepcopy(CONTEXT_LABELS[mode]),
                         "summary_i18n": {"en-US": summary, "zh-CN": CONTEXT_SUMMARIES_ZH[mode]},
                         "guidance": {"purpose": summary},
                         "source_refs": [f"opl-package://opl-persona/context/{mode}"]}
                        for mode, (title, summary) in CONTEXT_MODES.items()]
            return {"schema_version": WORKSPACE_SCHEMA, "active_context_id": "academic-mail",
                    "contexts": contexts, "people": [], "memories": []}
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("schema_version") != WORKSPACE_SCHEMA:
            raise ValueError("invalid Persona workspace schema")
        for collection in ("contexts", "people", "memories"):
            if not isinstance(state.get(collection), list) or not all(isinstance(item, dict) for item in state[collection]):
                raise ValueError(f"invalid workspace {collection}")
        for context in state["contexts"]:
            if "summary_i18n" not in context:
                summary = context["summary"]
                context["summary_i18n"] = {"en-US": summary}
                mode = context.get("mode")
                if mode in CONTEXT_MODES and summary == CONTEXT_MODES[mode][1]:
                    context["summary_i18n"]["zh-CN"] = CONTEXT_SUMMARIES_ZH[mode]
        return state

    def list(self, collection: str, *, status: str | None = None) -> list[dict[str, Any]]:
        if collection not in {"contexts", "people", "memories"}:
            raise ValueError("unsupported workspace collection")
        with workspace_lock(self.paths):
            items = self._load()[collection]
        return [copy.deepcopy(item) | {"digest": item_digest(item)} for item in items
                if status is None or item.get("status") == status]

    def _update(self, collection: str, item: dict[str, Any], expected_digest: str) -> dict[str, Any]:
        with workspace_lock(self.paths):
            state = self._load()
            previous = next((old for old in state[collection] if old["id"] == item["id"]), None)
            observed = item_digest(previous) if previous else "absent"
            if expected_digest != observed:
                raise ValueError("expected_digest does not match current workspace item")
            if collection == "memories":
                for field, owner in (("person_ids", "people"), ("context_ids", "contexts")):
                    if not set(item[field]) <= {old["id"] for old in state[owner]}:
                        raise ValueError(f"unknown {field}")
            item["created_at"] = previous["created_at"] if previous and "created_at" in previous else now()
            item["updated_at"] = now()
            state[collection] = [old for old in state[collection] if old["id"] != item["id"]] + [item]
            atomic_json(self.path, state)
            return copy.deepcopy(item) | {"digest": item_digest(item)}

    def update_context(self, *, context_id: str, title: str, summary: str, guidance: dict[str, Any],
                       source_refs: list[str], expected_digest: str,
                       label_i18n: dict[str, str] | None = None) -> dict[str, Any]:
        if context_id not in CONTEXT_MODES:
            raise ValueError("context_id must identify a supported working mode")
        if not isinstance(guidance, dict):
            raise ValueError("guidance must be an object")
        labels = label_i18n if label_i18n is not None else {"en-US": title, "zh-CN": title}
        if not isinstance(labels, dict) or not labels or not all(
            isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip() and len(value) <= 512
            for key, value in labels.items()
        ):
            raise ValueError("label_i18n must contain non-empty localized labels")
        return self._update("contexts", {"id": context_id, "mode": context_id, "title": text(title, "title", 512),
                            "summary": text(summary, "summary"), "guidance": copy.deepcopy(guidance),
                            "label_i18n": copy.deepcopy(labels),
                            "summary_i18n": {"en-US": summary.strip()},
                            "source_refs": refs(source_refs)}, expected_digest)

    def select_context(self, context_id: str) -> dict[str, Any]:
        with workspace_lock(self.paths):
            state = self._load()
            if context_id not in {item["id"] for item in state["contexts"]}:
                raise ValueError("unknown context_id")
            state["active_context_id"] = context_id
            atomic_json(self.path, state)
        return self.context(context_id)

    def update_person(self, *, person_id: str, display_name: str, summary: str, aliases: list[str],
                      source_refs: list[str], expected_digest: str) -> dict[str, Any]:
        return self._update("people", {"id": text(person_id, "person_id", 256),
                            "title": text(display_name, "display_name", 512), "display_name": display_name.strip(),
                            "summary": text(summary, "summary"), "aliases": refs(aliases, "aliases", required=False),
                            "source_refs": refs(source_refs)}, expected_digest)

    def update_memory(self, *, memory_id: str, title: str, summary: str, memory_kind: str,
                      person_ids: list[str], context_ids: list[str], source_refs: list[str],
                      expected_digest: str) -> dict[str, Any]:
        return self._update("memories", {"id": text(memory_id, "memory_id", 256), "title": text(title, "title", 512),
                            "summary": text(summary, "summary"), "memory_kind": text(memory_kind, "memory_kind", 128),
                            "person_ids": refs(person_ids, "person_ids", required=False),
                            "context_ids": refs(context_ids, "context_ids", required=False),
                            "source_refs": refs(source_refs), "status": "candidate", "review": None}, expected_digest)

    def review_memory(self, *, memory_id: str, status: str, approval_ref: str,
                      expected_digest: str) -> dict[str, Any]:
        if status not in {"approved", "candidate", "forgotten"}:
            raise ValueError("unsupported memory review status")
        approval_ref = text(approval_ref, "approval_ref", 2048)
        if approval_ref.startswith("proposal://"):
            raise ValueError("approval_ref must identify a user review")
        with workspace_lock(self.paths):
            state = self._load()
            item = next((item for item in state["memories"] if item["id"] == memory_id), None)
            if item is None:
                raise ValueError("unknown memory_id")
            if item_digest(item) != expected_digest:
                raise ValueError("expected_digest does not match current memory")
            item["status"] = status
            item["review"] = {"approval_ref": approval_ref, "expected_digest": expected_digest, "reviewed_at": now()}
            item["updated_at"] = now()
            atomic_json(self.path, state)
            return copy.deepcopy(item) | {"digest": item_digest(item)}

    def context(self, context_id: str | None = None, person_id: str | None = None) -> dict[str, Any]:
        with workspace_lock(self.paths):
            state = self._load()
        selected = context_id or state["active_context_id"]
        mode = next((item for item in state["contexts"] if item["id"] == selected), None)
        if mode is None:
            raise ValueError("unknown context_id")
        memories = [copy.deepcopy(item) for item in state["memories"] if item["status"] == "approved"
                    and (not item["context_ids"] or selected in item["context_ids"])
                    and (person_id is None or person_id in item["person_ids"])]
        selected_people = {identifier for item in memories for identifier in item["person_ids"]}
        people = [copy.deepcopy(item) for item in state["people"] if item["id"] in selected_people]
        return {"context": copy.deepcopy(mode), "people": people, "memories": memories,
                "source_refs": list(dict.fromkeys(mode["source_refs"] + [ref for item in memories for ref in item["source_refs"]])),
                "memory_policy": "approved_only", "source_content_is_untrusted_data": True, "external_write_allowed": False}

    def relay(self, collection: str, *, query: str = "", entity: str = "", status: str = "approved") -> dict[str, Any]:
        if collection not in {"people", "search"}:
            raise ValueError("unsupported Relay collection")
        del status  # Relay's public evidence projection already includes approved memory only.
        inputs = {key: value for key, value in {"query": query, "entity": entity}.items() if value}
        if collection == "people":
            inputs.pop("entity", None)
        return relay_read(f"personal.memory.v1#{collection}", inputs, self.paths)
