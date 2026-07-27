import io
import json
import sys

from opl_persona.app_contributions import (
    ACTION_CONTRACTS,
    DATA_CONTRACTS,
    REQUEST_SCHEMA,
    RESPONSE_SCHEMA,
)
from opl_persona.cli import main


def run_cli(monkeypatch, capsys, request: object) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))
    code = main(["--json", "app-contribution"])
    return code, json.loads(capsys.readouterr().out)


def test_describe_exposes_only_typed_declared_data_contract(monkeypatch, capsys) -> None:
    code, response = run_cli(
        monkeypatch,
        capsys,
        {
            "schema_version": REQUEST_SCHEMA,
            "operation": "describe",
            "ref": "personal.context.v1#today",
        },
    )

    assert code == 0
    assert response["schema_version"] == RESPONSE_SCHEMA
    assert response["ok"] is True
    assert response["result"]["operations"] == [DATA_CONTRACTS["personal.context.v1#today"]]


def test_read_returns_typed_unavailable_projection_without_private_data(monkeypatch, capsys) -> None:
    code, response = run_cli(
        monkeypatch,
        capsys,
        {
            "schema_version": REQUEST_SCHEMA,
            "operation": "read",
            "ref": "personal.context.v1#proposals",
            "input": {},
        },
    )

    assert code == 0
    assert response["result"] == {
        "kind": "data",
        "state": "input_required",
        "result_schema": "personal.context.v1#proposals.result",
        "input_schema": {},
        "reason": "Persona has no configured read-model store for this contribution.",
        "data": None,
    }


def test_execute_never_approves_or_writes_without_owner_handler(monkeypatch, capsys) -> None:
    code, response = run_cli(
        monkeypatch,
        capsys,
        {
            "schema_version": REQUEST_SCHEMA,
            "operation": "execute",
            "ref": "personal.context.v1#proposal.approve",
            "input": {
                "proposal_id": "persona-proposal://website.article/example",
                "approval_ref": "approval://user/example",
            },
        },
    )

    assert code == 0
    assert response["result"] == {
        "kind": "action",
        "status": "not_executed",
        "confirmation_required": True,
        "input_schema": ACTION_CONTRACTS["personal.context.v1#proposal.approve"]["input"],
        "result_schema": "personal.context.v1#proposal.approve.result",
        "execution_policy": "owner_handler_required",
        "reason": "Persona has no configured proposal action handler for this contribution.",
    }


def test_undeclared_ref_is_rejected(monkeypatch, capsys) -> None:
    code, response = run_cli(
        monkeypatch,
        capsys,
        {
            "schema_version": REQUEST_SCHEMA,
            "operation": "read",
            "ref": "personal.context.v1#private-path",
            "input": {},
        },
    )

    assert code == 2
    assert response == {
        "schema_version": RESPONSE_SCHEMA,
        "ok": False,
        "ref": "personal.context.v1#private-path",
        "error": {"code": "invalid_request", "message": "ref is not declared by this package"},
    }


def test_descriptor_ref_sets_match_the_only_supported_abi_refs() -> None:
    assert set(DATA_CONTRACTS) == {
        "personal.context.v1#today",
        "personal.context.v1#proposals",
    }
    assert set(ACTION_CONTRACTS) == {
        "personal.context.v1#proposal.inspect",
        "personal.context.v1#proposal.approve",
    }
