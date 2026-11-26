"""Exercise independently resolved tools through the existing TaskStore."""

import ast
from contextlib import nullcontext
import json
import os
import struct
from pathlib import Path

import pytest

from opl_persona.paths import PersonaPaths
from opl_persona.tasks import TaskStore
from opl_persona.tool_registry import ToolRegistry
from opl_persona.tools.desktop import Desktop


def prepare(store, name, provider, action, arguments):
    return store.prepare(task_id=name, title=name, plan={
        "source_refs": ["evidence://fixture/operation"],
        "steps": [{"kind": "tool", "title": action, "input": {
            "provider": provider, "action": action, "arguments": arguments,
        }}],
    })


def approve(store, item):
    proposal = item["current_step"]["proposal"]
    store.proposals.review(**proposal, decision="approved", approval_ref="approval://fixture/tool")
    return {"task_id": item["id"], "confirmation": "confirmed", **proposal}


def test_independent_connector_recovers_original_operation_without_repeating(monkeypatch, tmp_path):
    receipt = tmp_path / "remote-receipt.json"
    bad_receipt = {"enabled": False}

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def call(self, method, params):
            package = params["package_id"]
            assert package == "fixture-tasks"
            if method == "app.contribution.execute":
                ref = params["action_id"]
                value = params["payload"]
                assert ref == "tool.execution.v1#execute"
                assert value["input"] == {"complete": True}
                identity = {key: value[key] for key in ("operation_id", "operation", "target_ref", "expected_revision")}
                with receipt.open("x") as out:
                    json.dump(identity, out)
                raise OSError("simulated daemon drop during execute")
            assert method == "app.contribution.read"
            ref = params["ref"]
            phase = ref.split("#")[1]
            value = params["input"]
            if phase == "operations":
                return {"kind": "data", "state": "ready", "data": {
                    "schema_version": "opl-tool-operations.v1", "operations": [{"id": "task.complete"}],
                }}
            identity = {key: value[key] for key in ("operation_id", "operation", "target_ref", "expected_revision")}
            data = {"schema_version": "opl-tool-operation.v1", **identity}
            if phase == "preflight":
                data["state"] = "ready" if value["expected_revision"] == "rev-4" else "stale"
            else:
                assert "input" not in value and json.loads(receipt.read_text()) == identity
                data.update(state="applied", receipt_ref="fixture://receipts/" + value["operation_id"])
                if bad_receipt["enabled"]:
                    data["operation_id"] = "wrong-operation"
            return {"kind": "data", "state": "ready", "data": data}

    monkeypatch.setattr("opl_persona.tools.package.connect", lambda: FakeClient())
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "profile"))
    store = TaskStore()
    assert store.tools.connector_catalog("fixture-tasks")["operations"] == [{"id": "task.complete"}]
    args = {"package_id": "fixture-tasks", "operation": "task.complete", "target_ref": "fixture://tasks/17",
            "expected_revision": "rev-4", "input": {"complete": True}}
    stale = prepare(store, "stale", "opl-package", "execute", args | {"expected_revision": "rev-3"})
    assert store.run(**approve(store, stale))["current_step"]["attempts"] == 0
    item = prepare(store, "complete-17", "opl-package", "execute", args)
    action = approve(store, item)
    assert store.run(**action)["status"] == "needs-check"
    restarted = TaskStore()
    with pytest.raises(ValueError, match="original operation"):
        restarted.run(**action)
    bad_receipt["enabled"] = True
    assert restarted.check(task_id=item["id"])["status"] == "needs-check"
    bad_receipt["enabled"] = False
    completed = restarted.check(task_id=item["id"])
    step = completed["steps"][0]
    assert completed["status"] == "complete" and step["attempts"] == 1
    assert step["receipt"]["evidence"]["receipt_ref"] == f"fixture://receipts/{step['operation_id']}"
    assert json.loads(receipt.read_text())["operation_id"] == step["operation_id"]


