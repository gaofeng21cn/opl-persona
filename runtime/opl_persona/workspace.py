"""Profile-local derived context; source authorities remain outside Persona."""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    from opl_client import OplClientError, connect
except ModuleNotFoundError:  # pragma: no cover - optional when opl_client SDK is absent
    class OplClientError(RuntimeError):
        """Fallback error type when opl_client is unavailable."""

    connect = None  # type: ignore[assignment]

from .paths import PersonaPaths
from .knowledge import source_dependencies, verify_knowledge_dependencies
from .primitives import atomic_json, item_digest, text


WORKSPACE_SCHEMA = "opl-persona-workspace.v2"
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


def product_context(mode: str) -> dict[str, Any]:
    title, summary = CONTEXT_MODES[mode]
    return {"id": mode, "title": title, "summary": summary, "mode": mode,
            "label_i18n": copy.deepcopy(CONTEXT_LABELS[mode]),
            "summary_i18n": {"en-US": summary, "zh-CN": CONTEXT_SUMMARIES_ZH[mode]},
            "guidance": {"purpose": summary},
            "source_refs": [f"opl-package://opl-persona/context/{mode}"],
            "knowledge_origin": "product", "source_versions": {}}


def is_product_context(item: dict[str, Any]) -> bool:
    if item.get("id") not in CONTEXT_MODES:
        return False
    canonical = product_context(item["id"])
    metadata = {"created_at", "updated_at", "migration_review_required"}
    return set(item) <= set(canonical) | metadata and all(item.get(key) == value for key, value in canonical.items())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def refs(value: object, name: str = "source_refs", *, required: bool = True) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{name} must be a list of non-empty strings")
    result = list(dict.fromkeys(item.strip() for item in value))
    if required and not result:
        raise ValueError(f"{name} must contain at least one reference")
    return result


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


