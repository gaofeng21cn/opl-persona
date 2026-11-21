"""Bind local input to a fresh foreground window and verify its observed effect."""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from .workspace import text


class ToolPaused(RuntimeError):
    """The target needs attention before a local operation can proceed."""


def strict_object(value, *, required, optional=()):
    if not isinstance(value, dict) or set(required) - value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError("expected fields: " + ", ".join(required) + (", optional: " + ", ".join(optional) if optional else ""))
    return value


def _page_identity(value):
    url = urlsplit(value)
    if (url.scheme not in {"https", "http"} or not url.hostname or url.username is not None
            or url.password is not None or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})):
        raise ValueError("portal page must be an HTTPS URL or a loopback test URL, without credentials")
    return (url.scheme, url.hostname, url.port or (443 if url.scheme == "https" else 80),
            url.path or "/", url.query, url.fragment)


def normalize_target(value):
    if isinstance(value, dict) and "browser_session" in value:
        value = strict_object(value, required=("browser_session", "tab_id", "page_url", "marker", "account_marker"))
        target = {key: text(item, key, 2048) for key, item in value.items()}
        browser_session_name(target["browser_session"])
        browser_tab_id(target["tab_id"])
        _page_identity(target["page_url"])
        if target["marker"] == target["account_marker"]:
            raise ValueError("Review the record and signed-in account separately")
        return target
    value = strict_object(value, required=("app", "window_id", "process_instance", "marker"),
                          optional=("page_url", "account_marker"))
    target = {key: text(item, key, 2048) for key, item in value.items()}
    if not re.fullmatch(r"w-[A-Za-z0-9_-]{1,96}", target["window_id"]):
        raise ValueError("window_id must come from agent-desktop list-windows")
    if "page_url" in target:
        if "account_marker" not in target:
            raise ValueError("a portal requires a visible signed-in account")
        _page_identity(target["page_url"])
    return target


def browser_session_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", value):
        raise ValueError("Use a browser session name of 1–32 letters, digits, hyphens or underscores")
    return value


def browser_tab_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Fa-f]{32}", value):
        raise ValueError("Use the tab_id from opl-persona browser inspect")
    return value


def _field_value(value):
    if not isinstance(value, str) or len(value) > 12000 or "\0" in value:
        raise ValueError("a field value must be bounded text without NUL")
    return value


def normalize_action(kind, value):
    if kind == "fill":
        value = strict_object(value, required=("target", "field", "before", "value"))
        return {"target": normalize_target(value["target"]), "field": text(value["field"], "field", 512),
                "before": _field_value(value["before"]), "value": _field_value(value["value"])}
    if kind != "submit":
        raise ValueError("unsupported local operation")
    value = strict_object(value, required=("target", "button", "fields", "result"))
    fields = value["fields"]
    if not isinstance(fields, dict) or not fields or len(fields) > 30:
        raise ValueError("submit requires the reviewed form fields")
    target = normalize_target(value["target"])
    result = normalize_target(value["result"])
    for key in ("app", "window_id", "process_instance", "account_marker", "browser_session", "tab_id"):
        if target.get(key) != result.get(key):
            raise ValueError("submission readback must stay in the same window or tab and account")
    if ("page_url" in target) != ("page_url" in result) or target["marker"] == result["marker"]:
        raise ValueError("submission requires a distinct receipt marker in the same program")
    if "page_url" in target and _page_identity(target["page_url"])[:3] != _page_identity(result["page_url"])[:3]:
        raise ValueError("submission readback must stay on the approved origin")
    return {"target": target, "button": text(value["button"], "button", 512), "result": result,
            "fields": {text(key, "field name", 512): _field_value(item) for key, item in fields.items()}}


