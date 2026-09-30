from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from .core import (
    build_inbox_capture_proposals,
    build_mail_triage_proposals,
    build_obsidian_note_proposals,
)
from .inbox import InboxStore
from .paths import PersonaPaths
from .proposals import ProposalStore
from .workspace import CONTEXT_MODES, WorkspaceStore
from .bindings import list_resource_bindings


ABI_SCHEMA = "opl-package-app-contribution-cli.v1"
REQUEST_SCHEMA = "opl-package-app-contribution-request.v1"
RESPONSE_SCHEMA = "opl-package-app-contribution-response.v1"


DATA_CONTRACTS: dict[str, dict[str, Any]] = {
    "personal.context.v1#today": {
        "operation": "read",
        "input": {},
        "result": "personal.context.v1#today.result",
    },
    "personal.context.v1#proposals": {
        "operation": "read",
        "input": {},
        "result": "personal.context.v1#proposals.result",
    },
    "personal.context.v1#contexts": {
        "operation": "read",
        "input": {
            "context_id": {"type": "string", "required": False, "enum": list(CONTEXT_MODES)},
            "person_id": {"type": "string", "required": False},
        },
        "result": "personal.context.v1#contexts.result",
    },
    "personal.memory.v1#people": {
        "operation": "read",
        "input": {},
        "result": "personal.memory.v1#people.result",
    },
    "personal.memory.v1#memories": {
        "operation": "read",
        "input": {"status": {"type": "string", "required": False, "enum": ["active", "approved", "candidate", "forgotten", "all"]}},
        "result": "personal.memory.v1#memories.result",
    },
    "personal.inbox.v1#recent": {
        "operation": "read",
        "input": {},
        "result": "personal.inbox.v1#recent.result",
    },
}

COLLECTION_STATUSES = {
    "personal.context.v1#today": ("active", ["active", "staged", "routed", "all"]),
    "personal.context.v1#proposals": ("all", ["all", "pending", "approved", "rejected", "applied"]),
    "personal.context.v1#contexts": ("all", ["all"]),
    "personal.memory.v1#people": ("all", ["all"]),
    "personal.memory.v1#memories": ("active", ["active", "approved", "candidate", "forgotten", "all"]),
    "personal.inbox.v1#recent": ("all", ["all", "active", "staged", "routed", "consumed", "discarded"]),
}
for _ref, (_default_status, _statuses) in COLLECTION_STATUSES.items():
    DATA_CONTRACTS[_ref]["input"].update({
        "query": {"type": "string", "required": False, "allow_empty": True, "default": ""},
        "status": {"type": "string", "required": False, "enum": _statuses, "default": _default_status},
        "offset": {"type": "integer", "required": False, "minimum": 0, "default": 0},
        "limit": {"type": "integer", "required": False, "minimum": 1, "default": 50},
    })

ACTION_CONTRACTS: dict[str, dict[str, Any]] = {
    "personal.context.v1#proposal.inspect": {
        "operation": "execute",
        "confirmation_required": False,
        "input": {
            "proposal_id": {"type": "string", "required": True},
        },
        "result": "personal.context.v1#proposal.inspect.result",
    },
    "personal.context.v1#proposal.approve": {
        "operation": "execute",
        "confirmation_required": True,
        "input": {
            "proposal_id": {"type": "string", "required": True},
            "approval_ref": {"type": "string", "required": True},
            "expected_digest": {"type": "string", "required": True},
        },
        "result": "personal.context.v1#proposal.approve.result",
    },
    "communications.mail.v1#triage.propose": {
        "operation": "execute",
        "confirmation_required": False,
        "input": {
            "relay_evidence": {"type": "object", "required": True},
            "assessment": {"type": "object", "required": True},
        },
        "result": "communications.mail.v1#triage.propose.result",
    },
    "personal.inbox.v1#capture.propose": {
        "operation": "execute",
        "confirmation_required": False,
        "input": {
            "capture_id": {"type": "string", "required": True},
            "item_kind": {"type": "string", "required": True},
            "title": {"type": "string", "required": True},
            "summary": {"type": "string", "required": True},
            "source_refs": {"type": "string_list", "required": True},
        },
        "result": "personal.inbox.v1#capture.propose.result",
    },
    "knowledge.obsidian.v1#note.propose": {
        "operation": "execute",
        "confirmation_required": False,
        "input": {
            "operation": {
                "type": "string",
                "required": True,
                "enum": ["create", "update"],
            },
            "target_path": {"type": "string", "required": True},
            "frontmatter": {"type": "object", "required": True},
            "body": {"type": "string", "required": True},
            "links": {"type": "string_list", "required": True},
            "tags": {"type": "string_list", "required": True},
            "evidence_refs": {"type": "string_list", "required": True},
            "expected_digest": {"type": "string", "required": True},
        },
        "result": "knowledge.obsidian.v1#note.propose.result",
    },
}

