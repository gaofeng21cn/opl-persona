"""Use agent-browser for a private, pinned Chromium session."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager

from .local_tools import ToolPaused, _page_identity, browser_session_name, browser_tab_id
from .workspace import atomic_json


class Browser:
    provider = "agent-browser"

    def __init__(self, paths, session):
        session = browser_session_name(session)
        self.session = session
        self.root = paths.data_root / "browser" / session
        self.config = self.root / "config.json"
        namespace = hashlib.sha256(os.fsencode(paths.workspace.resolve())).hexdigest()[:16]
        # Keep the generated socket pathname short on macOS.
        private_session = hashlib.sha256(session.encode()).hexdigest()[:16]
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("AGENT_BROWSER_")}
        self.env.update(
            AGENT_BROWSER_NAMESPACE=f"opl-{namespace}",
            AGENT_BROWSER_SESSION=private_session,
            AGENT_BROWSER_PROFILE=str(self.root / "chrome"),
            AGENT_BROWSER_PIN_TAB="1",
            AGENT_BROWSER_NO_WEBMCP="1",
        )
        if sys.platform == "darwin":
            self.env["AGENT_BROWSER_ARGS"] = "--disable-features=MacAppCodeSignClone"
        self.binary = shutil.which("agent-browser")
        if not self.binary:
            raise ToolPaused("Install agent-browser 0.42 or newer to use independent browser sessions")

    @contextmanager
    def lane(self, *, create=False):
        if os.name != "posix":
            raise ToolPaused("Persona browser sessions require a POSIX host")
        import fcntl

        if create:
            self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not self.root.is_dir():
            raise ToolPaused("Open this Persona browser session first")
        fd = os.open(self.root / "input.lock", os.O_NOFOLLOW | os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, "ab") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ToolPaused("This browser session already has an active Persona operation") from exc
            if create and not self.config.exists():
                atomic_json(self.config, {})
            yield

    def _run(self, *args, stdin=None, mcp=False):
        try:
            argv = [self.binary, *args, "--config", str(self.config)] if mcp else [
                self.binary, "--json", "--config", str(self.config), *args,
            ]
            result = subprocess.run(argv, input=stdin, text=True, encoding="utf-8", capture_output=True,
                                    cwd=self.root, env=self.env, timeout=18, check=False)
            response = json.loads(result.stdout)
            if mcp:
                response = response["structuredContent"]["response"]
            if result.returncode or response.get("success") is not True or not isinstance(response["data"], dict):
                raise ValueError("unsuccessful agent-browser operation")
            return response["data"]
        except (AttributeError, KeyError, OSError, TypeError, ValueError, subprocess.SubprocessError) as exc:
            # Upstream diagnostics may contain page contents or values.
            raise ToolPaused("agent-browser could not verify the browser operation. Check the original session.") from exc

    def open(self, url, *, headless=False):
        _page_identity(url)
        try:
            result = subprocess.run([self.binary, "--version"], capture_output=True, text=True,
                                    env=self.env, timeout=5, check=True)
            version = re.fullmatch(r"agent-browser (\d+)\.(\d+)\.\d+.*", result.stdout.strip())
        except (OSError, subprocess.SubprocessError) as exc:
            raise ToolPaused("Could not start agent-browser") from exc
        if not version or tuple(map(int, version.groups())) < (0, 42):
            raise ToolPaused("Use agent-browser 0.42 or newer for pinned tabs and stdin form input")
        with self.lane(create=True):
            self._run("--headed", "false" if headless else "true", "open", url)
            return self._snapshot()

    def inspect(self):
        with self.lane():
            return self._snapshot()

    def close(self):
        with self.lane():
            self._run("close")

    def _active_tab(self):
        if self._run("session", "info").get("active") is not True:
            raise ToolPaused("Open the original page in this Persona browser session")
        tabs = self._run("tab", "list").get("tabs", [])
        active = [tab for tab in tabs if tab.get("active") is True and tab.get("type") == "page"]
        if len(active) != 1:
            raise ToolPaused("Open the reviewed tab in this Persona browser session")
        return {"browser_session": self.session, "tab_id": browser_tab_id(active[0].get("targetId")),
                "page_url": active[0]["url"]}

    @staticmethod
    def _matches(actual, expected):
        try:
            return _page_identity(actual) == _page_identity(expected)
        except (AttributeError, TypeError, ValueError):
            return False

    def _snapshot(self, target=None):
        tab = self._active_tab()
        if target and (tab["tab_id"] != target["tab_id"] or not self._matches(tab["page_url"], target["page_url"])):
            raise ToolPaused("The active browser tab or page differs from the reviewed target")
        data = self._run("snapshot")
        if not self._matches(data.get("origin"), tab["page_url"]) or self._active_tab() != tab:
            raise ToolPaused("The browser page changed during observation")
        return tab | {"snapshot": data["snapshot"], "refs": data["refs"]}

    @staticmethod
    def _marker(view, marker):
        if any(node.get("role") in {"heading", "link", "status", "text", "label"}
               and node.get("name") == marker for node in view["refs"].values()):
            return True
        # Unnamed paragraphs have StaticText children without a structured ref.
        return any(line.strip() == "- StaticText " + json.dumps(marker, ensure_ascii=False)
                   for line in view["snapshot"].splitlines())

    def _observe(self, target):
        view = self._snapshot(target)
        if not self._marker(view, target["marker"]):
            raise ToolPaused("The reviewed browser record or receipt is not visible")
        if not self._marker(view, target["account_marker"]):
            raise ToolPaused("The reviewed signed-in account is not visible")
        return view

    def _control(self, view, role, name):
        matches = [key for key, node in view["refs"].items() if node.get("role") == role and node.get("name") == name]
        if len(matches) != 1 or not re.fullmatch(r"e[0-9]+", matches[0]):
            raise ToolPaused("The reviewed browser control is missing or ambiguous")
        ref = "@" + matches[0]
        if self._run("is", "visible", ref).get("visible") is not True:
            raise ToolPaused("The reviewed browser control is hidden")
        return ref

    def _value(self, view, ref):
        field = self._run("get", "attr", ref, "type")
        auto = self._run("get", "attr", ref, "autocomplete")
        if (not self._matches(field.get("origin"), view["page_url"])
                or not self._matches(auto.get("origin"), view["page_url"])):
            raise ToolPaused("The field is outside the reviewed browser document")
        if (field.get("value") not in {None, "", "text", "search", "email", "tel", "url", "number"}
                or any(token in {"current-password", "new-password", "one-time-code"} or token.startswith("cc-")
                       for token in (auto.get("value") or "").lower().split())):
            raise ToolPaused("Use the website directly for credentials, protected or non-text fields")
        value = self._run("get", "value", ref).get("value")
        if not isinstance(value, str):
            raise ToolPaused("The reviewed field value could not be read")
        return value

    def preflight(self, kind, payload):
        view = self._observe(payload["target"])
        if kind == "fill":
            ref = self._control(view, "textbox", payload["field"])
            value = self._value(view, ref)
            if value == payload["value"]:
                return None
            if value != payload["before"]:
                raise ToolPaused("The reviewed browser field has changed")
            return ref
        if self._marker(view, payload["result"]["marker"]):
            raise ToolPaused("The expected receipt is already visible")
        for name, value in payload["fields"].items():
            if self._value(view, self._control(view, "textbox", name)) != value:
                raise ToolPaused("Browser form values changed since review")
        ref = self._control(view, "button", payload["button"])
        button = self._run("get", "attr", ref, "type")
        if not self._matches(button.get("origin"), view["page_url"]):
            raise ToolPaused("The submit control is outside the reviewed browser document")
        return ref

    def dispatch(self, kind, ref, payload):
        # Revalidate after the dispatch marker has been persisted.
        try:
            if self.preflight(kind, payload) != ref:
                return False
        except ToolPaused:
            return False
        if kind == "fill":
            self._run("mcp", "call", "agent_browser_fill", "-", mcp=True,
                      stdin=json.dumps({"selector": ref, "text": payload["value"]}))
        else:
            self._run("click", ref)
        return True

    def verified(self, kind, payload):
        if kind == "submit":
            target = payload["result"]
            tab = self._active_tab()
            if tab["tab_id"] == target["tab_id"]:
                if not self._matches(tab["page_url"], target["page_url"]):
                    self._run("wait", "--url", target["page_url"], "--timeout", "3500")
                self._run("wait", "--text", target["marker"], "--timeout", "3500")
            self._observe(target)
            return True
        view = self._observe(payload["target"])
        return self._value(view, self._control(view, "textbox", payload["field"])) == payload["value"]