def test_visual_drag_checks_window_pixels_and_requires_exact_review(monkeypatch, tmp_path):
    target = {"app": "Canvas", "window_id": "w-fixture", "process_instance": "proc-1", "marker": "Board 41"}
    state = {"frame": b"before", "inputs": []}
    png_header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack("!II", 120, 80)

    class FixtureDesktop(Desktop):
        def __init__(self):
            pass

        def observe(self, *args, **kwargs):
            return []

        def _window(self, *args, **kwargs):
            return {"bounds": {"x": -10, "y": 20, "width": 60, "height": 40}}

        def _run(self, *argv, **kwargs):
            if argv[0] == "screenshot":
                Path(argv[-1]).write_bytes(png_header + state["frame"])
            else:
                state["inputs"].append(argv)
                state["frame"] = b"after"
            return {"ok": True, "data": {}}

    monkeypatch.setattr("opl_persona.tools.desktop._console_session", lambda: "fixture")
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "profile"))
    paths = PersonaPaths.resolve()
    store = TaskStore(paths, tools=ToolRegistry(paths, desktop=FixtureDesktop, input_lane=nullcontext))
    before = store.tools.desktop_capture(target)
    args = {"target": target, "before": before["digest"], "at": [30, 20], "to": [90, 60]}
    item = prepare(store, "canvas-drag", "agent-desktop", "drag", args)
    action = approve(store, item)
    state["frame"] = b"changed"
    assert store.run(**action)["current_step"]["attempts"] == 0
    state["frame"] = b"before"
    result = store.run(**action)
    assert result["status"] == "needs-check"
    assert state["inputs"] == [("--headed", "drag", "--from-xy=5,30", "--to-xy=35,50")]
    proof = result["current_step"]["pending_readback"]
    check = {"operation_id": proof["operation_id"], "confirmation": "confirmed"}
    with pytest.raises(ValueError, match="current observed"):
        store.check(task_id=item["id"], review=check | {"digest": before["digest"]})
    after = proof["evidence"]
    image = Path(after["path"])
    original_bytes = image.read_bytes()
    image.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed or is missing"):
        store.check(task_id=item["id"], review=check | {"digest": after["digest"]})
    image.write_bytes(original_bytes)
    complete = store.check(task_id=item["id"], review=check | {"digest": after["digest"]})
    assert complete["status"] == "complete"
    assert complete["steps"][0]["receipt"]["human_reviewed"] is True


def test_github_label_preserves_existing_labels_and_checks_active_account(monkeypatch, tmp_path):
    fixture = tmp_path / "gh"
    state = tmp_path / "labels.json"
    state.write_text('["existing"]', encoding="utf-8")
    fixture.write_text("""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
assert args[:3] == ['api', '--hostname', 'github.com']
state = Path(os.environ['TEST_GITHUB_LABELS'])
labels = json.loads(state.read_text())
if args[3] == 'user':
    result = {'login': os.environ.get('TEST_GITHUB_ACCOUNT', 'reviewer')}
elif args[3] == 'repos/fixture/tools/issues/17':
    result = {'issue_id': 'I_fixture17', 'url': 'https://github.com/fixture/tools/issues/17',
              'state': 'open', 'labels': labels}
else:
    assert args[3:] == ['repos/fixture/tools/issues/17/labels', '--method', 'POST', '--input', '-']
    assert json.load(sys.stdin) == {'labels': ['reviewed']}
    assert 'reviewed' not in labels
    labels.append('reviewed')
    state.write_text(json.dumps(labels))
    result = labels
print(json.dumps(result))
""", encoding="utf-8")
    fixture.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("TEST_GITHUB_LABELS", str(state))
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "profile"))
    store = TaskStore()
    issue = store.tools.github_issue("fixture/tools", 17)
    arguments = {key: issue[key] for key in ("repo", "number", "account", "issue_id", "expected_revision")}
    item = prepare(store, "label-17", "github", "issue.label.add", arguments | {"label": "reviewed"})
    action = approve(store, item)
    monkeypatch.setenv("TEST_GITHUB_ACCOUNT", "different")
    assert store.run(**action)["current_step"]["attempts"] == 0
    assert json.loads(state.read_text()) == ["existing"]
    monkeypatch.delenv("TEST_GITHUB_ACCOUNT")
    completed = store.run(**action)
    assert completed["status"] == "complete"
    assert completed["steps"][0]["receipt"]["observation"] == "github-label-present"
    assert json.loads(state.read_text()) == ["existing", "reviewed"]


def test_provider_modules_import_only_the_shared_tool_contract_and_primitives():
    from opl_persona import tools

    root = Path(tools.__file__).parent
    providers = {file.stem for file in root.glob("*.py")} - {"__init__", "contract"}
    for provider in providers:
        tree = ast.parse((root / f"{provider}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 2:
                assert node.module == "primitives", f"{provider} imports another Persona domain"
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                names = {node.module.split(".")[0]} if node.module else {alias.name for alias in node.names}
                assert names.isdisjoint(providers), f"{provider} imports another tool provider"
            if isinstance(node, (ast.Import, ast.ImportFrom)) and not getattr(node, "level", 0):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module]
                assert all(not module or not module.startswith("opl_persona") or
                           module in {"opl_persona.primitives", "opl_persona.tools.contract"} for module in modules)