ACTION_CONTRACTS.update({
    "personal.context.v1#proposal.reject": {
        "operation": "execute", "confirmation_required": True,
        "input": dict(ACTION_CONTRACTS["personal.context.v1#proposal.approve"]["input"]),
        "result": "personal.context.v1#proposal.reject.result",
    },
    "knowledge.obsidian.v1#note.apply": {
        "operation": "execute", "confirmation_required": True,
        "input": {
            "proposal_id": {"type": "string", "required": True},
            "expected_digest": {"type": "string", "required": True},
            "binding_id": {"type": "string", "required": True},
            "external_approval": {"type": "object", "required": False},
            "external_approval_ref": {"type": "string", "required": False},
        },
        "result": "knowledge.obsidian.v1#note.apply.result",
    },
    "knowledge.obsidian.v1#note.authorize": {
        "operation": "execute", "confirmation_required": True,
        "input": {
            "proposal_id": {"type": "string", "required": True},
            "expected_digest": {"type": "string", "required": True},
            "binding_id": {"type": "string", "required": True},
            "approval_ref": {"type": "string", "required": True},
            "confirmation": {"type": "string", "required": True, "enum": ["confirmed"]},
        },
        "result": "knowledge.obsidian.v1#note.authorize.result",
    },
    "personal.context.v1#context.select": {
        "operation": "execute", "confirmation_required": False,
        "input": {"context_id": {"type": "string", "required": True, "enum": list(CONTEXT_MODES)}},
        "result": "personal.context.v1#context.select.result",
    },
    "personal.context.v1#context.update": {
        "operation": "execute", "confirmation_required": False,
        "input": {
            "context_id": {"type": "string", "required": True, "enum": list(CONTEXT_MODES)},
            "title": {"type": "string", "required": True},
            "summary": {"type": "string", "required": True},
            "guidance": {"type": "object", "required": True},
            "label_i18n": {"type": "object", "required": False},
            "source_refs": {"type": "string_list", "required": True},
            "expected_digest": {"type": "string", "required": True},
        },
        "result": "personal.context.v1#context.update.result",
    },
    "personal.memory.v1#person.update": {
        "operation": "execute", "confirmation_required": False,
        "input": {
            "person_id": {"type": "string", "required": True},
            "display_name": {"type": "string", "required": True},
            "summary": {"type": "string", "required": True},
            "aliases": {"type": "string_list", "required": True},
            "source_refs": {"type": "string_list", "required": True},
            "expected_digest": {"type": "string", "required": True},
        },
        "result": "personal.memory.v1#person.update.result",
    },
    "personal.memory.v1#memory.update": {
        "operation": "execute", "confirmation_required": False,
        "input": {
            "memory_id": {"type": "string", "required": True},
            "title": {"type": "string", "required": True},
            "summary": {"type": "string", "required": True},
            "memory_kind": {"type": "string", "required": True},
            "person_ids": {"type": "string_list", "required": True},
            "context_ids": {"type": "string_list", "required": True},
            "source_refs": {"type": "string_list", "required": True},
            "expected_digest": {"type": "string", "required": True},
        },
        "result": "personal.memory.v1#memory.update.result",
    },
    "personal.memory.v1#memory.review": {
        "operation": "execute", "confirmation_required": True,
        "input": {
            "memory_id": {"type": "string", "required": True},
            "status": {"type": "string", "required": True, "enum": ["approved", "candidate", "forgotten"]},
            "approval_ref": {"type": "string", "required": True},
            "expected_digest": {"type": "string", "required": True},
        },
        "result": "personal.memory.v1#memory.review.result",
    },
})


PROPOSAL_BUILDERS: dict[str, Callable[[dict[str, object]], dict[str, Any]]] = {
    "communications.mail.v1#triage.propose": build_mail_triage_proposals,
    "personal.inbox.v1#capture.propose": build_inbox_capture_proposals,
    "knowledge.obsidian.v1#note.propose": build_obsidian_note_proposals,
}


def _error(ref: str | None, message: str) -> dict[str, object]:
    return {
        "schema_version": RESPONSE_SCHEMA,
        "ok": False,
        "ref": ref,
        "error": {"code": "invalid_request", "message": message},
    }


