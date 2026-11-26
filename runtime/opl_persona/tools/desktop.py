"""Bind local input to a fresh foreground window and verify its observed effect."""

from __future__ import annotations

import hashlib
import json
import math
import os
import plistlib
import re
import shutil
import subprocess
import struct
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from .contract import Readback, ToolPaused, normalize_desktop_target, page_identity, strict_object


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
    provider = "agent-desktop"

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

    def observe(self, target, *, wait_for_focus=False, visual=False):
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
        if not _marker(nodes, target["marker"]) and not (visual and window.get("title") == target["marker"]):
            raise ToolPaused("The reviewed form or receipt is not visible")
        if target.get("account_marker") and not _marker(nodes, target["account_marker"]):
            raise ToolPaused("The reviewed signed-in account is not visible")
        self._window(target)
        if _console_session() != session:
            raise ToolPaused("The desktop session changed during observation")
        return nodes

    def capture(self, target):
        self.observe(target, wait_for_focus=True, visual=True)
        window = self._window(target)
        bounds = window.get("bounds")
        keys = ("x", "y", "width", "height")
        if (not isinstance(bounds, dict) or any(type(bounds.get(key)) not in (int, float)
                                               or not math.isfinite(bounds[key]) for key in keys)
                or bounds["width"] <= 0 or bounds["height"] <= 0):
            raise ToolPaused("The reviewed window has no usable screen geometry")
        self.visual_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.visual_root) as directory:
            image = Path(directory) / "window.png"
            self._read("screenshot", "--app", target["app"], "--window-id", target["window_id"], str(image))
            current = self._window(target)
            if current.get("bounds") != bounds:
                raise ToolPaused("The reviewed window moved during image capture")
            if "page_url" in target:
                self._check_page(target, current)
            data = image.read_bytes()
            if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 24:
                raise ToolPaused("The desktop tool did not return a window PNG")
            size = struct.unpack("!II", data[16:24])
            if not all(size):
                raise ToolPaused("The window image has invalid dimensions")
            digest = hashlib.sha256(data).hexdigest()
            destination = self.visual_root / f"{digest}.png"
            image.chmod(0o600)
            os.replace(image, destination)
        return {"target": target, "bounds": bounds, "size": list(size), "digest": f"sha256:{digest}",
                "path": str(destination)}

    @staticmethod
    def _screen_point(point, capture):
        width, height = capture["size"]
        x, y = point
        if not 0 <= x < width or not 0 <= y < height:
            raise ToolPaused("The reviewed point is outside the window image")
        bounds = capture["bounds"]
        return (math.floor(bounds["x"] + x * bounds["width"] / width),
                math.floor(bounds["y"] + y * bounds["height"] / height))

    def _visual_preflight(self, kind, payload):
        capture = self.capture(payload["target"])
        if capture["digest"] != payload["before"]:
            raise ToolPaused("The window image changed since review")
        points = [self._screen_point(payload["at"], capture)]
        if kind == "drag":
            points.append(self._screen_point(payload["to"], capture))
        return capture["bounds"], points

    def readback(self, _action, payload):
        capture = self.capture(payload["target"])
        return Readback("visual-result", payload["target"], capture, review_required=True)

    def confirm_readback(self, capture):
        digest = capture["digest"].removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("The reviewed window image digest is invalid")
        image = self.visual_root / f"{digest}.png"
        if image.is_symlink() or not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != digest:
            raise ValueError("The observed window image changed or is missing")

    @staticmethod
    def _check_page(target, window):
        try:
            live_page = page_identity(_focused_page_url(window["pid"]))
        except ValueError as exc:
            raise ToolPaused("Could not verify the exact portal page") from exc
        if live_page != page_identity(target["page_url"]):
            raise ToolPaused("Open the reviewed portal page")

    def preflight(self, kind, payload):
        if kind in ("click", "drag"):
            return self._visual_preflight(kind, payload)
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
            if kind in ("click", "drag"):
                if self._visual_preflight(kind, payload) != ref or self._window(target).get("bounds") != ref[0]:
                    return False
        except ToolPaused:
            return False
        if kind == "drag":
            (start_x, start_y), (end_x, end_y) = ref[1]
            result = self._run("--headed", "drag", f"--from-xy={start_x},{start_y}", f"--to-xy={end_x},{end_y}")
        elif kind == "click":
            (x, y), = ref[1]
            result = self._run("--headed", "mouse-click", f"--xy={x},{y}")
        elif kind == "fill":
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


def normalize_visual(action, value):
    if action not in ("click", "drag"):
        raise ValueError("Unsupported desktop visual operation")
    required = ("target", "before", "at", "to") if action == "drag" else ("target", "before", "at")
    value = strict_object(value, required=required)
    digest = value["before"]
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Use the reviewed window image digest")
    result = {"target": normalize_desktop_target(value["target"]), "before": digest}
    for key in required[2:]:
        point = value[key]
        if not isinstance(point, list) or len(point) != 2 or any(type(i) is not int or i < 0 for i in point):
            raise ValueError("Visual points are [x, y] integer pixels in the reviewed image")
        result[key] = point
    return result
