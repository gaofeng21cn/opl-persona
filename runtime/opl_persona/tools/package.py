"""Invoke independently installed connector Packages through OPL v2 (`opld`)."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager

from opl_client import OplClientError, connect

from .contract import Readback, ToolPaused, exclusive_lane, strict_object
from ..primitives import text


CAPABILITY = "tool.execution.v1"


def connector_id(value):
    if (not isinstance(value, str) or len(value) > 96
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?", value) or value == "opl-persona"):
        raise ValueError("Select an installed connector Package other than Persona")
    return value


def normalize_connector(value):
    value = strict_object(value, required=("package_id", "operation", "target_ref", "expected_revision", "input"))
    if not isinstance(value["input"], dict):
        raise ValueError("Connector input must be a JSON object")
    if len(json.dumps(value["input"], allow_nan=False).encode()) > 100_000:
        raise ValueError("Connector input exceeds 100 KB")
    return {
        "package_id": connector_id(value["package_id"]),
        "operation": text(value["operation"], "connector operation", 128),
        "target_ref": text(value["target_ref"], "connector target", 2048),
        "expected_revision": text(value["expected_revision"], "target revision", 256),
        "input": value["input"],
    }


class PackageTool:
    provider = "opl-package"

    def __init__(self, paths, package_id):
        self.paths = paths
        self.package_id = connector_id(package_id)

    @contextmanager
    def lane(self):
        root = self.paths.data_root / "tool-locks"
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        with exclusive_lane(root / f"{self.package_id}.lock", "This connector already has a Persona operation in progress"):
            yield

    def _call(self, phase, value):
        method = "execute" if phase == "execute" else "read"
        ref = f"{CAPABILITY}#{phase}"
        rpc_method = "app.contribution.execute" if method == "execute" else "app.contribution.read"
        rpc_params = (
            {"package_id": self.package_id, "action_id": ref, "payload": value}
            if method == "execute"
            else {"package_id": self.package_id, "ref": ref, "input": value}
        )
        try:
            with connect() as client:
                raw_response = client.call(rpc_method, rpc_params)
            if not isinstance(raw_response, dict):
                raise ValueError("Connector response must be an object")
            if raw_response.get("ok") is False:
                raise ValueError("Connector invocation returned ok=False")
            payload = raw_response.get("result") if isinstance(raw_response.get("result"), dict) else raw_response
            if not isinstance(payload, dict):
                raise ValueError("Connector payload must be an object")
            if payload.get("package_id") not in (None, self.package_id):
                raise ValueError("Connector package_id mismatch")
            if method == "read":
                state_val = payload.get("state") or payload.get("status")
                if state_val not in (None, "ready"):
                    raise ValueError("Connector read is not ready")
                if "kind" in payload and payload.get("kind") != "data":
                    raise ValueError("Connector read did not return data")
            elif "kind" in payload and payload.get("kind") != "action":
                raise ValueError("Connector execute did not return an action")
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            if not isinstance(data, dict):
                raise ValueError("Connector did not return a data object")
            return data
        except (OSError, KeyError, AttributeError, TypeError, ValueError, OplClientError) as exc:
            raise ToolPaused(f"{self.package_id} could not verify {phase} through Framework") from exc

    def describe(self):
        data = self._call("operations", {})
        operations = data.get("operations")
        if data.get("schema_version") != "opl-tool-operations.v1" or not isinstance(operations, list):
            raise ToolPaused("The Package did not publish a connector operations catalog")
        return data

    @staticmethod
    def _identity(args):
        return {key: args[key] for key in ("operation_id", "operation", "target_ref", "expected_revision")}

    def _exchange(self, phase, args):
        identity = self._identity(args)
        value = identity | ({"input": args["input"]} if phase != "receipt" else {})
        data = self._call(phase, value)
        if (data.get("schema_version") != "opl-tool-operation.v1"
                or any(data.get(key) != expected for key, expected in identity.items())):
            raise ToolPaused("The connector returned a different operation, target or revision")
        return data

    def preflight(self, _action, args):
        data = self._exchange("preflight", args)
        if data.get("state") == "applied":
            return None
        if data.get("state") != "ready":
            raise ToolPaused("The connector target or revision needs a new review")
        return args["operation_id"]

    def dispatch(self, _action, operation_id, args):
        if operation_id != args["operation_id"]:
            raise ValueError("Connector operation identity mismatch")
        return self._exchange("execute", args).get("state") != "not_delivered"

    def readback(self, _action, args):
        data = self._exchange("receipt", args)
        target = {"package_id": self.package_id, **self._identity(args)}
        if data.get("state") == "not_delivered":
            return Readback("connector-not-delivered", target, not_delivered=True)
        if data.get("state") != "applied":
            return None
        receipt = data.get("receipt_ref")
        if not isinstance(receipt, str) or not receipt.strip() or len(receipt) > 2048:
            raise ToolPaused("The connector has not returned its original receipt reference")
        return Readback("connector-receipt", target, {"receipt_ref": receipt})
