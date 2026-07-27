from __future__ import annotations

from typing import Any


ABI_SCHEMA = "opl-package-app-contribution-cli.v1"
REQUEST_SCHEMA = "opl-package-app-contribution-request.v1"
RESPONSE_SCHEMA = "opl-package-app-contribution-response.v1"


DATA_CONTRACTS: dict[str, dict[str, Any]] = {
    "personal.context.v1#today": {
        "operation": "read",
        "input": {},
        "result": "personal.context.v1#today.result",
    },
    "personal.context.v1#proposals": {
        "operation": "read",
        "input": {},
        "result": "personal.context.v1#proposals.result",
    },
}

ACTION_CONTRACTS: dict[str, dict[str, Any]] = {
    "personal.context.v1#proposal.inspect": {
        "operation": "execute",
        "confirmation_required": False,
        "input": {
            "proposal_id": {"type": "string", "required": True},
        },
        "result": "personal.context.v1#proposal.inspect.result",
    },
    "personal.context.v1#proposal.approve": {
        "operation": "execute",
        "confirmation_required": True,
        "input": {
            "proposal_id": {"type": "string", "required": True},
            "approval_ref": {"type": "string", "required": True},
        },
        "result": "personal.context.v1#proposal.approve.result",
    },
}


def _error(ref: str | None, message: str) -> dict[str, object]:
    return {
        "schema_version": RESPONSE_SCHEMA,
        "ok": False,
        "ref": ref,
        "error": {"code": "invalid_request", "message": message},
    }


def _response(ref: str, operation: str, result: object) -> dict[str, object]:
    return {
        "schema_version": RESPONSE_SCHEMA,
        "ok": True,
        "ref": ref,
        "operation": operation,
        "result": result,
    }


def _request_input(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("input must be an object")
    return value


def _validate_input(value: dict[str, object], contract: dict[str, Any]) -> None:
    fields = contract["input"]
    assert isinstance(fields, dict)
    unexpected = sorted(set(value) - set(fields))
    if unexpected:
        raise ValueError("input contains unsupported fields: " + ", ".join(unexpected))
    for name, schema in fields.items():
        assert isinstance(schema, dict)
        if schema["required"] and name not in value:
            raise ValueError(f"input.{name} is required")
        if name in value and (not isinstance(value[name], str) or not value[name].strip()):
            raise ValueError(f"input.{name} must be a non-empty string")


def _unavailable_data(contract: dict[str, Any]) -> dict[str, object]:
    return {
        "kind": "data",
        "state": "input_required",
        "result_schema": contract["result"],
        "input_schema": contract["input"],
        "reason": "Persona has no configured read-model store for this contribution.",
        "data": None,
    }


def _unavailable_action(contract: dict[str, Any]) -> dict[str, object]:
    return {
        "kind": "action",
        "status": "not_executed",
        "confirmation_required": contract["confirmation_required"],
        "input_schema": contract["input"],
        "result_schema": contract["result"],
        "execution_policy": "owner_handler_required",
        "reason": "Persona has no configured proposal action handler for this contribution.",
    }


def handle_request(request: object) -> tuple[int, dict[str, object]]:
    ref: str | None = None
    try:
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        raw_ref = request.get("ref")
        if isinstance(raw_ref, str):
            ref = raw_ref
        unexpected = sorted(set(request) - {"schema_version", "operation", "ref", "input"})
        if unexpected:
            raise ValueError("request contains unsupported fields: " + ", ".join(unexpected))
        if request.get("schema_version") != REQUEST_SCHEMA:
            raise ValueError(f"schema_version must be {REQUEST_SCHEMA}")
        operation = request.get("operation")
        if operation not in {"describe", "read", "execute"}:
            raise ValueError("operation must be describe, read, or execute")
        if not ref:
            raise ValueError("ref must be a non-empty string")

        data_contract = DATA_CONTRACTS.get(ref)
        action_contract = ACTION_CONTRACTS.get(ref)
        if data_contract is None and action_contract is None:
            raise ValueError("ref is not declared by this package")

        if operation == "describe":
            if "input" in request:
                raise ValueError("describe does not accept input")
            return 0, _response(
                ref,
                operation,
                {
                    "abi": ABI_SCHEMA,
                    "request_schema": REQUEST_SCHEMA,
                    "response_schema": RESPONSE_SCHEMA,
                    "ref": ref,
                    "operations": [
                        contract
                        for contract in (data_contract, action_contract)
                        if contract is not None
                    ],
                },
            )

        contract = data_contract if operation == "read" else action_contract
        if contract is None:
            raise ValueError(f"{ref} does not support {operation}")
        _validate_input(_request_input(request.get("input")), contract)
        result = _unavailable_data(contract) if operation == "read" else _unavailable_action(contract)
        return 0, _response(ref, operation, result)
    except ValueError as exc:
        return 2, _error(ref, str(exc))
