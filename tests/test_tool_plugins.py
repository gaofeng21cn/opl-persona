"""Exercise independently resolved tools through the existing TaskStore."""

import ast
from contextlib import nullcontext
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from opl_persona.knowledge import _notify_daemon_writeback
from opl_persona.paths import PersonaPaths
from opl_persona.tasks import TaskStore
from opl_persona.tool_registry import ToolRegistry
from opl_persona.tools.contract import ToolPaused
from opl_persona.tools.desktop import Desktop
from opl_persona.tools.package import PackageTool
from opl_persona.workspace import relay_read


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


def test_package_tool_unwraps_opld_execute_contribution_nested_envelope(monkeypatch, tmp_path):
    receipt = tmp_path / "remote-receipt.json"

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def call(self, method, params):
            assert params["package_id"] == "fixture-tasks"
            if method == "app.contribution.execute":
                value = params["payload"]
                assert params["action_id"] == "tool.execution.v1#execute"
                identity = {key: value[key] for key in ("operation_id", "operation", "target_ref", "expected_revision")}
                receipt.write_text(json.dumps(identity), encoding="utf-8")
                return {
                    "ok": True,
                    "dryRun": False,
                    "dry_run": False,
                    "authorityBoundary": "app_bridge_no_domain_authority",
                    "action_id": "tool.execution.v1#execute",
                    "result": {
                        "schema_version": "opl-package-app-contribution-response.v1",
                        "ok": True,
                        "operation": "execute",
                        "result": {
                            "kind": "action",
                            "status": "applied",
                            "data": {
                                "schema_version": "opl-tool-operation.v1",
                                **identity,
                                "state": "applied",
                                "receipt_ref": "fixture://receipts/" + value["operation_id"],
                            },
                        },
                    },
                }

            assert method == "app.contribution.read"
            phase = params["ref"].split("#")[1]
            value = params["input"]
            if phase == "operations":
                return {
                    "schema_version": "opl-package-app-contribution-response.v1",
                    "ok": True,
                    "ref": params["ref"],
                    "operation": "read",
                    "result": {
                        "kind": "data",
                        "state": "ready",
                        "data": {
                            "schema_version": "opl-tool-operations.v1",
                            "operations": [{"id": "task.complete"}],
                        },
                    },
                }
            identity = {key: value[key] for key in ("operation_id", "operation", "target_ref", "expected_revision")}
            data = {"schema_version": "opl-tool-operation.v1", **identity}
            if phase == "preflight":
                data["state"] = "ready"
            else:
                assert json.loads(receipt.read_text(encoding="utf-8")) == identity
                data.update(state="applied", receipt_ref="fixture://receipts/" + value["operation_id"])
            return {
                "schema_version": "opl-package-app-contribution-response.v1",
                "ok": True,
                "ref": params["ref"],
                "operation": "read",
                "result": {"kind": "data", "state": "ready", "data": data},
            }

    monkeypatch.setattr("opl_persona.tools.package.connect", lambda: FakeClient())
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "profile"))
    store = TaskStore()
    assert store.tools.connector_catalog("fixture-tasks")["operations"] == [{"id": "task.complete"}]
    args = {
        "package_id": "fixture-tasks",
        "operation": "task.complete",
        "target_ref": "fixture://tasks/17",
        "expected_revision": "rev-4",
        "input": {"complete": True},
    }
    item = prepare(store, "complete-nested-17", "opl-package", "execute", args)
    completed = store.run(**approve(store, item))
    step = completed["steps"][0]
    assert completed["status"] == "complete"
    assert step["attempts"] == 1
    assert step["receipt"]["evidence"]["receipt_ref"] == f"fixture://receipts/{step['operation_id']}"


