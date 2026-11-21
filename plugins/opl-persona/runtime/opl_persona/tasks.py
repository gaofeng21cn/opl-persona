"""Continue one approved plan across Persona's existing proposal owners and local tools."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager

from .browser_tools import Browser
from .local_tools import Desktop, ToolPaused, browser_tab_id, desktop_input_lane, normalize_action, strict_object
from .paths import PersonaPaths
from .proposals import ProposalStore
from .workspace import atomic_json, item_digest, now, refs, text


TASKS_REF = "personal.context.v1#tasks"
TASK_ACTIONS = {verb: f"personal.context.v1#task.{verb}" for verb in ("prepare", "inspect", "run", "check")}
TASK_STATUSES = ("ready", "waiting", "needs-check", "complete")


def _task_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("task_id must be 1–64 letters, digits, hyphens or underscores")
    return value


def _step(value):
    value = strict_object(value, required=("kind", "title", "input"))
    kind = value["kind"]
    if kind == "proposal":
        linked = strict_object(value["input"], required=("proposal_id", "expected_digest"))
        payload = {key: text(item, key, 2048) for key, item in linked.items()}
    elif kind in ("fill", "submit"):
        payload = normalize_action(kind, value["input"])
    else:
        raise ValueError("steps must link an existing proposal, fill a field, or submit a reviewed form")
    return {"kind": kind, "title": text(value["title"], "step title", 256), "input": payload}


class TaskStore:
    def __init__(self, paths=None, *, desktop=Desktop, input_lane=desktop_input_lane, browser=Browser):
        self.paths = paths or PersonaPaths.resolve()
        self.root = self.paths.data_root / "tasks"
        self.proposals = ProposalStore(self.paths)
        self.desktop = desktop
        self.input_lane = input_lane
        self.browser = browser

    @contextmanager
    def _adapter(self, payload):
        session = payload["target"].get("browser_session")
        if session:
            browser = self.browser(self.paths, session)
            with browser.lane():
                yield browser, Browser.provider
        else:
            with self.input_lane():
                yield self.desktop(), "agent-desktop"

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
        steps = [_step(value) for value in raw_steps]
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
                if step["kind"] == "proposal":
                    proposal = step["input"]
                else:
                    identifier = f"persona-proposal://task/{task_id}/{digest[7:]}/{index + 1}"
                    target = step["input"]["target"]
                    stored = self.proposals.persist_bundle({"proposals": [{
                        "schema_version": "opl-persona-proposal.v1",
                        "proposal_id": identifier,
                        "proposal_kind": "personal.local-tools.v1",
                        "target": target.get("page_url") or target["app"],
                        "operation": step["kind"],
                        "source_refs": source_refs,
                        "payload": {"title": step["title"], "task_id": task_id, "plan_digest": digest,
                                    "step": index + 1, **step["input"]},
                        "approval": {"status": "pending", "required": True, "external_write_allowed": False},
                    }]})["stored_items"][0]
                    proposal = {"proposal_id": identifier, "expected_digest": stored["proposal_digest"]}
                session = step["input"].get("target", {}).get("browser_session")
                linked.append({"kind": step["kind"], "title": step["title"], "proposal": proposal,
                               "state": "ready", "attempts": 0,
                               **({"browser_session": session} if session else {})})
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
        record["updated_at"] = now()
        atomic_json(path, record)
        return self._project(record)

    def _require_browser_readback(self, session):
        # The browser lock makes this observation consistent with dispatch and readback.
        # The existing task file is the durable receipt, including after process loss.
        for path in self.root.glob("*.json"):
            record = self._load(path)
            step = self._current(record)
            if step and step.get("browser_session") == session and step["state"] == "attempted":
                raise ToolPaused(f"Check the result of task {record['id']} before continuing in this browser session.")

    def _readback(self, path, record, step, adapter, provider, payload):
        if adapter.verified(step["kind"], payload):
            target = payload["result"] if step["kind"] == "submit" else payload["target"]
            return self._change(path, record, step, state="verified",
                                receipt={"provider": provider, "target_digest": item_digest(target),
                                         "observation": "receipt-visible" if step["kind"] == "submit" else "field-matches"})
        return self._change(path, record, step, blocked="The expected result is not visible. Inspect the original target.")

    def check(self, *, task_id, window=None, tab_id=None):
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
            payload = item["proposal"]["payload"]
            key = "result" if step["kind"] == "submit" else "target"
            original = payload[key]
            if tab_id is not None:
                if window is not None or "browser_session" not in original:
                    raise ValueError("A replacement tab requires the original browser session")
                payload = {**payload, key: {**original, "tab_id": browser_tab_id(tab_id)}}
            if window is not None:
                window = strict_object(window, required=("window_id", "process_instance"))
                # A new process/window can supply readback of an exact site/account.
                # It does not inherit the original permission to deliver input.
                if "page_url" not in original or "browser_session" in original:
                    raise ValueError("Readback in a replacement window requires the original portal URL and account")
                replacement = {**original, **{key: text(value, key, 128) for key, value in window.items()}}
                payload = {**payload, key: replacement}
            try:
                with self._adapter(payload) as (adapter, provider):
                    return self._readback(path, record, step, adapter, provider, payload)
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
            kind = step["kind"]
            try:
                with self._adapter(payload) as (adapter, provider):
                    if step.get("browser_session"):
                        self._require_browser_readback(step["browser_session"])
                    ref = adapter.preflight(kind, payload)
                    if ref is None:
                        return self._readback(path, record, step, adapter, provider, payload)
                    step["attempts"] += 1
                    self._change(path, record, step, state="attempted")
                    if adapter.dispatch(kind, ref, payload) is False:
                        return self._change(path, record, step, state="ready",
                                            blocked="The tool reported that input was not delivered. Verify the target before continuing.")
                    return self._readback(path, record, step, adapter, provider, payload)
            except ToolPaused as exc:
                return self._change(path, record, step, blocked=str(exc))
