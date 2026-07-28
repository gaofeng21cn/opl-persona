import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from opl_persona.app_contributions import (
    ACTION_CONTRACTS,
    DATA_CONTRACTS,
    REQUEST_SCHEMA,
    RESPONSE_SCHEMA,
)
from opl_persona.cli import main
from opl_persona.inbox import InboxStore
from opl_persona.paths import PersonaPaths


ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "opl-persona"


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


def test_read_projects_persona_private_inbox_refs_only(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setenv("OPL_PERSONA_HOME", str(tmp_path / "persona"))
    InboxStore.from_paths(PersonaPaths.resolve()).capture(
        capture_id="paper://demo",
        item_kind="paper",
        title="Demo paper",
        summary="A bounded summary.",
        source_refs=["https://example.org/paper"],
    )

    code, response = run_cli(
        monkeypatch,
        capsys,
        {
            "schema_version": REQUEST_SCHEMA,
            "operation": "read",
            "ref": "personal.inbox.v1#recent",
            "input": {},
        },
    )

    assert code == 0
    result = response["result"]
    assert result["state"] == "ready"
    assert result["data"]["count"] == 1
    assert result["data"]["items"][0] == {
        "item_id": result["data"]["items"][0]["item_id"],
        "capture_id": "paper://demo",
        "item_kind": "paper",
        "title": "Demo paper",
        "summary": "A bounded summary.",
        "source_refs": ["https://example.org/paper"],
        "status": "staged",
        "route_refs": [],
        "created_at": result["data"]["items"][0]["created_at"],
        "updated_at": result["data"]["items"][0]["updated_at"],
    }
    assert "body" not in result["data"]["items"][0]


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


def test_execute_generates_only_declared_reviewable_proposals(monkeypatch, capsys) -> None:
    requests = [
        (
            "communications.mail.v1#triage.propose",
            {
                "email_ref": "email-store://account/inbox/123",
                "source_refs": ["email-store://account/inbox/123"],
                "subject": "Review request",
                "summary": "Response needed.",
                "classification": "needs_decision",
                "priority": "high",
                "rationale": "A short response window is stated.",
                "uncertainty": "The deadline is not independently verified.",
                "recommended_action": "Read and decide.",
                "policy_refs": ["policy://persona/mail-triage/v1"],
                "policy_digest": "sha256:" + "a" * 64,
            },
            ["personal.inbox.v1.capture", "mail.triage"],
        ),
        (
            "personal.inbox.v1#capture.propose",
            {
                "capture_id": "knowledge://memo/1",
                "item_kind": "knowledge",
                "title": "New memo",
                "summary": "A memo ready for review.",
                "source_refs": ["obsidian://vault/memo.md"],
            },
            ["personal.inbox.v1.capture"],
        ),
        (
            "knowledge.obsidian.v1#note.propose",
            {
                "operation": "create",
                "target_path": "Knowledge/new-note.md",
                "frontmatter": {"title": "New note"},
                "body": "# New note",
                "links": [],
                "tags": ["policy"],
                "evidence_refs": ["obsidian://vault/memo.md"],
                "expected_digest": "absent",
            },
            ["knowledge.obsidian.note.v1"],
        ),
    ]

    for ref, proposal_input, proposal_kinds in requests:
        code, response = run_cli(
            monkeypatch,
            capsys,
            {
                "schema_version": REQUEST_SCHEMA,
                "operation": "execute",
                "ref": ref,
                "input": proposal_input,
            },
        )

        assert code == 0
        assert response["ok"] is True
        assert response["ref"] == ref
        assert response["result"]["kind"] == "proposal"
        assert response["result"]["status"] == "proposed"
        assert response["result"]["execution_policy"] == "proposal_only"
        assert response["result"]["result_schema"] == ACTION_CONTRACTS[ref]["result"]
        bundle = response["result"]["proposal_bundle"]
        assert [item["proposal_kind"] for item in bundle["proposals"]] == proposal_kinds
        assert all(item["approval"]["external_write_allowed"] is False for item in bundle["proposals"])


def test_mail_triage_app_action_accepts_markdown_policy_and_recipient_evidence(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    policy = tmp_path / "policies" / "mail-triage.md"
    policy.parent.mkdir(parents=True)
    policy.write_text("# Mail rules\n\n投稿论文优先。", encoding="utf-8")
    email_ref = "email-store://account/inbox/456"
    code, response = run_cli(
        monkeypatch,
        capsys,
        {
            "schema_version": REQUEST_SCHEMA,
            "operation": "execute",
            "ref": "communications.mail.v1#triage.propose",
            "input": {
                "email_ref": email_ref,
                "source_refs": [email_ref],
                "subject": "Manuscript revision",
                "summary": "A revision deadline needs attention.",
                "policy_workspace": str(tmp_path),
                "to": ["gaof57@mail.sysu.edu.cn"],
                "cc": [],
                "bcc": [],
                "user_addresses": ["gaof57@mail.sysu.edu.cn"],
                "actual_first_author": {"email": "student@example.edu"},
                "team_members": [{"email": "student@example.edu"}],
            },
        },
    )

    assert code == 0
    assert response["ok"] is True
    triage = response["result"]["proposal_bundle"]["proposals"][1]
    assert triage["policy_digest"].startswith("sha256:")
    assert triage["payload"]["forward_to"]["email"] == "student@example.edu"


def test_execute_rejects_undeclared_proposal_input_fields(monkeypatch, capsys) -> None:
    code, response = run_cli(
        monkeypatch,
        capsys,
        {
            "schema_version": REQUEST_SCHEMA,
            "operation": "execute",
            "ref": "personal.inbox.v1#capture.propose",
            "input": {
                "capture_id": "knowledge://memo/1",
                "item_kind": "knowledge",
                "title": "New memo",
                "summary": "A memo ready for review.",
                "source_refs": ["obsidian://vault/memo.md"],
                "vault_path": "/private/vault",
            },
        },
    )

    assert code == 2
    assert response == {
        "schema_version": RESPONSE_SCHEMA,
        "ok": False,
        "ref": "personal.inbox.v1#capture.propose",
        "error": {
            "code": "invalid_request",
            "message": "input contains unsupported fields: vault_path",
        },
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
        "personal.inbox.v1#recent",
    }
    assert set(ACTION_CONTRACTS) == {
        "personal.context.v1#proposal.inspect",
        "personal.context.v1#proposal.approve",
        "communications.mail.v1#triage.propose",
        "personal.inbox.v1#capture.propose",
        "knowledge.obsidian.v1#note.propose",
    }


def test_installed_carrier_wrapper_serves_abi_without_the_source_checkout(tmp_path: Path) -> None:
    installed_root = tmp_path / "installed-plugin"
    shutil.copytree(PLUGIN_ROOT, installed_root)
    wrapper = installed_root / "bin" / "opl-persona"
    wrapper.chmod(0o755)
    request = {
        "schema_version": REQUEST_SCHEMA,
        "operation": "execute",
        "ref": "personal.inbox.v1#capture.propose",
        "input": {
            "capture_id": "knowledge://memo/1",
            "item_kind": "knowledge",
            "title": "New memo",
            "summary": "A memo ready for review.",
            "source_refs": ["obsidian://vault/memo.md"],
        },
    }
    environment = os.environ | {"PYTHONPATH": ""}
    result = subprocess.run(
        [str(wrapper), "--json", "app-contribution"],
        cwd=tmp_path,
        env=environment,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["schema_version"] == RESPONSE_SCHEMA
    assert response["ok"] is True
    assert response["ref"] == request["ref"]
    assert response["result"]["execution_policy"] == "proposal_only"
    assert response["result"]["proposal_bundle"]["proposals"][0]["target"] == "personal.inbox.v1"