def current_relay_memory(item: object) -> bool:
    if not isinstance(item, dict) or item.get("status") != "approved":
        return False
    source_refs = item.get("source_refs")
    if (not isinstance(source_refs, list) or not source_refs
            or not all(isinstance(source, str) and source for source in source_refs)):
        return False
    currentness = item.get("source_currentness")
    if (not isinstance(currentness, dict) or currentness.get("status") != "current"
            or currentness.get("reasons") != [] or not isinstance(currentness.get("checked_at"), str)):
        return False
    try:
        return datetime.fromisoformat(currentness["checked_at"].replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def relay_read(ref: str, value: dict[str, Any], paths: PersonaPaths) -> dict[str, Any]:
    """Use only Relay's package-scoped public read ABI via opld, never a private store."""
    if ref not in {"personal.memory.v1#people", "personal.memory.v1#search"}:
        raise ValueError("unsupported Relay memory read ref")
    del paths  # opld manages workspace isolation; Persona keeps paths arg for ABI stability.
    client_connect = connect
    client_error = OplClientError
    if client_connect is None:
        try:
            from opl_client import OplClientError as _SdkError, connect as _sdk_connect
            client_connect = _sdk_connect
            client_error = _SdkError
        except ModuleNotFoundError:
            return {"state": "unavailable", "items": [], "package_id": "opl-relay", "ref": ref,
                    "reason": "Relay public memory ABI unavailable"}
    elif client_error.__module__ == __name__:
        try:
            from opl_client import OplClientError as _SdkError
            client_error = _SdkError
        except ModuleNotFoundError:
            pass
    try:
        with client_connect() as client:
            raw_response = client.call(
                "app.contribution.read",
                {"package_id": "opl-relay", "ref": ref, "input": value},
            )
        if not isinstance(raw_response, dict):
            raise ValueError("Relay public read returned a non-object response")
        if raw_response.get("ok") is False:
            raise ValueError("Relay public read returned ok=False")
        if "opl_app_contribution" in raw_response:
            raise ValueError("Unexpected v1 wrapper from v2 opld")
        payload = raw_response.get("result") if isinstance(raw_response.get("result"), dict) else raw_response
        if not isinstance(payload, dict):
            raise ValueError("Relay memory read payload is invalid")
        if payload.get("package_id") not in (None, "opl-relay") or payload.get("ref") not in (None, ref):
            raise ValueError("Relay public read returned an invalid package identity")
        state_val = payload.get("state") or payload.get("status")
        if state_val != "ready":
            raise ValueError("Relay memory read is not ready")
        if "kind" in payload and payload.get("kind") != "data":
            raise ValueError("Relay memory read kind must be data")
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("Relay memory read must contain data.items")
        policy = data.get("source_policy")
        if (not isinstance(policy, dict) or policy.get("source_currentness_checked") is not True
                or policy.get("only_approved_memory_included") is not True):
            raise ValueError("Relay memory read must verify approved source currentness")
        items = []
        for raw in data["items"]:
            if not isinstance(raw, dict):
                continue
            item = copy.deepcopy(raw)
            if ref.endswith("#search"):
                if not current_relay_memory(item):
                    continue
            else:
                memories = item.get("approved_memories")
                if not isinstance(memories, list):
                    continue
                # Identity can remain discoverable, but its summary must come from a current source.
                item["approved_memories"] = [memory for memory in memories if current_relay_memory(memory)]
                item["summary"] = next((memory.get("summary", "") for memory in item["approved_memories"]), "")
                item["source_refs"] = list(dict.fromkeys(
                    source for memory in item["approved_memories"] for source in memory.get("source_refs", [])
                    if isinstance(source, str) and source))
            items.append(item)
        return {"state": "ready", "items": items, "source_policy": copy.deepcopy(policy),
                "package_id": "opl-relay", "ref": ref}
    except (OSError, ValueError, client_error):
        return {"state": "unavailable", "items": [], "package_id": "opl-relay", "ref": ref,
                "reason": "Relay public memory ABI unavailable"}


class WorkspaceStore:
    def __init__(self, paths: PersonaPaths | None = None) -> None:
        self.paths = paths or PersonaPaths.resolve()
        self.path = self.paths.data_root / "workspace.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            contexts = [product_context(mode) for mode in CONTEXT_MODES]
            return {"schema_version": WORKSPACE_SCHEMA, "active_context_id": "academic-mail",
                    "contexts": contexts, "people": [], "memories": []}
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("schema_version") != WORKSPACE_SCHEMA:
            raise ValueError("invalid Persona workspace schema; use workspace-migrate for an existing v1 workspace")
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
        return [self._projection(item) for item in items
                if status is None or item.get("status") == status]

    def _source_check(self, item: dict[str, Any]) -> dict[str, Any]:
        if is_product_context(item):
            return {"valid": True, "issues": []}
        return verify_knowledge_dependencies(item.get("source_versions"), self.paths)

    def _projection(self, item: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(item) | {"digest": item_digest(item)}
        result["source_verification"] = self._source_check(item)
        if not result["source_verification"]["valid"]:
            # Keep identities and provenance for repair; stale private content is
            # not returned by the management ABI as another readable truth.
            for key in ("title", "summary", "display_name", "guidance", "aliases", "label_i18n", "summary_i18n"):
                if key in result:
                    result[key] = {} if isinstance(result[key], dict) else [] if isinstance(result[key], list) else ""
            fields = {"id", "mode", "title", "summary", "display_name", "guidance", "aliases",
                      "label_i18n", "summary_i18n", "memory_kind", "person_ids", "context_ids",
                      "source_refs", "source_versions", "knowledge_origin", "status", "review",
                      "created_at", "updated_at", "migration_review_required", "digest", "source_verification"}
            result = {key: value for key, value in result.items() if key in fields}
        return result

    def migrate_workspace(self) -> dict[str, Any]:
        """One-time lossless migration; old approvals cannot prove source currency."""
        with workspace_lock(self.paths):
            if not self.path.exists():
                return {"migrated": False, "schema_version": WORKSPACE_SCHEMA, "reason": "workspace_absent"}
            original = self.path.read_bytes()
            state = json.loads(original)
            if isinstance(state, dict) and state.get("schema_version") == WORKSPACE_SCHEMA:
                return {"migrated": False, "schema_version": WORKSPACE_SCHEMA, "reason": "already_current"}
            if not isinstance(state, dict) or state.get("schema_version") != "opl-persona-workspace.v1":
                raise ValueError("unsupported Persona workspace migration source")
            if any(not isinstance(state.get(key), list) or not all(isinstance(item, dict) for item in state[key])
                   for key in ("contexts", "people", "memories")):
                raise ValueError("invalid Persona migration collections")
            backup = self.paths.data_root / "migration-backups" / (hashlib.sha256(original).hexdigest() + ".json")
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists() and backup.read_bytes() != original:
                raise ValueError("migration backup identity conflict")
            if not backup.exists():
                with backup.open("xb") as handle:
                    os.chmod(backup, 0o600)
                    handle.write(original)
            for collection in ("contexts", "people", "memories"):
                for item in state[collection]:
                    item["knowledge_origin"] = "derived"
                    item["source_versions"] = {}
                    item["migration_review_required"] = True
                    if collection == "contexts" and is_product_context(item | {"knowledge_origin": "product"}):
                        item["knowledge_origin"] = "product"
                        item["migration_review_required"] = False
                    if collection == "memories":
                        item["status"] = "forgotten" if item.get("status") == "forgotten" else "candidate"
                        item["review"] = None
            state["schema_version"] = WORKSPACE_SCHEMA
            atomic_json(self.path, state)
            return {"migrated": True, "schema_version": WORKSPACE_SCHEMA, "backup_ref": str(backup),
                    "source_review_required": True, "preserved_records": sum(len(state[key]) for key in ("contexts", "people", "memories"))}

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
            return self._projection(item)

    def update_context(self, *, context_id: str, title: str, summary: str, guidance: dict[str, Any],
                       source_refs: list[str], source_versions: dict[str, str], expected_digest: str,
                       label_i18n: dict[str, str] | None = None) -> dict[str, Any]:
        if context_id not in CONTEXT_MODES:
            raise ValueError("context_id must identify a supported working mode")
        if not isinstance(guidance, dict):
            raise ValueError("guidance must be an object")
        source_dependencies(source_versions)
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
                            "source_refs": refs(source_refs), "source_versions": copy.deepcopy(source_versions),
                            "knowledge_origin": "derived"}, expected_digest)

    def select_context(self, context_id: str) -> dict[str, Any]:
        with workspace_lock(self.paths):
            state = self._load()
            if context_id not in {item["id"] for item in state["contexts"]}:
                raise ValueError("unknown context_id")
            state["active_context_id"] = context_id
            atomic_json(self.path, state)
        return self.context(context_id)

    def update_person(self, *, person_id: str, display_name: str, summary: str, aliases: list[str],
                      source_refs: list[str], source_versions: dict[str, str], expected_digest: str) -> dict[str, Any]:
        source_dependencies(source_versions)
        return self._update("people", {"id": text(person_id, "person_id", 256),
                            "title": text(display_name, "display_name", 512), "display_name": display_name.strip(),
                            "summary": text(summary, "summary"), "aliases": refs(aliases, "aliases", required=False),
                            "source_refs": refs(source_refs), "source_versions": copy.deepcopy(source_versions),
                            "knowledge_origin": "derived"}, expected_digest)

    def update_memory(self, *, memory_id: str, title: str, summary: str, memory_kind: str,
                      person_ids: list[str], context_ids: list[str], source_refs: list[str],
                      source_versions: dict[str, str], expected_digest: str) -> dict[str, Any]:
        source_dependencies(source_versions)
        return self._update("memories", {"id": text(memory_id, "memory_id", 256), "title": text(title, "title", 512),
                            "summary": text(summary, "summary"), "memory_kind": text(memory_kind, "memory_kind", 128),
                            "person_ids": refs(person_ids, "person_ids", required=False),
                            "context_ids": refs(context_ids, "context_ids", required=False),
                            "source_refs": refs(source_refs), "source_versions": copy.deepcopy(source_versions),
                            "knowledge_origin": "derived", "status": "candidate", "review": None}, expected_digest)

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
            if status == "approved":
                verification = self._source_check(item)
                if not verification["valid"]:
                    raise ValueError("memory sources require review: " + "; ".join(verification["issues"]))
            item["status"] = status
            item["review"] = {"approval_ref": approval_ref, "expected_digest": expected_digest, "reviewed_at": now()}
            item["updated_at"] = now()
            atomic_json(self.path, state)
            return self._projection(item)

    def context(self, context_id: str | None = None, person_id: str | None = None, *,
                drafting: bool = False) -> dict[str, Any]:
        with workspace_lock(self.paths):
            state = self._load()
        selected = context_id or state["active_context_id"]
        mode = next((item for item in state["contexts"] if item["id"] == selected), None)
        if mode is None:
            raise ValueError("unknown context_id")
        def matches_person(item: dict[str, Any]) -> bool:
            if drafting and not item["person_ids"]:
                return True
            if person_id is None:
                return not drafting
            return person_id in item["person_ids"]

        candidates = [copy.deepcopy(item) for item in state["memories"] if item["status"] == "approved"
                    and (not item["context_ids"] or selected in item["context_ids"])
                    and matches_person(item)]
        excluded: list[dict[str, Any]] = []
        def current(item: dict[str, Any]) -> bool:
            verification = self._source_check(item)
            if not verification["valid"]:
                excluded.append({"id": item["id"], "issues": verification["issues"]})
            return verification["valid"]
        memories = [item for item in candidates if current(item)]
        selected_people = {identifier for item in memories for identifier in item["person_ids"]}
        people = [copy.deepcopy(item) for item in state["people"] if item["id"] in selected_people and current(item)]
        mode_current = current(mode)
        context = copy.deepcopy(mode) if mode_current else {"id": selected, "mode": selected,
                  "summary": "", "guidance": {}, "source_refs": [], "source_state": "review_required"}
        return {"context": context, "people": people, "memories": memories,
                "source_refs": list(dict.fromkeys(context["source_refs"] + [ref for item in memories + people for ref in item["source_refs"]])),
                "excluded_knowledge": excluded, "memory_policy": "approved_and_current_sources_only",
                "source_content_is_untrusted_data": True, "external_write_allowed": False}

    def relay(self, collection: str, *, query: str = "", entity: str = "", status: str = "approved") -> dict[str, Any]:
        if collection not in {"people", "search"}:
            raise ValueError("unsupported Relay collection")
        del status  # Relay's public evidence projection already includes approved memory only.
        inputs = {key: value for key, value in {"query": query, "entity": entity}.items() if value}
        if collection == "people":
            inputs.pop("entity", None)
        return relay_read(f"personal.memory.v1#{collection}", inputs, self.paths)
