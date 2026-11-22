"""GitHub issue labels through the user's existing gh login."""

from __future__ import annotations

import json
import re
import subprocess
from contextlib import contextmanager

from .contract import Readback, ToolPaused, exclusive_lane, strict_object
from ..primitives import item_digest, text


def issue_address(repo, number):
    if (not isinstance(repo, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", repo)
            or repo.endswith(("/.", "/.."))):
        raise ValueError("Use a GitHub repository in owner/name form")
    if type(number) is not int or not 1 <= number < 10**10:
        raise ValueError("Use a positive GitHub issue number")
    return repo.lower(), number


def normalize_label(action, args):
    if action != "issue.label.add":
        raise ValueError("Unsupported GitHub operation")
    args = strict_object(args, required=("repo", "number", "account", "issue_id", "expected_revision", "label"))
    repo, number = issue_address(args["repo"], args["number"])
    return {
        "repo": repo, "number": number,
        **{key: text(args[key], key, limit) for key, limit in
           (("account", 100), ("issue_id", 128), ("expected_revision", 80), ("label", 50))},
    }


class GitHub:
    provider = "github"

    def __init__(self, paths, repo, number):
        self.paths = paths
        self.repo, self.number = issue_address(repo, number)
        self.api = f"repos/{self.repo}/issues/{self.number}"
        self.url = f"https://github.com/{self.repo}/issues/{self.number}"

    @contextmanager
    def lane(self):
        root = self.paths.data_root / "tool-locks"
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        key = item_digest({"url": self.url})[7:]
        with exclusive_lane(root / f"github-{key}.lock", "This GitHub issue already has a Persona operation in progress"):
            yield

    def _call(self, endpoint, *, query=None, labels=None):
        args = ["gh", "api", "--hostname", "github.com", endpoint]
        if query is not None:
            args += ["--jq", query]
        if labels is not None:
            args += ["--method", "POST", "--input", "-"]
        try:
            result = subprocess.run(args, input=json.dumps({"labels": labels}) if labels is not None else None,
                                    capture_output=True, text=True, timeout=15, check=True)
            return json.loads(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise ToolPaused("GitHub did not return a usable issue observation through gh") from exc

    def inspect(self):
        issue = self._call(self.api, query="{issue_id:.node_id,url:.html_url,state,labels:[.labels[].name]}")
        account = self._call("user", query="{login}")
        if (not isinstance(issue, dict) or not isinstance(account, dict) or not account.get("login")
                or not isinstance(issue.get("url"), str) or issue["url"].lower() != self.url
                or not isinstance(issue.get("issue_id"), str) or issue.get("state") not in ("open", "closed")
                or not isinstance(issue.get("labels"), list)
                or not all(isinstance(label, str) for label in issue["labels"])):
            raise ToolPaused("The authenticated GitHub issue identity is unavailable")
        revision = {"account": account["login"], "issue_id": issue["issue_id"], "state": issue["state"],
                    "labels": sorted(issue["labels"])}
        return {"repo": self.repo, "number": self.number, "target_ref": issue["url"], **revision,
                "expected_revision": item_digest(revision)}

    def _observe(self, args):
        issue = self.inspect()
        if any(issue[key] != args[key] for key in ("account", "issue_id")):
            raise ToolPaused("GitHub account or issue identity changed")
        return issue

    def preflight(self, _action, args):
        issue = self._observe(args)
        if issue["expected_revision"] != args["expected_revision"]:
            raise ToolPaused("GitHub issue state or labels changed since review")
        return args["label"] if args["label"] not in issue["labels"] else None

    def dispatch(self, action, label, args):
        try:
            if self.preflight(action, args) != label:
                return False
        except ToolPaused:
            return False
        self._call(self.api + "/labels", labels=[label])
        return True

    def readback(self, _action, args):
        issue = self._observe(args)
        if args["label"] not in issue["labels"]:
            return None
        identity = {key: issue[key] for key in ("account", "issue_id", "target_ref")}
        return Readback("github-label-present", identity | {"label": args["label"]},
                        {"receipt_ref": issue["target_ref"], "label": args["label"]})
