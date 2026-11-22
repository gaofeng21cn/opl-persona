"""Exercise browser approvals against synthetic records, with optional real Chromium."""

from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest

from opl_persona.paths import PersonaPaths
from opl_persona.tasks import TaskStore
from opl_persona.tools.browser import Browser
from opl_persona.tools.contract import ToolPaused, normalize_browser_target, normalize_form


def target(tab, record, account):
    return {key: tab[key] for key in ("browser_session", "tab_id", "page_url")} | {
        "marker": f"Record {record}", "account_marker": f"Signed in as {account}",
    }


def prepare(store, identifier, *steps):
    return store.prepare(task_id=identifier, title=identifier, plan={
        "source_refs": ["evidence://synthetic/forms"],
        "steps": [{"kind": kind, "title": kind, "input": payload} for kind, payload in steps],
    })


def approve(store, item):
    proposal = item["current_step"]["proposal"]
    store.proposals.review(**proposal, decision="approved", approval_ref="approval://synthetic/browser")
    return {"task_id": item["id"], "confirmation": "confirmed", **proposal}


def test_browser_plan_rejects_receipt_from_a_different_session_tab_or_origin():
    page = {"browser_session": "conference", "tab_id": "A" * 32, "page_url": "https://portal.example.test/form"}
    reviewed = target(page, "A", "staff")
    receipt = reviewed | {"marker": "Receipt A", "page_url": "https://portal.example.test/receipt"}
    for change in ({"browser_session": "other"}, {"tab_id": "B" * 32}, {"page_url": "https://other.example.test/receipt"}):
        with pytest.raises(ValueError, match="must stay"):
            normalize_form("submit", {"target": reviewed, "button": "Submit", "fields": {"Title": "A"},
                                      "result": receipt | change}, normalize_browser_target)


def test_browser_session_input_ownership_is_per_session_and_profile(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/test/agent-browser")
    one = PersonaPaths(tmp_path / "one" / "data" / "persona", tmp_path / "one")
    two = PersonaPaths(tmp_path / "two" / "data" / "persona", tmp_path / "two")
    a, b, c = Browser(one, "work"), Browser(one, "other"), Browser(two, "work")
    with a.lane(create=True), b.lane(create=True), c.lane(create=True):
        with pytest.raises(ToolPaused, match="active Persona operation"):
            with Browser(one, "work").lane():
                pytest.fail("a second executor took the same browser session")
        assert a.env["AGENT_BROWSER_NAMESPACE"] != c.env["AGENT_BROWSER_NAMESPACE"]
        assert a.env["AGENT_BROWSER_SESSION"] != b.env["AGENT_BROWSER_SESSION"]


@pytest.fixture
def portal():
    submissions = {"A": [], "B": []}

    class Handler(BaseHTTPRequestHandler):
        def page(self, head, account, body=""):
            html = f"<!doctype html><title>{head}</title><h1>{head}</h1><p>Signed in as {account}</p>{body}"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())

        def account(self):
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return cookie["account"].value if "account" in cookie else "guest"

        def do_GET(self):
            record = self.path.rsplit("/", 1)[-1]
            if self.path.startswith("/login/") and record in submissions:
                self.send_response(303)
                self.send_header("Set-Cookie", f"account=staff-{record}; Max-Age=3600; Path=/")
                self.send_header("Location", f"/form/{record}")
                self.end_headers()
            elif self.path.startswith("/form/") and record in submissions:
                self.page(f"Record {record}", self.account(), f"""
                    <form method="post" action="/submit/{record}">
                      <label>Title <input name="title" type="text"></label>
                      <label>Secret <input name="secret" type="password"></label>
                      <button>Submit</button>
                    </form>""")
            elif self.path.startswith("/receipt/") and submissions.get(record):
                self.page(f"Receipt for {record}", self.account())
            else:
                self.send_error(404)

        def do_POST(self):
            record = self.path.rsplit("/", 1)[-1]
            fields = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            if record not in submissions or self.account() != f"staff-{record}":
                self.send_error(403)
                return
            submissions[record].append(fields.get("title"))
            self.send_response(303)
            self.send_header("Location", f"/receipt/{record}")
            self.end_headers()

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", submissions
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.skipif(os.environ.get("OPL_PERSONA_TEST_BROWSER") != "1",
                    reason="Opt in with agent-browser 0.42+ and Chromium installed")