@pytest.mark.parametrize("bad_response", [
    {"ok": False, "result": {"kind": "action", "data": {"schema_version": "opl-tool-operation.v1"}}},
    {
        "ok": True,
        "dryRun": False,
        "dry_run": False,
        "authorityBoundary": "app_bridge_no_domain_authority",
        "action_id": "tool.execution.v1#execute",
        "result": {
            "schema_version": "opl-package-app-contribution-response.v1",
            "ok": False,
            "operation": "execute",
            "error": {"code": "invalid_request", "message": "rejected"},
        },
    },
    {
        "ok": True,
        "result": {
            "schema_version": "opl-package-app-contribution-response.v1",
            "ok": True,
            "result": {"kind": "action", "ok": False, "data": {"schema_version": "opl-tool-operation.v1"}},
        },
    },
    {
        "ok": True,
        "result": {
            "schema_version": "opl-package-app-contribution-response.v1",
            "ok": True,
            "package_id": "wrong-package",
            "result": {"kind": "action", "data": {"schema_version": "opl-tool-operation.v1"}},
        },
    },
])
def test_package_tool_fails_closed_on_nested_rejection(monkeypatch, tmp_path, bad_response):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def call(self, method, params):
            return bad_response

    monkeypatch.setattr("opl_persona.tools.package.connect", lambda: FakeClient())
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "profile"))
    tool = PackageTool(PersonaPaths.resolve(), "fixture-tasks")
    with pytest.raises(ToolPaused):
        tool._call("execute", {"operation_id": "op-1"})


def test_package_tool_over_real_af_unix_json_rpc_socket(monkeypatch, tmp_path):
    token = "test-session-token-af-unix"
    fail_nested = {"enabled": False}
    executed = []

    with tempfile.TemporaryDirectory(dir="/tmp", prefix="oplp-sock-") as sock_dir:
        sock_path = os.path.join(sock_dir, "opld.sock")
        state_dir = tmp_path / "state"
        run_dir = state_dir / "run"
        run_dir.mkdir(parents=True)
        (run_dir / "opld.session.json").write_text(
            json.dumps({"socket_path": sock_path, "token": token}),
            encoding="utf-8",
        )

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(sock_path)
        server.listen(8)
        stop_event = threading.Event()

        def serve():
            while not stop_event.is_set():
                try:
                    server.settimeout(0.1)
                    conn, _ = server.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break
                with conn:
                    buf = b""
                    while True:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        buf += chunk
                        while b"\n" in buf:
                            raw_line, buf = buf.split(b"\n", 1)
                            if not raw_line.strip():
                                continue
                            req = json.loads(raw_line.decode("utf-8"))
                            method = req["method"]
                            params = req.get("params", {})
                            if method == "daemon.handshake":
                                assert params["token"] == token
                                result = {"session_id": "sess-1", "api_version": "2.0", "base_version": "2.0.0"}
                            elif method == "app.contribution.execute":
                                value = params["payload"]
                                executed.append(value)
                                identity = {
                                    key: value[key]
                                    for key in ("operation_id", "operation", "target_ref", "expected_revision")
                                }
                                if fail_nested["enabled"]:
                                    handler_out = {
                                        "schema_version": "opl-package-app-contribution-response.v1",
                                        "ok": False,
                                        "operation": "execute",
                                        "error": {"code": "invalid_request", "message": "nested fail"},
                                    }
                                else:
                                    handler_out = {
                                        "schema_version": "opl-package-app-contribution-response.v1",
                                        "ok": True,
                                        "operation": "execute",
                                        "result": {
                                            "kind": "action",
                                            "status": "applied",
                                            "data": {
                                                "schema_version": "opl-tool-operation.v1",
                                                **identity,
                                                "state": "applied",
                                                "receipt_ref": "fixture://unix/" + value["operation_id"],
                                            },
                                        },
                                    }
                                result = {
                                    "ok": True,
                                    "dryRun": False,
                                    "dry_run": False,
                                    "authorityBoundary": "app_bridge_no_domain_authority",
                                    "action_id": params["action_id"],
                                    "result": handler_out,
                                }
                            else:
                                assert method == "app.contribution.read"
                                phase = params["ref"].split("#")[1]
                                value = params["input"]
                                if phase == "operations":
                                    result = {
                                        "schema_version": "opl-package-app-contribution-response.v1",
                                        "ok": True,
                                        "ref": params["ref"],
                                        "operation": "read",
                                        "result": {
                                            "kind": "data",
                                            "state": "ready",
                                            "data": {
                                                "schema_version": "opl-tool-operations.v1",
                                                "operations": [{"id": "task.complete"}],
                                            },
                                        },
                                    }
                                else:
                                    identity = {
                                        key: value[key]
                                        for key in ("operation_id", "operation", "target_ref", "expected_revision")
                                    }
                                    data = {"schema_version": "opl-tool-operation.v1", **identity}
                                    if phase == "preflight":
                                        data["state"] = "ready"
                                    else:
                                        data.update(
                                            state="applied",
                                            receipt_ref="fixture://unix/" + value["operation_id"],
                                        )
                                    result = {
                                        "schema_version": "opl-package-app-contribution-response.v1",
                                        "ok": True,
                                        "ref": params["ref"],
                                        "operation": "read",
                                        "result": {"kind": "data", "state": "ready", "data": data},
                                    }
                            reply = json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}) + "\n"
                            conn.sendall(reply.encode("utf-8"))

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            monkeypatch.setenv("OPL_STATE_DIR", str(state_dir))
            monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "profile"))
            store = TaskStore()
            assert store.tools.connector_catalog("fixture-tasks")["operations"] == [{"id": "task.complete"}]
            args = {
                "package_id": "fixture-tasks",
                "operation": "task.complete",
                "target_ref": "fixture://tasks/42",
                "expected_revision": "rev-1",
                "input": {"complete": True},
            }
            item = prepare(store, "unix-42", "opl-package", "execute", args)
            completed = store.run(**approve(store, item))
            step = completed["steps"][0]
            assert completed["status"] == "complete"
            assert step["receipt"]["evidence"]["receipt_ref"] == f"fixture://unix/{step['operation_id']}"
            assert len(executed) == 1

            fail_nested["enabled"] = True
            tool = PackageTool(PersonaPaths.resolve(), "fixture-tasks")
            with pytest.raises(ToolPaused):
                tool._call("execute", {
                    "operation_id": "op-fail",
                    "operation": "task.complete",
                    "target_ref": "fixture://tasks/43",
                    "expected_revision": "rev-1",
                    "input": {"complete": True},
                })
        finally:
            stop_event.set()
            thread.join(timeout=2.0)
            server.close()


