"""Compose tool providers for Persona tasks and their direct observation commands."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from .tools.browser import Browser
from .tools.contract import (browser_tab_id, form_readback, normalize_browser_target, normalize_desktop_target,
                             normalize_form, strict_object)
from .tools.desktop import Desktop, desktop_input_lane, normalize_visual
from .tools.github import GitHub, normalize_label
from .tools.package import PackageTool, normalize_connector
from .primitives import text


@dataclass(frozen=True)
class Operation:
    provider: str
    action: str
    args: dict
    lane: str
    target: str

    @property
    def form(self):
        return self.action in {"fill", "submit"}

    def readback(self, driver):
        return form_readback(driver, self.action, self.args) if self.form else driver.readback(self.action, self.args)


class ToolRegistry:
    def __init__(self, paths, *, desktop=Desktop, input_lane=desktop_input_lane, browser=Browser, package=PackageTool,
                 github=GitHub):
        self.paths = paths
        self._desktop = desktop
        self._input_lane = input_lane
        self._browser = browser
        self._package = package
        self._github = github

    @staticmethod
    def _kind(kind, value, *, reviewed=False):
        if kind in ("fill", "submit"):
            target = value.get("target", {}) if isinstance(value, dict) else {}
            provider = "agent-browser" if isinstance(target, dict) and "browser_session" in target else "agent-desktop"
            return provider, kind, value
        if kind != "tool":
            raise ValueError("Use a linked proposal or a supported tool operation")
        metadata = ("title", "task_id", "plan_digest", "step") if reviewed else ()
        value = strict_object(value, required=("provider", "action", "arguments"), optional=metadata)
        return value["provider"], value["action"], value["arguments"]

    def normalize(self, kind, value):
        provider, action, args = self._kind(kind, value)
        if provider == "agent-browser":
            normalized = normalize_form(action, args, normalize_browser_target)
        elif provider == "agent-desktop":
            normalized = (normalize_form(action, args, normalize_desktop_target) if action in ("fill", "submit")
                          else normalize_visual(action, args))
        elif provider == "opl-package" and action == "execute":
            normalized = normalize_connector(args)
        elif provider == "github":
            normalized = normalize_label(action, args)
        else:
            raise ValueError("Unsupported tool provider or action")
        if kind == "tool":
            return {"provider": provider, "action": action, "arguments": normalized}
        return normalized

    def resolve(self, kind, value, operation_id=None, *, window=None, tab_id=None):
        provider, action, args = self._kind(kind, value, reviewed=True)
        if window is not None or tab_id is not None:
            if action not in {"fill", "submit"}:
                raise ValueError("Only a form result supports replacing its observation window or tab")
            key = "result" if action == "submit" else "target"
            target = args[key]
            if tab_id is not None:
                if window is not None or provider != "agent-browser":
                    raise ValueError("A replacement tab requires the original browser session")
                replacement = {"tab_id": browser_tab_id(tab_id)}
            else:
                if provider != "agent-desktop" or "page_url" not in target:
                    raise ValueError("A replacement window requires the original desktop portal and account")
                replacement = {key: text(value, key, 128) for key, value in
                               strict_object(window, required=("window_id", "process_instance")).items()}
            args = {**args, key: {**target, **replacement}}
        if provider == "agent-browser":
            return Operation(provider, action, args, "browser:" + args["target"]["browser_session"], args["target"]["page_url"])
        if provider == "agent-desktop":
            target = args["target"]
            return Operation(provider, action, args, "desktop", target.get("page_url") or target["app"])
        if provider == "opl-package" and action == "execute":
            return Operation(provider, action, args | {"operation_id": operation_id},
                             "package:" + args["package_id"], args["target_ref"])
        if provider == "github":
            target = f"https://github.com/{args['repo']}/issues/{args['number']}"
            return Operation(provider, action, args, "github:" + target, target)
        raise ValueError("Unsupported tool provider or action")

    @contextmanager
    def bind(self, operation):
        args = operation.args
        if operation.provider == "agent-browser":
            driver = self._browser(self.paths, args["target"]["browser_session"])
            with driver.lane():
                yield driver
        elif operation.provider == "agent-desktop":
            with self._input_lane():
                driver = self._desktop()
                if operation.action in ("click", "drag"):
                    driver.visual_root = self.paths.data_root / "visual"
                yield driver
        elif operation.provider == "opl-package":
            driver = self._package(self.paths, args["package_id"])
            with driver.lane():
                yield driver
        elif operation.provider == "github":
            driver = self._github(self.paths, args["repo"], args["number"])
            with driver.lane():
                yield driver

    def desktop_capture(self, target):
        with self._input_lane():
            driver = self._desktop()
            driver.visual_root = self.paths.data_root / "visual"
            return driver.capture(normalize_desktop_target(target))

    def browser_session(self, name):
        return self._browser(self.paths, name)

    def connector_catalog(self, package_id):
        return self._package(self.paths, package_id).describe()

    def github_issue(self, repo, number):
        return self._github(self.paths, repo, number).inspect()