def test_parallel_chromium_tasks_keep_accounts_and_reconcile_a_crash(monkeypatch, tmp_path, portal):
    url, submissions = portal
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "profile"))
    store = TaskStore()
    browsers = [Browser(store.paths, f"conference-{record}") for record in ("A", "B")]
    try:
        with ThreadPoolExecutor(2) as pool:
            tabs = list(pool.map(lambda pair: pair[0].open(f"{url}/login/{pair[1]}", headless=True),
                                 zip(browsers, ("A", "B"))))
        assert tabs[0]["tab_id"] != tabs[1]["tab_id"]
        targets = [target(tab, record, f"staff-{record}") for tab, record in zip(tabs, ("A", "B"))]

        for identifier, wrong, field in (
            ("wrong-account", targets[0] | {"account_marker": "Signed in as staff-B"}, "Title"),
            ("wrong-tab", targets[0] | {"tab_id": tabs[1]["tab_id"]}, "Title"),
            ("protected-field", targets[0], "Secret"),
        ):
            item = prepare(store, identifier, ("fill", {"target": wrong, "field": field, "before": "", "value": "fixture"}))
            halted = store.run(**approve(store, item))
            assert halted["status"] == "waiting"
            assert halted["current_step"]["attempts"] == 0

        items = []
        for record, reviewed in zip(("A", "B"), targets):
            value = f"Reviewed title {record}"
            items.append(prepare(store, record,
                ("fill", {"target": reviewed, "field": "Title", "before": "", "value": value}),
                ("submit", {"target": reviewed, "button": "Submit", "fields": {"Title": value},
                            "result": reviewed | {"marker": f"Receipt for {record}", "page_url": f"{url}/receipt/{record}"}})))
        arguments = [approve(store, item) for item in items]
        with ThreadPoolExecutor(2) as pool:
            filled = list(pool.map(lambda args: store.run(**args), arguments))
        assert all(item["steps"][0]["receipt"]["provider"] == "agent-browser" for item in filled)

        submit_a = approve(store, filled[0])
        runtime = Path(__import__("opl_persona").__file__).parent.parent
        child = """
import json
import os
import sys
from opl_persona.paths import PersonaPaths
from opl_persona.tasks import TaskStore
from opl_persona.tool_registry import ToolRegistry
from opl_persona.tools.browser import Browser

class InterruptedBrowser(Browser):
    def dispatch(self, *args):
        if super().dispatch(*args):
            os._exit(84)
        return False

paths = PersonaPaths.resolve()
TaskStore(paths, tools=ToolRegistry(paths, browser=InterruptedBrowser)).run(**json.load(sys.stdin))
"""
        result = subprocess.run([sys.executable, "-c", child], input=json.dumps(submit_a), text=True,
                                env=os.environ | {"PYTHONPATH": str(runtime)}, check=False, timeout=30)
        assert result.returncode == 84
        assert submissions == {"A": [["Reviewed title A"]], "B": []}
        restarted = TaskStore()
        assert restarted.inspect(task_id="A")["status"] == "needs-check"
        with pytest.raises(ValueError, match="original operation"):
            restarted.run(**submit_a)
        other_task_same_session = prepare(restarted, "linked-A", ("fill", {
            "target": targets[0], "field": "Title", "before": "", "value": "Blocked while A is uncertain",
        }))
        waiting = restarted.run(**approve(restarted, other_task_same_session))
        assert waiting["current_step"]["attempts"] == 0 and "task A" in waiting["summary"]
        assert restarted.run(**approve(restarted, filled[1]))["status"] == "complete"

        browsers[0].close()
        replacement = browsers[0].open(f"{url}/receipt/A", headless=True)
        assert replacement["tab_id"] != tabs[0]["tab_id"]
        assert restarted.check(task_id="A")["status"] == "needs-check"
        checked = restarted.check(task_id="A", tab_id=replacement["tab_id"])
        assert checked["status"] == "complete" and checked["steps"][1]["attempts"] == 1
        assert checked["steps"][1]["receipt"]["provider"] == "agent-browser"
        assert submissions == {"A": [["Reviewed title A"]], "B": [["Reviewed title B"]]}
    finally:
        for browser in browsers:
            try:
                browser.close()
            except ToolPaused:
                pass


@pytest.mark.skipif(os.environ.get("OPL_PERSONA_TEST_BROWSER") != "1",
                    reason="Opt in with agent-browser 0.42+ and Chromium installed")
def test_shared_chrome_pins_two_tabs_without_taking_original(monkeypatch, tmp_path, portal):
    url, _ = portal
    monkeypatch.setenv("OPL_PROFILE_WORKSPACE", str(tmp_path / "profile"))
    store = TaskStore()
    original, first, second = (Browser(store.paths, name) for name in ("original", "seat-one", "seat-two"))
    try:
        initial = original.open(f"{url}/login/A", headless=True)
        connection = original._run("get", "cdp-url")
        port = urlsplit(connection.get("cdpUrl") or connection["url"]).port
        tabs = [driver.open(f"{url}/form/{record}", shared=True, chrome_port=port)
                for driver, record in ((first, "A"), (second, "B"))]
        assert len({view["tab_id"] for view in [initial, *tabs]}) == 3
        assert all("Signed in as staff-A" in view["snapshot"] for view in tabs)
        arguments = []
        for record, view in zip(("A", "B"), tabs):
            item = prepare(store, f"shared-{record}", ("fill", {
                "target": target(view, record, "staff-A"), "field": "Title", "before": "", "value": f"Seat {record}",
            }))
            arguments.append(approve(store, item))
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda args: store.run(**args), arguments))
        assert all(item["status"] == "complete" for item in results)
        original_tab = next(tab for tab in original._run("tab", "list")["tabs"] if tab["targetId"] == initial["tab_id"])
        assert original_tab["url"] == initial["page_url"]
        original._run("tab", initial["tab_id"])
        assert "Seat A" not in original.inspect()["snapshot"]
        first.close()
        survivors = {tab["targetId"] for tab in original._run("tab", "list")["tabs"]}
        assert initial["tab_id"] in survivors and tabs[1]["tab_id"] in survivors
        assert tabs[0]["tab_id"] not in survivors
        assert second.inspect()["tab_id"] == tabs[1]["tab_id"]
    finally:
        for browser in (first, second, original):
            try:
                browser.close()
            except ToolPaused:
                pass
