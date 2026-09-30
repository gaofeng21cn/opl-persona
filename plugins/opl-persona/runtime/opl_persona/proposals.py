"""Persistent, digest-bound proposal review and narrowly scoped owner apply."""

from __future__ import annotations

import copy
import json
from typing import Any

from .approvals import APPROVAL_SCHEMA_VERSION, approve_proposal, proposal_digest
from .bindings import binding_file_root, load_resource_binding
from .inbox import InboxStore
from .obsidian_apply import apply_approved_obsidian_note
from .paths import PersonaPaths
from .workspace import atomic_json, now, refs, text, workspace_lock


STORE_SCHEMA = "opl-persona-proposal-store.v1"


class ProposalStore:
    def __init__(self, paths: PersonaPaths | None = None) -> None:
        self.paths = paths or PersonaPaths.resolve()
        self.path = self.paths.data_root / "proposals.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": STORE_SCHEMA, "items": []}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("schema_version") != STORE_SCHEMA
                or not isinstance(value.get("items"), list)):
            raise ValueError("invalid Persona proposal store")
        for item in value["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("proposal"), dict):
                raise ValueError("invalid persisted proposal")
            if item.get("proposal_digest") != proposal_digest(item["proposal"]):
                raise ValueError("persisted proposal digest mismatch")
        return value

    @staticmethod
    def _item(state: dict[str, Any], proposal_id: str, expected_digest: str | None = None) -> dict[str, Any]:
        item = next((item for item in state["items"] if item["id"] == proposal_id), None)
        if item is None:
            raise ValueError("unknown proposal_id")
        if expected_digest is not None and item["proposal_digest"] != expected_digest:
            raise ValueError("expected_digest does not match current proposal")
        return item

    def list(self) -> list[dict[str, Any]]:
        with workspace_lock(self.paths):
            return copy.deepcopy(self._load()["items"])

    def inspect(self, proposal_id: str) -> dict[str, Any]:
        with workspace_lock(self.paths):
            return copy.deepcopy(self._item(self._load(), proposal_id))

    def persist_bundle(self, bundle: dict[str, Any]) -> dict[str, Any]:
        proposals = bundle.get("proposals")
        if not isinstance(proposals, list) or not proposals:
            raise ValueError("bundle must contain proposals")
        prepared = []
        for proposal in proposals:
            if not isinstance(proposal, dict) or proposal.get("schema_version") != "opl-persona-proposal.v1":
                raise ValueError("invalid proposal schema")
            identifier = text(proposal.get("proposal_id"), "proposal_id", 2048)
            source_refs = refs(proposal.get("source_refs"))
            approval = proposal.get("approval")
            if not isinstance(approval, dict) or approval != {"status": "pending", "required": True, "external_write_allowed": False}:
                raise ValueError("new proposals must be pending with no external write authority")
            payload = proposal.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("proposal payload must be an object")
            title = payload.get("title") or proposal.get("target_path") or proposal["proposal_kind"]
            summary = payload.get("summary") or proposal.get("operation", "propose") + " -> " + proposal["target"]
            prepared.append({"id": identifier, "title": title, "summary": summary, "status": "pending",
                             "source_refs": source_refs, "proposal_digest": proposal_digest(proposal),
                             "proposal": copy.deepcopy(proposal), "approval": copy.deepcopy(approval),
                             "receipt": None, "created_at": now(), "updated_at": now()})
        with workspace_lock(self.paths):
            state = self._load()
            stored = []
            for item in prepared:
                previous = next((old for old in state["items"] if old["id"] == item["id"]), None)
                if previous:
                    if previous["proposal_digest"] != item["proposal_digest"]:
                        # Stable builder IDs can name changed candidates, never changed approvals.
                        if previous["status"] != "pending":
                            raise ValueError("reviewed proposal identity changed; use a new proposal identity")
                        item["created_at"] = previous["created_at"]
                    else:
                        item = previous
                    state["items"] = [old for old in state["items"] if old["id"] != item["id"]]
                state["items"].append(item)
                stored.append(item)
            atomic_json(self.path, state)
            # Inbox staging is local, not a cross-domain permission or an external apply.
            inbox = InboxStore.from_paths(self.paths)
            for item in stored:
                if item["proposal"]["proposal_kind"] == "personal.inbox.v1.capture":
                    if item["status"] == "pending":
                        inbox.capture_proposal(item["proposal"])
            result = copy.deepcopy(bundle)
            result["proposals"] = [copy.deepcopy(item["proposal"]) for item in stored]
            result["stored_items"] = copy.deepcopy(stored)
            return result

    def review(self, *, proposal_id: str, approval_ref: str, expected_digest: str,
               decision: str) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("unsupported proposal decision")
        approval_ref = text(approval_ref, "approval_ref", 2048)
        if approval_ref.startswith(("proposal://", "persona-proposal://")):
            raise ValueError("approval_ref must identify a user review, not a proposal")
        with workspace_lock(self.paths):
            state = self._load()
            item = self._item(state, proposal_id, expected_digest)
            if item["status"] != "pending":
                if item["status"] == decision and item["approval"].get("approval_ref") == approval_ref:
                    return copy.deepcopy(item)
                raise ValueError("proposal is already reviewed")
            if decision == "approved":
                item["proposal"] = approve_proposal(item["proposal"], approval_ref=approval_ref)
                item["approval"] = copy.deepcopy(item["proposal"]["approval"])
            else:
                item["approval"] = {"schema_version": APPROVAL_SCHEMA_VERSION, "status": "rejected", "required": True,
                                    "external_write_allowed": False, "approval_ref": approval_ref,
                                    "proposal_id": proposal_id, "proposal_digest": expected_digest}
                item["proposal"]["approval"] = copy.deepcopy(item["approval"])
            item["status"] = decision
            item["updated_at"] = now()
            atomic_json(self.path, state)
            return copy.deepcopy(item)

    def authorize_obsidian(self, *, proposal_id: str, expected_digest: str, binding_id: str,
                           approval_ref: str, confirmation: str) -> dict[str, Any]:
        if confirmation != "confirmed":
            raise ValueError("external write authorization requires explicit confirmation")
        approval_ref = text(approval_ref, "approval_ref", 2048)
        if approval_ref.startswith(("proposal://", "persona-proposal://")):
            raise ValueError("approval_ref must identify a user approval")
        with workspace_lock(self.paths):
            state = self._load()
            item = self._item(state, proposal_id, expected_digest)
            if item["status"] != "approved" or item["proposal"]["proposal_kind"] != "knowledge.obsidian.note.v1":
                raise ValueError("only an approved Obsidian note can receive external authorization")
            if approval_ref == item["approval"].get("approval_ref"):
                raise ValueError("external approval must be separate from proposal review")
            binding = load_resource_binding(self.paths.workspace, binding_id)
            binding_file_root(binding, provider_id="obsidian", capability_ids={"knowledge.obsidian.v1", "knowledge.documents.v1"},
                              required_scope="notes.write")
            item["external_approval"] = {
                "schema_version": APPROVAL_SCHEMA_VERSION, "status": "approved", "required": True,
                "external_write_allowed": True, "approval_ref": approval_ref, "proposal_id": proposal_id,
                "proposal_digest": expected_digest, "binding_id": binding_id, "provider_id": binding.provider_id,
                "capability_id": binding.capability_id, "resource_ref": binding.resource_ref, "scope": "notes.write",
            }
            item["updated_at"] = now()
            atomic_json(self.path, state)
            return copy.deepcopy(item)

    def apply_obsidian(self, *, proposal_id: str, expected_digest: str, binding_id: str,
                       external_approval: dict[str, Any] | None = None,
                       external_approval_ref: str | None = None) -> dict[str, Any]:
        with workspace_lock(self.paths):
            state = self._load()
            item = self._item(state, proposal_id, expected_digest)
            if item["status"] not in {"approved", "applied"}:
                raise ValueError("proposal must first be approved")
            if (external_approval is None) == (external_approval_ref is None):
                raise ValueError("supply exactly one external_approval or external_approval_ref")
            if external_approval_ref is not None:
                external_approval = item.get("external_approval")
                if not isinstance(external_approval, dict) or external_approval.get("approval_ref") != external_approval_ref:
                    raise ValueError("external_approval_ref does not identify the stored approval")
            if not isinstance(external_approval, dict):
                raise ValueError("external_approval must be an object")
            binding = load_resource_binding(self.paths.workspace, binding_id)
            if (external_approval.get("binding_id") != binding_id
                    or external_approval.get("capability_id") != binding.capability_id
                    or external_approval.get("provider_id") != binding.provider_id
                    or external_approval.get("resource_ref") != binding.resource_ref
                    or external_approval.get("scope") != "notes.write"):
                raise ValueError("external approval must bind the exact Obsidian resource capability and notes.write scope")
            if external_approval.get("approval_ref") == item["approval"].get("approval_ref"):
                raise ValueError("external approval must be separate from proposal review")
            if (external_approval.get("status") != "approved" or external_approval.get("external_write_allowed") is not True
                    or external_approval.get("proposal_id") != proposal_id
                    or external_approval.get("proposal_digest") != expected_digest):
                raise ValueError("external approval must authorize the exact proposal digest")
            if item["status"] == "applied":
                raise ValueError("proposal already applied; inspect its persisted receipt")
            receipt = apply_approved_obsidian_note(item["proposal"], external_approval, binding=binding)
            item["status"] = "applied"
            item["receipt"] = receipt
            item["external_approval"] = copy.deepcopy(external_approval)
            item["updated_at"] = now()
            atomic_json(self.path, state)
            return copy.deepcopy(item)
