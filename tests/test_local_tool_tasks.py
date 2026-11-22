from contextlib import nullcontext
import json
import os
import subprocess
import sys

import pytest

from opl_persona.bindings import set_resource_binding
from opl_persona.core import build_obsidian_note_proposals
from opl_persona.paths import PersonaPaths
from opl_persona.tasks import TaskStore
from opl_persona.tool_registry import ToolRegistry
from opl_persona.tools.contract import ToolPaused, normalize_desktop_target, normalize_form
from opl_persona.tools.desktop import Desktop


TARGET = {"app": "Test Browser", "window_id": "w-1", "process_instance": "test-process",
          "marker": "Conference form 41", "account_marker": "Signed in as Test Scholar",
          "page_url": "https://portal.example.test/form/41"}
FILL = {"kind": "fill", "title": "Fill the title", "input": {
    "target": TARGET, "field": "Title", "before": "", "value": "Evidence and interpretation",
}}
SUBMIT = {"kind": "submit", "title": "Submit the form", "input": {
    "target": TARGET, "button": "Submit", "fields": {"Title": FILL["input"]["value"]},
    "result": {**TARGET, "marker": "Receipt for form 41", "page_url": "https://portal.example.test/receipt/41"},
}}


@pytest.fixture
def profile(monkeypatch, tmp_path):
    root = tmp_path / "profile"
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(root))
    return PersonaPaths.resolve()


def prepare(store, *steps):
    return store.prepare(task_id="form-41", title="Conference application", plan={
        "source_refs": ["email-store://fixture/41"], "steps": list(steps),
    })


def approve(store, item):
    current = item["current_step"]["proposal"]
    store.proposals.review(**current, approval_ref="approval://synthetic/approve", decision="approved")
    return {"task_id": item["id"], "confirmation": "confirmed", **current}


def test_changed_window_or_missing_approval_leaves_the_step_ready(profile):
    class Background:
        def preflight(self, *args):
            raise ToolPaused("The selected window moved to the background")

    store = TaskStore(profile, tools=ToolRegistry(profile, desktop=Background, input_lane=nullcontext))
    item = prepare(store, FILL)
    with pytest.raises(ValueError, match="approve"):
        store.run(task_id=item["id"], confirmation="confirmed", **item["current_step"]["proposal"])
    result = store.run(**approve(store, item))
    assert result["status"] == "waiting"
    assert result["current_step"]["attempts"] == 0


def test_interrupted_submit_resumes_same_proposal_and_projects_owner_receipt(profile, tmp_path):
    root = tmp_path / "knowledge"
    root.mkdir()
    set_resource_binding(profile.workspace, binding_id="notes", capability_id="knowledge.obsidian.v1",
                         provider_id="obsidian", resource_ref=root.as_uri(), scopes=["notes.read", "notes.write"])
    store = TaskStore(profile)
    note = store.proposals.persist_bundle(build_obsidian_note_proposals({
        "operation": "create", "target_path": "application.md", "expected_digest": "absent",
        "frontmatter": {}, "body": "The conference system issued receipt 41.", "tags": [], "links": [],
        "evidence_refs": ["https://portal.example.test/receipt/41"],
    }))["stored_items"][0]
    note_step = {"kind": "proposal", "title": "Retain the outcome in Obsidian", "input": {
        "proposal_id": note["id"], "expected_digest": note["proposal_digest"],
    }}
    item = prepare(store, SUBMIT, note_step)
    arguments = approve(store, item)
    portal = tmp_path / "portal-receipt"
    adapter = """
import json
import os
from contextlib import nullcontext
from pathlib import Path
from opl_persona.paths import PersonaPaths
from opl_persona.tasks import TaskStore
from opl_persona.tool_registry import ToolRegistry

class Portal:
    def preflight(self, *args):
        return '@s0:e1'
    def dispatch(self, *args):
        with Path(os.environ['PERSONA_TEST_PORTAL']).open('x') as handle:
            handle.write('receipt-41')
        os._exit(84)
paths = PersonaPaths.resolve()
TaskStore(paths, tools=ToolRegistry(paths, desktop=Portal, input_lane=nullcontext)).run(**json.loads(os.environ['PERSONA_TEST_ARGS']))
"""
    runtime = str(__import__("opl_persona").__path__[0] + "/..")
    result = subprocess.run([sys.executable, "-c", adapter], check=False, env={
        **os.environ, "PYTHONPATH": runtime, "PERSONA_TEST_PORTAL": str(portal), "PERSONA_TEST_ARGS": json.dumps(arguments),
    })
    assert result.returncode == 84
    assert portal.read_text() == "receipt-41"

    class NewExecutor:
        def verified(self, kind, payload):
            assert kind == "submit" and payload["result"]["marker"] == "Receipt for form 41"
            return portal.read_text() == "receipt-41"

    restarted = TaskStore(profile, tools=ToolRegistry(profile, desktop=NewExecutor, input_lane=nullcontext))
    paused = restarted.inspect(task_id=item["id"])
    assert paused["status"] == "needs-check"
    assert paused["current_step"]["proposal"] == item["current_step"]["proposal"]
    with pytest.raises(ValueError, match="original operation"):
        restarted.run(**arguments)
    assert restarted.check(task_id=item["id"])["current_step"]["proposal"] == note_step["input"]
    restarted.proposals.review(**note_step["input"], approval_ref="approval://synthetic/note", decision="approved")
    restarted.proposals.authorize_obsidian(**note_step["input"], binding_id="notes",
                                         approval_ref="approval://synthetic/notes-write", confirmation="confirmed")
    restarted.proposals.apply_obsidian(**note_step["input"], binding_id="notes",
                                      external_approval_ref="approval://synthetic/notes-write")
    final = restarted.check(task_id=item["id"])
    assert final["status"] == "complete"
    assert final["steps"][0]["attempts"] == 1
    assert final["steps"][1]["receipt"]["provider"] == "proposal-owner"
    assert (root / "application.md").is_file()


def test_submit_rejects_cross_origin_readback_and_a_changed_field(monkeypatch):
    with pytest.raises(ValueError, match="approved origin"):
        normalize_form("submit", SUBMIT["input"] | {
            "result": SUBMIT["input"]["result"] | {"page_url": "https://other.example.test/receipt/41"},
        }, normalize_desktop_target)
    desktop = Desktop.__new__(Desktop)
    monkeypatch.setattr(desktop, "observe", lambda *args, **kwargs: [
        {"role": "textfield", "name": "Title", "value": "An independent edit", "ref_id": "@s0:e1"},
    ])
    with pytest.raises(ToolPaused, match="changed since review"):
        desktop.preflight("submit", SUBMIT["input"])