@contextmanager
def desktop_input_lane(directory: Path | None = None):
    """Keep the observation, delivery and readback together across Persona profiles."""
    if sys.platform != "darwin":
        raise ToolPaused("Local tool tasks require a macOS desktop")
    import fcntl

    directory = directory or Path.home() / "Library" / "Application Support" / "OPL"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(directory / "persona-desktop-input.lock", os.O_NOFOLLOW | os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "rb+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ToolPaused("Another Persona task is using the desktop") from exc
        yield


def _console_session():
    try:
        raw = subprocess.check_output(["/usr/sbin/ioreg", "-a", "-n", "Root", "-d", "1"], timeout=4)
        roots = plistlib.loads(raw)
        if isinstance(roots, dict):
            roots = [roots]
        sessions = [entry for root in roots for entry in root.get("IOConsoleUsers", [])
                    if entry.get("kCGSSessionOnConsoleKey") and entry.get("kCGSSessionUserIDKey") == os.getuid()]
        if len(sessions) == 1:
            entry = sessions[0]
            if entry.get("kCGSessionLoginDoneKey") and not entry.get("CGSSessionScreenIsLocked"):
                identifier = entry.get("CGSSessionUniqueSessionUUID")
                if identifier:
                    return identifier
    except (OSError, ValueError, subprocess.SubprocessError, plistlib.InvalidFileException):
        pass
    raise ToolPaused("Unlock the local macOS session to continue")


def _nodes(tree):
    yield tree
    for child in tree.get("children", []):
        yield from _nodes(child)


def _focused_page_url(pid):
    """Read the native AXWebArea URL. Chrome's editable address bar may hide the scheme."""
    from ctypes import CDLL, POINTER, byref, c_bool, c_char_p, c_float, c_int, c_long, c_uint, c_void_p, create_string_buffer

    core = CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    ax = CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")

    def bind(lib, name, result, *params):
        function = getattr(lib, name)
        function.restype = result
        function.argtypes = params
        return function

    app_element = bind(ax, "AXUIElementCreateApplication", c_void_p, c_int)
    copy_attribute = bind(ax, "AXUIElementCopyAttributeValue", c_int, c_void_p, c_void_p, POINTER(c_void_p))
    set_timeout = bind(ax, "AXUIElementSetMessagingTimeout", c_int, c_void_p, c_float)
    create_string = bind(core, "CFStringCreateWithCString", c_void_p, c_void_p, c_char_p, c_uint)
    utf8_string = bind(core, "CFStringGetCString", c_bool, c_void_p, c_char_p, c_long, c_uint)
    array_size = bind(core, "CFArrayGetCount", c_long, c_void_p)
    array_item = bind(core, "CFArrayGetValueAtIndex", c_void_p, c_void_p, c_long)
    url_string = bind(core, "CFURLGetString", c_void_p, c_void_p)
    type_id = bind(core, "CFGetTypeID", c_long, c_void_p)
    url_type = bind(core, "CFURLGetTypeID", c_long)
    release = bind(core, "CFRelease", None, c_void_p)
    encoding = 0x08000100

    @contextmanager
    def attribute(element, name):
        key = create_string(None, name.encode("ascii"), encoding)
        value = c_void_p()
        try:
            yield value.value if copy_attribute(element, key, byref(value)) == 0 else None
        finally:
            release(key)
            if value.value:
                release(value)

    def string(value):
        buffer = create_string_buffer(8192)
        return buffer.value.decode("utf-8") if value and utf8_string(value, buffer, len(buffer), encoding) else None

    deadline = time.monotonic() + 4

    def pages(element, depth):
        if depth > 18 or time.monotonic() > deadline:
            raise ToolPaused("Could not verify the page within the desktop observation budget")
        with attribute(element, "AXRole") as role:
            if string(role) == "AXWebArea":
                with attribute(element, "AXURL") as url:
                    if url and type_id(url) == url_type():
                        yield string(url_string(url))
                return
        with attribute(element, "AXChildren") as children:
            if children:
                for index in range(array_size(children)):
                    yield from pages(array_item(children, index), depth + 1)

    app = app_element(pid)
    try:
        set_timeout(app, 0.3)
        with attribute(app, "AXFocusedWindow") as window:
            urls = list(pages(window, 0)) if window else []
            if len(urls) == 1 and urls[0]:
                return urls[0]
    finally:
        release(app)
    raise ToolPaused("Could not identify one browser document in the reviewed window")


def _marker(nodes, expected):
    return any(node.get("role") in {"text", "statictext", "heading", "label", "link"}
               and expected in (node.get("name"), node.get("value")) for node in nodes)


def _control(nodes, role, name):
    matches = [node for node in nodes if node.get("role") == role and node.get("name") == name]
    if len(matches) != 1:
        raise ToolPaused("The reviewed control is missing or ambiguous")
    node = matches[0]
    if "protected" in (node.get("states") or []) or node.get("subrole") in {"AXSecureTextField", "secure_textfield"}:
        raise ToolPaused("Enter protected values through the application")
    ref = node.get("ref_id", "")
    if not re.fullmatch(r"@[A-Za-z0-9_-]+:e[0-9]+", ref):
        raise ToolPaused("The reviewed control has no actionable accessibility identity")
    return node


class Desktop:
    def __init__(self):
        self.binary = shutil.which("agent-desktop")
        if not self.binary:
            raise ToolPaused("Install agent-desktop and grant Accessibility permission to the current host")

    def _run(self, *args, value=None):
        try:
            result = subprocess.run([self.binary, *args], input=value, capture_output=True, text=True,
                                    encoding="utf-8", timeout=15, check=False)
            response = json.loads(result.stdout)
            if not isinstance(response, dict) or type(response.get("ok")) is not bool:
                raise ValueError("invalid agent-desktop response")
            return response
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise ToolPaused("agent-desktop did not return a usable result") from exc

    def _read(self, *args):
        result = self._run(*args)
        if not result["ok"]:
            raise ToolPaused("agent-desktop could not verify the target")
        return result["data"]

    def _window(self, target, *, wait_for_focus=False):
        windows = self._read("list-windows", "--app", target["app"])
        for window in windows:
            if (window.get("id") == target["window_id"] and window.get("app_name") == target["app"]
                    and window.get("process_instance") == target["process_instance"] and window.get("visible") is True):
                if window.get("is_focused") is True:
                    return window
                if wait_for_focus:
                    self._run("wait", "--event", "focus-changed", "--window-id", target["window_id"], "--timeout", "8000")
                    return self._window(target)
                break
        raise ToolPaused("Bring the reviewed window to the foreground")

    def observe(self, target, *, wait_for_focus=False):
        session = _console_session()
        window = self._window(target, wait_for_focus=wait_for_focus)
        snapshot = self._read("snapshot", "--app", target["app"], "--window-id", target["window_id"],
                              "--max-depth", "20", "--timeout-ms", "7000")
        if snapshot.get("window", {}).get("id") != target["window_id"] or not snapshot.get("complete"):
            raise ToolPaused("Could not read the whole reviewed window")
        nodes = list(_nodes(snapshot["tree"]))
        if "page_url" in target:
            self._check_page(target, window)
            documents = [node for node in nodes if node.get("role") == "webarea"]
            if len(documents) != 1:
                raise ToolPaused("Could not identify one accessible portal document")
            nodes = list(_nodes(documents[0]))
        if not _marker(nodes, target["marker"]):
            raise ToolPaused("The reviewed form or receipt is not visible")
        if target.get("account_marker") and not _marker(nodes, target["account_marker"]):
            raise ToolPaused("The reviewed signed-in account is not visible")
        self._window(target)
        if _console_session() != session:
            raise ToolPaused("The desktop session changed during observation")
        return nodes

    @staticmethod
    def _check_page(target, window):
        try:
            live_page = _page_identity(_focused_page_url(window["pid"]))
        except ValueError as exc:
            raise ToolPaused("Could not verify the exact portal page") from exc
        if live_page != _page_identity(target["page_url"]):
            raise ToolPaused("Open the reviewed portal page")

    def preflight(self, kind, payload):
        nodes = self.observe(payload["target"], wait_for_focus=True)
        if kind == "fill":
            field = _control(nodes, "textfield", payload["field"])
            current = field.get("value", "")
            if current == payload["value"]:
                return None
            if current != payload["before"]:
                raise ToolPaused("The field value changed since review")
            return field["ref_id"]
        if _marker(nodes, payload["result"]["marker"]):
            raise ToolPaused("The expected receipt is already visible")
        for name, reviewed in payload["fields"].items():
            if _control(nodes, "textfield", name).get("value", "") != reviewed:
                raise ToolPaused("Form values changed since review")
        return _control(nodes, "button", payload["button"])["ref_id"]

    def dispatch(self, kind, ref, payload):
        target = payload["target"]
        try:
            _console_session()
            window = self._window(target)
            if "page_url" in target:
                self._check_page(target, window)
        except ToolPaused:
            return False
        if kind == "fill":
            result = self._run("set-value", ref, "--stdin", value=payload["value"])
        else:
            result = self._run("click", ref)
        if not result["ok"]:
            disposition = result.get("error", {}).get("disposition", {})
            if disposition.get("delivery") == "not_delivered" and disposition.get("retry") == "safe":
                return False
        return True

    def verified(self, kind, payload):
        if kind == "submit":
            self.observe(payload["result"])
            return True
        nodes = self.observe(payload["target"])
        return _control(nodes, "textfield", payload["field"]).get("value", "") == payload["value"]
