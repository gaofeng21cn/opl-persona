"""Stable boundaries for a reviewed operation and its readback."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ..primitives import text


class ToolPaused(RuntimeError):
    """A live observation is missing or a tool needs attention."""


@dataclass(frozen=True)
class Readback:
    observation: str
    target: dict
    evidence: dict | None = None
    review_required: bool = False
    not_delivered: bool = False


def strict_object(value, *, required, optional=()):
    if not isinstance(value, dict) or set(required) - value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError("expected fields: " + ", ".join(required) + (", optional: " + ", ".join(optional) if optional else ""))
    return value


def page_identity(value):
    url = urlsplit(value)
    if (url.scheme not in {"https", "http"} or not url.hostname or url.username is not None
            or url.password is not None or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})):
        raise ValueError("portal page must be an HTTPS URL or a loopback test URL, without credentials")
    return (url.scheme, url.hostname, url.port or (443 if url.scheme == "https" else 80),
            url.path or "/", url.query, url.fragment)


def browser_session_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", value):
        raise ValueError("Use a browser session name of 1–32 letters, digits, hyphens or underscores")
    return value


def browser_tab_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Fa-f]{32}", value):
        raise ValueError("Use the tab_id from opl-persona browser inspect")
    return value


def normalize_browser_target(value):
    value = strict_object(value, required=("browser_session", "tab_id", "page_url", "marker", "account_marker"))
    target = {key: text(item, key, 2048) for key, item in value.items()}
    browser_session_name(target["browser_session"])
    browser_tab_id(target["tab_id"])
    page_identity(target["page_url"])
    if target["marker"] == target["account_marker"]:
        raise ValueError("Review the record and signed-in account separately")
    return target


def normalize_desktop_target(value):
    value = strict_object(value, required=("app", "window_id", "process_instance", "marker"),
                          optional=("page_url", "account_marker"))
    target = {key: text(item, key, 2048) for key, item in value.items()}
    if not re.fullmatch(r"w-[A-Za-z0-9_-]{1,96}", target["window_id"]):
        raise ValueError("window_id must come from agent-desktop list-windows")
    if "page_url" in target:
        if "account_marker" not in target:
            raise ValueError("a portal requires a visible signed-in account")
        page_identity(target["page_url"])
    return target


def _field_value(value):
    if not isinstance(value, str) or len(value) > 12000 or "\0" in value:
        raise ValueError("a field value must be bounded text without NUL")
    return value


def normalize_form(kind, value, target_parser):
    if kind == "fill":
        value = strict_object(value, required=("target", "field", "before", "value"))
        return {"target": target_parser(value["target"]), "field": text(value["field"], "field", 512),
                "before": _field_value(value["before"]), "value": _field_value(value["value"])}
    if kind != "submit":
        raise ValueError("unsupported form operation")
    value = strict_object(value, required=("target", "button", "fields", "result"))
    fields = value["fields"]
    if not isinstance(fields, dict) or not fields or len(fields) > 30:
        raise ValueError("submit requires the reviewed form fields")
    target = target_parser(value["target"])
    result = target_parser(value["result"])
    for key in ("app", "window_id", "process_instance", "account_marker", "browser_session", "tab_id"):
        if target.get(key) != result.get(key):
            raise ValueError("submission readback must stay in the same window or tab and account")
    if ("page_url" in target) != ("page_url" in result) or target["marker"] == result["marker"]:
        raise ValueError("submission requires a distinct receipt marker in the same program")
    if "page_url" in target and page_identity(target["page_url"])[:3] != page_identity(result["page_url"])[:3]:
        raise ValueError("submission readback must stay on the approved origin")
    return {"target": target, "button": text(value["button"], "button", 512), "result": result,
            "fields": {text(key, "field name", 512): _field_value(item) for key, item in fields.items()}}


def form_readback(driver, action, arguments):
    if driver.verified(action, arguments):
        key = "result" if action == "submit" else "target"
        return Readback("receipt-visible" if action == "submit" else "field-matches", arguments[key])
    return None


@contextmanager
def exclusive_lane(path: Path, busy: str):
    if os.name != "posix":
        raise ToolPaused("Tool input lanes require a POSIX host")
    import fcntl

    fd = os.open(path, os.O_NOFOLLOW | os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(fd, "ab") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ToolPaused(busy) from exc
        yield