def test_clean_env_resilience_without_opl_client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "profile"))
    paths = PersonaPaths.resolve()
    monkeypatch.setitem(sys.modules, "opl_client", None)
    monkeypatch.setattr("opl_persona.knowledge.connect", None)
    monkeypatch.setattr("opl_persona.workspace.connect", None)
    monkeypatch.setattr("opl_persona.tools.package.connect", None)

    _notify_daemon_writeback(paths, "workspace.writeback.propose", {"knowledge_id": "k.test"})
    assert relay_read("personal.memory.v1#people", {}, paths)["state"] == "unavailable"
    with pytest.raises(ToolPaused):
        PackageTool(paths, "fixture-tasks")._call("operations", {})

    repo_root = Path(__file__).parents[1]
    staged = tmp_path / "staged-persona"
    shutil.copytree(repo_root / "runtime", staged / "runtime", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (staged / "bin").mkdir()
    shutil.copy2(repo_root / "bin" / "opl-persona", staged / "bin" / "opl-persona")
    (staged / "bin" / "opl-persona").chmod(0o755)

    clean_env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"OPL_PYTHON_SDK_ROOT", "PYTHONPATH"}
    }
    clean_env["OPL_PROFILE_WORKSPACE"] = str(tmp_path / "staged-profile")

    for req in (
        {"schema_version": "opl-package-app-contribution-request.v1", "operation": "read", "package_id": "opl-persona", "ref": "personal.context.v1#today", "input": {}},
        {"schema_version": "opl-package-app-contribution-request.v1", "operation": "read", "package_id": "opl-persona", "ref": "personal.memory.v1#people", "input": {}},
        {
            "schema_version": "opl-package-app-contribution-request.v1",
            "operation": "execute",
            "package_id": "opl-persona",
            "action_id": "personal.inbox.v1#capture.propose",
            "payload": {
                "capture_id": "cap-clean-1",
                "item_kind": "note",
                "title": "Clean env capture",
                "summary": "Captured without opl_client",
                "source_refs": ["source://clean-env/1"],
            },
        },
    ):
        proc = subprocess.run(
            [str(staged / "bin" / "opl-persona"), "--json", "app-contribution"],
            input=json.dumps(req),
            text=True,
            capture_output=True,
            env=clean_env,
            cwd=str(staged),
            timeout=20,
        )
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        out = json.loads(proc.stdout)
        assert out["ok"] is True
