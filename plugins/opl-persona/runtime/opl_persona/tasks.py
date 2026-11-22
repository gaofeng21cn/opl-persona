"""Continue one approved plan across Persona's existing proposal owners and local tools."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from uuid import uuid4

from .paths import PersonaPaths
from .proposals import ProposalStore
from .tool_registry import ToolRegistry
from .tools.contract import ToolPaused, strict_object
from .primitives import atomic_json, item_digest, text
from .workspace import now, refs


TASKS_REF = "personal.context.v1#tasks"
TASK_ACTIONS = {verb: f"personal.context.v1#task.{verb}" for verb in ("prepare", "inspect", "run", "check")}
TASK_STATUSES = ("ready", "waiting", "needs-check", "complete")


def _task_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("task_id must be 1–64 letters, digits, hyphens or underscores")
    return value


def _step(value, tools):
    value = strict_object(value, required=("kind", "title", "input"))
    kind = value["kind"]
    if kind == "proposal":
        linked = strict_object(value["input"], required=("proposal_id", "expected_digest"))
        payload = {key: text(item, key, 2048) for key, item in linked.items()}
    else:
        payload = tools.normalize(kind, value["input"])
    return {"kind": kind, "title": text(value["title"], "step title", 256), "input": payload}


class TaskStore:
    def __init__(self, paths=None, *, tools=None):
        self.paths = paths or PersonaPaths.resolve()
        self.root = self.paths.data_root / "tasks"
        self.proposals = ProposalStore(self.paths)
        self.tools = tools or ToolRegistry(self.paths)

    def _path(self, task_id):
        return self.root / f"{_task_id(task_id)}.json"

    @contextmanager
    def _owner(self, task_id):
        # A process may die while holding a task. The OS releases its ownership;
        # the last persisted operation state is retained.
        if os.name != "posix":
            raise ValueError("Resumable tasks require a POSIX host")
        import fcntl

        path = self._path(task_id)
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd = os.open(path.with_suffix(".lock"), os.O_NOFOLLOW | os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, "ab") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("The task already has an active executor") from exc
            yield path

    def _load(self, path):
        if not path.is_file():
            raise ValueError("Task does not exist in this Profile")
        return json.loads(path.read_text(encoding="utf-8"))

    def _proposal(self, step):
        linked = step["proposal"]
        item = self.proposals.inspect(linked["proposal_id"])
        if item["proposal_digest"] != linked["expected_digest"]:
            raise ValueError("The linked proposal changed. Review a new task plan for the new revision.")
        return item

    def prepare(self, *, task_id, title, plan):
        plan = strict_object(plan, required=("source_refs", "steps"))
        source_refs = refs(plan["source_refs"])
        raw_steps = plan["steps"]
        if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 40:
            raise ValueError("A task needs between 1 and 40 ordered steps")
        steps = [_step(value, self.tools) for value in raw_steps]
        plan = {"id": _task_id(task_id), "title": text(title, "title", 256),
                "source_refs": source_refs, "steps": steps}
        digest = item_digest(plan)
        with self._owner(task_id) as path:
            if path.exists():
                record = self._load(path)
                if digest != record["plan_digest"]:
                    raise ValueError("The task ID already names a different plan")
                return self._project(record)
            linked = []
            # Complete local validation first so bad input does not leave a partial plan.
            for step in steps:
                if step["kind"] == "proposal":
                    item = self._proposal({"proposal": step["input"]})
                    if item["proposal"]["proposal_kind"] == "personal.local-tools.v1":
                        raise ValueError("Local tool actions must be prepared as their own step")
            for index, step in enumerate(steps):
                route = {}
                if step["kind"] == "proposal":
                    proposal = step["input"]
                else:
                    identifier = f"persona-proposal://task/{task_id}/{digest[7:]}/{index + 1}"
                    operation_id = uuid4().hex
                    operation = self.tools.resolve(step["kind"], step["input"], operation_id)
                    route = {"tool_lane": operation.lane, "operation_id": operation_id}
                    stored = self.proposals.persist_bundle({"proposals": [{
                        "schema_version": "opl-persona-proposal.v1",
                        "proposal_id": identifier,
                        "proposal_kind": "personal.local-tools.v1",
                        "target": operation.target,
                        "operation": step["kind"],
                        "source_refs": source_refs,
                        "payload": {"title": step["title"], "task_id": task_id, "plan_digest": digest,
                                    "step": index + 1, **step["input"]},
                        "approval": {"status": "pending", "required": True, "external_write_allowed": False},
                    }]})["stored_items"][0]
                    proposal = {"proposal_id": identifier, "expected_digest": stored["proposal_digest"]}
                linked.append({"kind": step["kind"], "title": step["title"], "proposal": proposal,
                               "state": "ready", "attempts": 0, **route})
            record = {"schema_version": "opl-persona-task.v1", "id": task_id, "title": plan["title"],
                      "source_refs": source_refs, "plan_digest": digest, "steps": linked,
                      "created_at": now(), "updated_at": now()}
            atomic_json(path, record)
            return self._project(record)

    @staticmethod
    def _current(record):
        return next((step for step in record["steps"] if step["state"] != "verified"), None)

    def _project(self, record):
        step = self._current(record)
        status = "complete"
        if step is not None:
            if step["state"] == "attempted":
                status = "needs-check"
            elif step["kind"] == "proposal" or step.get("blocked_reason"):
                status = "waiting"
            else:
                status = "ready"
        summary = "All steps verified"
        if step:
            summary = step.get("blocked_reason") or step["title"]
        return {**record, "status": status, "current_step": step, "summary": summary}

    def list(self):
        records = (self._load(path) for path in self.root.glob("*.json"))
        return [self._project(record) for record in sorted(records, key=lambda r: (r["updated_at"], r["id"]), reverse=True)]

    def inspect(self, *, task_id):
        return self._project(self._load(self._path(task_id)))

    def _change(self, path, record, step, *, state=None, blocked=None, receipt=None):
        if state:
            step["state"] = state
        if blocked:
            step["blocked_reason"] = blocked
        else:
            step.pop("blocked_reason", None)
        if receipt:
            step["receipt"] = {"observed_at": now(), **receipt}
            step.pop("pending_readback", None)
        record["updated_at"] = now()
        atomic_json(path, record)
        return self._project(record)

    def _require_readback(self, lane):
        # The provider lock serializes this check with dispatch for the same lane.
        for path in self.root.glob("*.json"):
            record = self._load(path)
            step = self._current(record)
            if not step or step["state"] != "attempted":
                continue
            pending_lane = step.get("tool_lane")
            if pending_lane is None and step.get("browser_session"):
                pending_lane = "browser:" + step["browser_session"]
            if pending_lane == lane:
                raise ToolPaused(f"Check the result of task {record['id']} before continuing on this tool.")

    def _readback(self, path, record, step, operation, driver):
        observed = operation.readback(driver)
        if observed is None:
            return self._change(path, record, step, blocked="The expected result is not visible. Inspect the original target.")
        if observed.not_delivered:
            return self._change(path, record, step, state="ready",
                                blocked="The connector confirmed non-delivery. Review the original step before retrying.")
        proof = {"provider": operation.provider, "target_digest": item_digest(observed.target),
                 "observation": observed.observation}
        if observed.evidence is not None:
            proof["evidence"] = observed.evidence
            proof["operation_id"] = step["operation_id"]
        if observed.review_required:
            step["pending_readback"] = proof
            return self._change(path, record, step, blocked="Review the observed result before accepting it.")
        return self._change(path, record, step, state="verified", receipt=proof)

    def _confirm_readback(self, path, record, step, review):
        review = strict_object(review, required=("operation_id", "digest", "confirmation"))
        proof = step.get("pending_readback")
        if (not proof or review["confirmation"] != "confirmed" or review["operation_id"] != proof["operation_id"]
                or review["digest"] != proof["evidence"]["digest"]):
            raise ValueError("Confirm the current observed image and original operation")
        payload = self._proposal(step)["proposal"]["payload"]
        operation = self.tools.resolve(step["kind"], payload, step["operation_id"])
        with self.tools.bind(operation) as driver:
            driver.confirm_readback(proof["evidence"])
        return self._change(path, record, step, state="verified", receipt=proof | {"human_reviewed": True})

    def check(self, *, task_id, window=None, tab_id=None, review=None):
        with self._owner(task_id) as path:
            record = self._load(path)
            step = self._current(record)
            if step is None:
                return self._project(record)
            item = self._proposal(step)
            if step["kind"] == "proposal":
                if item["status"] == "applied" and isinstance(item.get("receipt"), dict) and item["receipt"]:
                    return self._change(path, record, step, state="verified", receipt={
                        "provider": "proposal-owner", "proposal_id": item["id"],
                        "owner_receipt_digest": item_digest(item["receipt"]),
                    })
                return self._change(path, record, step, blocked="Complete this step through the linked proposal owner and check again.")
            if step["state"] != "attempted":
                return self._project(record)
            if review is not None:
                if window is not None or tab_id is not None:
                    raise ValueError("Review the observed result separately from changing its readback target")
                return self._confirm_readback(path, record, step, review)
            payload = item["proposal"]["payload"]
            operation = self.tools.resolve(step["kind"], payload, step.get("operation_id"), window=window, tab_id=tab_id)
            try:
                with self.tools.bind(operation) as driver:
                    return self._readback(path, record, step, operation, driver)
            except ToolPaused as exc:
                return self._change(path, record, step, blocked=str(exc))

    def run(self, *, task_id, proposal_id, expected_digest, confirmation):
        if confirmation != "confirmed":
            raise ValueError("Confirm the exact reviewed step before delivering input")
        with self._owner(task_id) as path:
            record = self._load(path)
            step = self._current(record)
            if step is None or step["kind"] == "proposal":
                raise ValueError("No local tool step is ready")
            if step["state"] != "ready":
                raise ValueError("Check the result of the original operation before continuing")
            if step["proposal"] != {"proposal_id": proposal_id, "expected_digest": expected_digest}:
                raise ValueError("The confirmation must identify the current proposal and digest")
            item = self._proposal(step)
            if item["status"] != "approved":
                raise ValueError("Review and approve the exact step proposal first")
            payload = item["proposal"]["payload"]
            operation = self.tools.resolve(step["kind"], payload, step.get("operation_id"))
            try:
                with self.tools.bind(operation) as driver:
                    self._require_readback(operation.lane)
                    ref = driver.preflight(operation.action, operation.args)
                    if ref is None:
                        return self._readback(path, record, step, operation, driver)
                    step["attempts"] += 1
                    self._change(path, record, step, state="attempted")
                    if driver.dispatch(operation.action, ref, operation.args) is False:
                        return self._change(path, record, step, state="ready",
                                            blocked="The tool reported that input was not delivered. Verify the target before continuing.")
                    return self._readback(path, record, step, operation, driver)
            except ToolPaused as exc:
                return self._change(path, record, step, blocked=str(exc))