def _response(ref: str, operation: str, result: object) -> dict[str, object]:
    return {
        "schema_version": RESPONSE_SCHEMA,
        "ok": True,
        "ref": ref,
        "operation": operation,
        "result": result,
    }


def _request_input(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("input must be an object")
    return value


def _validate_input(value: dict[str, object], contract: dict[str, Any]) -> None:
    fields = contract["input"]
    assert isinstance(fields, dict)
    unexpected = sorted(set(value) - set(fields))
    if unexpected:
        raise ValueError("input contains unsupported fields: " + ", ".join(unexpected))
    for name, schema in fields.items():
        assert isinstance(schema, dict)
        if schema["required"] and name not in value:
            raise ValueError(f"input.{name} is required")
        if name not in value:
            continue
        field_value = value[name]
        field_type = schema["type"]
        if field_type == "string":
            if not isinstance(field_value, str) or (not field_value.strip() and not schema.get("allow_empty")):
                raise ValueError(f"input.{name} must be a non-empty string")
            allowed = schema.get("enum")
            if allowed is not None and field_value not in allowed:
                raise ValueError(f"input.{name} must be one of: {', '.join(allowed)}")
        elif field_type == "string_list":
            if (
                not isinstance(field_value, list)
                or not all(isinstance(item, str) and item.strip() for item in field_value)
            ):
                raise ValueError(f"input.{name} must be a list of non-empty strings")
        elif field_type == "object":
            if not isinstance(field_value, dict):
                raise ValueError(f"input.{name} must be an object")
        elif field_type == "integer":
            if type(field_value) is not int or field_value < schema["minimum"]:
                raise ValueError(f"input.{name} must be an integer >= {schema['minimum']}")
        else:
            raise ValueError(f"input.{name} has an unsupported contract type")


VIEW_ACTIONS = {
    "personal.context.v1#today": [],
    "personal.inbox.v1#recent": ["personal.inbox.v1#capture.propose"],
    "personal.context.v1#contexts": ["personal.context.v1#context.select", "personal.context.v1#context.update"],
    "personal.memory.v1#people": ["personal.memory.v1#person.update"],
    "personal.memory.v1#memories": ["personal.memory.v1#memory.update", "personal.memory.v1#memory.review"],
    "personal.context.v1#proposals": [
        "personal.context.v1#proposal.inspect", "personal.context.v1#proposal.approve", "personal.context.v1#proposal.reject",
        "communications.mail.v1#triage.propose", "personal.inbox.v1#capture.propose",
        "knowledge.obsidian.v1#note.propose", "knowledge.obsidian.v1#note.authorize", "knowledge.obsidian.v1#note.apply",
    ],
}


CREATE_DEFAULTS = {
    "personal.memory.v1#person.update": {"expected_digest": "absent", "aliases": []},
    "personal.memory.v1#memory.update": {"expected_digest": "absent", "person_ids": [], "context_ids": []},
    "personal.inbox.v1#capture.propose": {"item_kind": "note"},
    "knowledge.obsidian.v1#note.propose": {
        "operation": "create", "expected_digest": "absent", "frontmatter": {}, "links": [], "tags": [],
    },
}
COLLECTION_ACTIONS = {
    "personal.context.v1#today": [],
    "personal.context.v1#contexts": [],
    "personal.memory.v1#people": [
        ("personal.memory.v1#person.update", {"zh-CN": "新建人物", "en-US": "New person"}),
    ],
    "personal.memory.v1#memories": [
        ("personal.memory.v1#memory.update", {"zh-CN": "新建记忆", "en-US": "New memory"}),
    ],
    "personal.inbox.v1#recent": [
        ("personal.inbox.v1#capture.propose", {"zh-CN": "新建收集项", "en-US": "New capture"}),
    ],
    "personal.context.v1#proposals": [
        ("communications.mail.v1#triage.propose", {"zh-CN": "邮件分流提案", "en-US": "Mail triage proposal"}),
        ("personal.inbox.v1#capture.propose", {"zh-CN": "收集项提案", "en-US": "Capture proposal"}),
        ("knowledge.obsidian.v1#note.propose", {"zh-CN": "笔记提案", "en-US": "Note proposal"}),
    ],
}


def command_inputs(ref: str) -> dict[str, object]:
    forms = {action_ref: {"input_schema": ACTION_CONTRACTS[action_ref]["input"],
                         "defaults": copy.deepcopy(CREATE_DEFAULTS.get(action_ref, {}))}
             for action_ref in VIEW_ACTIONS[ref]}
    for action_ref, identity in (("personal.memory.v1#person.update", "person_id"),
                                 ("personal.memory.v1#memory.update", "memory_id")):
        if action_ref in forms:
            forms[action_ref]["defaults"][identity] = str(uuid4())
    return forms


def _row_action(ref: str, value: dict[str, object], label_i18n: dict[str, str] | None = None) -> dict[str, object]:
    if ref not in ACTION_CONTRACTS:
        raise ValueError("row action must belong to this package")
    action: dict[str, object] = {"action_ref": ref, "input": value}
    if label_i18n is not None:
        action["label_i18n"] = label_i18n
    return action


def _search_text(value: object) -> str:
    if isinstance(value, dict):
        return "\n".join(_search_text(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(_search_text(item) for item in value)
    return value if isinstance(value, str) else ""


def _collection_data(ref: str, items: list[dict[str, Any]], value: dict[str, Any]) -> dict[str, Any]:
    schema = DATA_CONTRACTS[ref]["input"]
    status = value.get("status", schema["status"]["default"])
    if status == "active":
        active = {"approved", "candidate"} if ref == "personal.memory.v1#memories" else {"staged", "routed"}
        items = [item for item in items if item.get("status") in active]
    elif status != "all":
        items = [item for item in items if item.get("status") == status]
    query = value.get("query", "").strip().casefold()
    if query:
        def matches(item: dict[str, Any]) -> bool:
            fields = {key: item[key] for key in (
                "id", "item_id", "capture_id", "title", "summary", "display_name", "aliases", "label_i18n",
                "summary_i18n", "guidance", "memory_kind", "person_ids", "context_ids", "source_refs",
            ) if key in item}
            proposal = item.get("proposal", {})
            fields.update({key: proposal[key] for key in ("payload", "target", "target_path", "proposal_kind") if key in proposal})
            return query in _search_text(fields).casefold()
        items = [item for item in items if matches(item)]
    offset = value.get("offset", schema["offset"]["default"])
    limit = value.get("limit", schema["limit"]["default"])
    total = len(items)
    page = items[offset:offset + limit]
    forms = command_inputs(ref)
    return {
        "items": page, "count": len(page),
        "pagination": {"offset": offset, "limit": limit, "total": total, "has_more": offset + len(page) < total},
        "collection_actions": [_row_action(action_ref, copy.deepcopy(forms[action_ref]["defaults"]), labels)
                               for action_ref, labels in COLLECTION_ACTIONS[ref]],
        "command_inputs": forms,
    }


MEMORY_REVIEW_LABELS = {
    "approved": {"zh-CN": "确认记忆", "en-US": "Confirm memory"},
    "candidate": {"zh-CN": "保留候选", "en-US": "Keep candidate"},
    "forgotten": {"zh-CN": "忘记记忆", "en-US": "Forget memory"},
}


def _proposal_row(item: dict[str, Any], bindings: list[dict[str, Any]], store: ProposalStore) -> dict[str, Any]:
    identity = {"proposal_id": item["id"], "expected_digest": item["proposal_digest"]}
    actions = [_row_action("personal.context.v1#proposal.inspect", {"proposal_id": item["id"]})]
    if item["status"] == "pending":
        actions += [_row_action(f"personal.context.v1#proposal.{verb}", identity) for verb in ("approve", "reject")]
    if item["status"] == "approved" and item["proposal"]["proposal_kind"] == "knowledge.obsidian.note.v1":
        selected = {"binding_id": bindings[0]["binding_id"]} if len(bindings) == 1 else {}
        actions.append(_row_action("knowledge.obsidian.v1#note.authorize", identity | selected))
        authorization = item.get("external_approval")
        if isinstance(authorization, dict):
            actions.append(_row_action("knowledge.obsidian.v1#note.apply", identity | {
                "binding_id": authorization["binding_id"], "external_approval_ref": authorization["approval_ref"]}))
    return item | {"actions": actions, "preview": store.preview(item)}


def _relay_projection(evidence: dict[str, Any], collection: str) -> list[dict[str, Any]]:
    projected = []
    for raw in evidence["items"]:
        if not isinstance(raw, dict):
            continue
        source_refs = raw.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs or not all(isinstance(ref, str) and ref.strip() for ref in source_refs):
            continue
        identifier = raw.get("id") or raw.get("person_id") or raw.get("memory_id") or raw.get("entity")
        title = raw.get("title") or raw.get("display_name") or raw.get("name") or raw.get("entity") or identifier
        summary = raw.get("summary") or raw.get("statement") or raw.get("content")
        if not isinstance(identifier, (str, int)) or not isinstance(title, str):
            continue
        if collection == "memories" and raw.get("status") not in {"approved", "candidate", "forgotten"}:
            continue
        projected.append({"id": f"relay:{identifier}", "title": title, "summary": summary if isinstance(summary, str) else "",
                          "status": raw.get("status", "approved"), "source_refs": source_refs,
                          "owner_package_id": "opl-relay", "owner_ref": evidence["ref"], "actions": []})
    return projected


def _workspace_read(ref: str, contract: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    store = WorkspaceStore()
    data: dict[str, Any] = {}
    if ref == "personal.context.v1#proposals":
        try:
            bindings = [{"binding_id": identifier, **binding.to_dict()} for identifier, binding in
                        list_resource_bindings(store.paths.workspace).items()
                        if binding.provider_id == "obsidian" and binding.capability_id in {
                            "knowledge.obsidian.v1", "knowledge.documents.v1"} and "notes.write" in binding.scopes]
        except FileNotFoundError:
            bindings = []
        data["bindings"] = bindings
        proposals = ProposalStore(store.paths)
        data.update(_collection_data(ref, proposals.list(), value))
        data["items"] = [_proposal_row(item, bindings, proposals) for item in data["items"]]
    elif ref == "personal.context.v1#contexts":
        items = []
        for item in store.list("contexts"):
            fields = {"context_id": item["id"], "title": item["title"], "summary": item["summary"],
                      "guidance": item["guidance"], "label_i18n": item.get("label_i18n", {}),
                      "source_refs": item["source_refs"], "expected_digest": item["digest"]}
            items.append(item | {"actions": [_row_action("personal.context.v1#context.select", {"context_id": item["id"]}),
                                               _row_action("personal.context.v1#context.update", fields)]})
        data["active_context"] = store.context(value.get("context_id"), value.get("person_id"))
        relay = store.relay("search", entity=value.get("person_id", ""))
        data["relay"] = {key: item for key, item in relay.items() if key != "items"}
        mail_memories = [item for item in _relay_projection(relay, "memories") if item["status"] == "approved"]
        data["active_context"]["mail_memories"] = mail_memories
        data["active_context"]["source_refs"] = list(dict.fromkeys(data["active_context"]["source_refs"] + [
            source for item in mail_memories for source in item["source_refs"]]))
    elif ref == "personal.memory.v1#people":
        items = []
        memories = store.list("memories", status="approved")
        for item in store.list("people"):
            fields = {"person_id": item["id"], "display_name": item["display_name"], "summary": item["summary"],
                      "aliases": item["aliases"], "source_refs": item["source_refs"], "expected_digest": item["digest"]}
            items.append(item | {"owner_package_id": "opl-persona", "memories": [memory for memory in memories if item["id"] in memory["person_ids"]],
                                 "actions": [_row_action("personal.memory.v1#person.update", fields)]})
        relay = store.relay("people")
        items += _relay_projection(relay, "people")
        data["relay"] = {key: item for key, item in relay.items() if key != "items"}
    else:
        items = []
        for item in store.list("memories"):
            fields = {key: item[key] for key in ("title", "summary", "memory_kind", "person_ids", "context_ids", "source_refs")}
            fields.update(memory_id=item["id"], expected_digest=item["digest"])
            actions = [_row_action("personal.memory.v1#memory.update", fields)]
            actions += [_row_action("personal.memory.v1#memory.review", {"memory_id": item["id"], "status": decision,
                        "expected_digest": item["digest"]}, MEMORY_REVIEW_LABELS[decision])
                        for decision in ("approved", "candidate", "forgotten") if decision != item["status"]]
            items.append(item | {"owner_package_id": "opl-persona", "actions": actions})
        relay = store.relay("search")
        items += _relay_projection(relay, "memories")
        data["relay"] = {key: item for key, item in relay.items() if key != "items"}
        data["memory_policy"] = "approved_only_for_context"
    if ref != "personal.context.v1#proposals":
        data.update(_collection_data(ref, items, value))
    return {"kind": "data", "state": "ready", "result_schema": contract["result"], "input_schema": contract["input"], "data": data}


def _inbox_read(ref: str, contract: dict[str, Any], value: dict[str, Any], *, active_only: bool = False) -> dict[str, object]:
    items = InboxStore.from_paths(PersonaPaths.resolve()).list()
    if active_only:
        items = [item for item in items if item.status in {"staged", "routed"}]
    projected_items = [item.to_dict() for item in items]
    return {
        "kind": "data",
        "state": "ready",
        "result_schema": contract["result"],
        "input_schema": contract["input"],
        "data": {
            **_collection_data(ref, projected_items, value),
            "source_policy": "persona_private_refs_only",
        },
    }


def _execute(ref: str, contract: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    builder = PROPOSAL_BUILDERS.get(ref)
    if builder is not None:
        return _proposal_result(contract, ProposalStore().persist_bundle(builder(value)))
    proposals = ProposalStore()
    workspace = WorkspaceStore()
    if ref == "personal.context.v1#proposal.inspect":
        item = proposals.inspect(**value)
    elif ref in {"personal.context.v1#proposal.approve", "personal.context.v1#proposal.reject"}:
        item = proposals.review(**value, decision="approved" if ref.endswith("approve") else "rejected")
    elif ref == "knowledge.obsidian.v1#note.apply":
        item = proposals.apply_obsidian(**value)
    elif ref == "knowledge.obsidian.v1#note.authorize":
        item = proposals.authorize_obsidian(**value)
    elif ref == "personal.context.v1#context.select":
        item = workspace.select_context(**value)
    elif ref == "personal.context.v1#context.update":
        item = workspace.update_context(**value)
    elif ref == "personal.memory.v1#person.update":
        item = workspace.update_person(**value)
    elif ref == "personal.memory.v1#memory.update":
        item = workspace.update_memory(**value)
    elif ref == "personal.memory.v1#memory.review":
        item = workspace.review_memory(**value)
    else:
        raise ValueError("no handler for declared action")
    return {"kind": "action", "status": item.get("status", "ready"), "item": item,
            "confirmation_required": contract["confirmation_required"], "result_schema": contract["result"],
            "execution_policy": "obsidian_owner_apply" if ref.endswith("note.apply") else "persona_local_only"}


def _proposal_result(contract: dict[str, Any], proposal_bundle: dict[str, Any]) -> dict[str, object]:
    return {
        "kind": "proposal",
        "status": "proposed",
        "confirmation_required": contract["confirmation_required"],
        "input_schema": contract["input"],
        "result_schema": contract["result"],
        "execution_policy": "proposal_only",
        "proposal_bundle": proposal_bundle,
    }


def handle_request(request: object) -> tuple[int, dict[str, object]]:
    ref: str | None = None
    try:
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        raw_ref = request.get("ref")
        if isinstance(raw_ref, str):
            ref = raw_ref
        unexpected = sorted(set(request) - {"schema_version", "operation", "ref", "input"})
        if unexpected:
            raise ValueError("request contains unsupported fields: " + ", ".join(unexpected))
        if request.get("schema_version") != REQUEST_SCHEMA:
            raise ValueError(f"schema_version must be {REQUEST_SCHEMA}")
        operation = request.get("operation")
        if operation not in {"describe", "read", "execute"}:
            raise ValueError("operation must be describe, read, or execute")
        if not ref:
            raise ValueError("ref must be a non-empty string")

        data_contract = DATA_CONTRACTS.get(ref)
        action_contract = ACTION_CONTRACTS.get(ref)
        if data_contract is None and action_contract is None:
            raise ValueError("ref is not declared by this package")

        if operation == "describe":
            if "input" in request:
                raise ValueError("describe does not accept input")
            return 0, _response(
                ref,
                operation,
                {
                    "abi": ABI_SCHEMA,
                    "request_schema": REQUEST_SCHEMA,
                    "response_schema": RESPONSE_SCHEMA,
                    "ref": ref,
                    "operations": [
                        contract
                        for contract in (data_contract, action_contract)
                        if contract is not None
                    ],
                },
            )

        contract = data_contract if operation == "read" else action_contract
        if contract is None:
            raise ValueError(f"{ref} does not support {operation}")
        value = _request_input(request.get("input"))
        _validate_input(value, contract)
        if operation == "read":
            result = (
                _inbox_read(ref, contract, value, active_only=ref == "personal.context.v1#today")
                if ref in {"personal.context.v1#today", "personal.inbox.v1#recent"}
                else _workspace_read(ref, contract, value)
            )
        else:
            result = _execute(ref, contract, value)
        return 0, _response(ref, operation, result)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        return 2, _error(ref, str(exc))
