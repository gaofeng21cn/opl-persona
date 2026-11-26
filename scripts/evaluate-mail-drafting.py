#!/usr/bin/env python3
"""Exercise accepted Persona feedback through two fresh Codex sessions and a Relay draft."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
POLICY = "synthetic.academic-mail"
NEW_GREETING = "Professor Tanaka,"
NEW_CLOSE = "I appreciate your guidance."
BEFORE = "# Academic correspondence\nBegin with 'Hello Keiko,' and close with 'Talk soon!'.\n"
AFTER = f"# Academic correspondence\nBegin with '{NEW_GREETING}' and close with '{NEW_CLOSE}' before the signature.\n"
PROMPT = (
    "Use the accepted OPL Persona drafting context below for this synthetic academic email. "
    "Draft a brief English note to Keiko Tanaka thanking her for feedback on the poster title. "
    "The latest title is 'Methods in Practice'. Old thread greeting: Hi Keiko. "
    "Return JSON with exactly subject and body. Leave the standalone signature to Relay. "
    "Use only the provided synthetic context and facts."
)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def sha(body):
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def seed(root):
    profile = root / "profile"
    vault = root / "vault"
    vault.mkdir()
    source = vault / "mail.md"
    source.write_text(BEFORE, encoding="utf-8")
    registry = profile / "shared/memory/sources.json"
    scope = {"kind": "topic", "id": "synthetic.mail"}
    write_json(registry, {
        "surface_kind": "opl_knowledge_source_registry", "version": "knowledge-source-registry.v2",
        "registry_id": "synthetic.eval", "owner": "synthetic.eval",
        "sources": [{"source_id": "synthetic.vault", "root": str(vault), "status": "active", "writable": True,
                     "grants": [{"workspace_root": str(profile), "domains": ["persona"],
                                 "write_domains": ["persona"], "scope_ids": [scope["id"]]}]}],
        "items": [{"surface_kind": "opl_durable_knowledge_item", "version": "durable-knowledge-item.v2",
                   "knowledge_id": POLICY, "title": "Academic correspondence", "owner": "synthetic.eval",
                   "scope": scope, "content_kind": "policy", "status": "active",
                   "body_ref": {"kind": "source_path", "source_id": "synthetic.vault", "ref": source.name, "sha256": sha(BEFORE)},
                   "applicability": {"domains": ["persona"], "stages": ["academic-mail"]},
                   "reviewed_at": "2026-01-01T00:00:00Z", "next_review_at": "2099-01-01T00:00:00Z",
                   "authority_boundary": {"semantic_body_owner": "synthetic.eval", "opl_role": "catalog_recall_and_receipt_projection_only"}}],
    })
    write_json(profile / "shared/memory/knowledge-bindings.json", {
        "surface_kind": "opl_knowledge_source_bindings", "version": "knowledge-source-bindings.v2",
        "registries": [{"registry_ref": str(registry), "source_ids": ["synthetic.vault"], "scope_ids": [scope["id"]]}],
    })
    write_json(profile / "data/persona/knowledge-inputs.json", {
        "schema_version": "opl-persona-knowledge-inputs.v1", "roles": {"mail_policy": [POLICY]},
    })
    return profile, vault, scope


def _command(argv, *, env, cwd, payload=None):
    result = subprocess.run(argv, cwd=cwd, env=env, input=payload, text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"{Path(argv[0]).name} exited {result.returncode}: {result.stderr[-1300:]}")
    return result.stdout


def draft(args, root, env, persona):
    context = json.loads(_command([str(persona), "--json", "context", "list", "--input", "-"],
                                  cwd=root, env=env, payload='{"purpose":"mail-drafting"}'))
    accepted = context["result"]["data"]["active_context"]["drafting_policy"]["documents"]
    if [item["knowledge_id"] for item in accepted] != [POLICY]:
        raise RuntimeError("Persona did not read the expected synthetic policy")
    schema = root / "response.schema.json"
    write_json(schema, {
        "type": "object", "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
        "required": ["subject", "body"], "additionalProperties": False,
    })
    last = root / "draft.json"
    argv = [args.codex, "exec", "--ignore-user-config", "--ephemeral", "--sandbox", "read-only",
            "--skip-git-repo-check", "--json", "--output-schema", str(schema), "-o", str(last)]
    if args.model:
        argv += ["-m", args.model]
    prompt = PROMPT + "\n\nAccepted drafting context:\n" + json.dumps(accepted, ensure_ascii=False)
    lines = _command([*argv, "-"], env=env, cwd=root, payload=prompt)
    events = [json.loads(line) for line in lines.splitlines() if line.startswith("{")]
    thread = next(event["thread_id"] for event in events if event.get("type") == "thread.started")
    return thread, json.loads(last.read_text(encoding="utf-8"))


def relay_blueprint(args, root, env, profile, message):
    data = profile / "data/relay"
    data.mkdir(parents=True, exist_ok=True)
    account = data / "accounts.toml"
    account.write_text(
        '[[accounts]]\naccount_id = "synthetic"\nemail = "morgan@example.test"\n'
        '[accounts.imap]\nhost = "imap.example.test"\nport = 993\nsecurity = "ssl"\n'
        'username = "morgan@example.test"\ncredential_ref = "unused-test-reference"\n', encoding="utf-8",
    )
    body_file = root / "body.txt"
    body_file.write_text(message["body"], encoding="utf-8")
    signature = root / "signature.txt"
    signature.write_text("Dr. Morgan", encoding="utf-8")
    result = json.loads(_command(
        [args.relay, "--json", "draft", "server-create", "--account", "synthetic", "--request-id", "persona-style-eval",
         "--to", "keiko@example.test", "--subject", message["subject"], "--body-file", str(body_file),
         "--signature-file", str(signature)], env=env, cwd=root,
    ))
    draft_state = result.get("draft", result)
    if draft_state.get("state") != "prepared" or draft_state.get("send_allowed") is not False:
        raise RuntimeError("Relay did not prepare a no-send draft")
    if NEW_GREETING not in draft_state["body_text"] or NEW_CLOSE not in draft_state["body_text"]:
        raise RuntimeError("The prepared Relay draft dropped the accepted preference")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework-root", type=Path, required=True)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--relay", default="opl-relay")
    parser.add_argument("--model")
    args = parser.parse_args()
    persona = ROOT / "bin/opl-persona"
    with tempfile.TemporaryDirectory(prefix="opl-persona-mail-eval-") as temp:
        root = Path(temp)
        profile, vault, scope = seed(root)
        env = {**os.environ, "OPL_PROFILE_WORKSPACE": str(profile), "OPL_STATE_DIR": str(root / "framework-state"),
               "PATH": str(args.framework_root.resolve() / "bin") + os.pathsep + os.environ["PATH"]}

        def command(*argv, payload=None):
            raw = _command([str(persona), "--json", *argv], env=env, cwd=root,
                           payload=None if payload is None else json.dumps(payload))
            return json.loads(raw)

        first_thread, initial = draft(args, root, env, persona)
        if "Hello Keiko," not in initial["body"] or "Talk soon!" not in initial["body"]:
            raise RuntimeError("The baseline email did not use the initial accepted policy")
        command("binding", "set", "--id", "eval-vault", "--provider", "obsidian", "--path", str(vault), "--scope", "notes.write")
        correction = initial["body"].replace("Hello Keiko,", NEW_GREETING).replace("Talk soon!", NEW_CLOSE)
        proposal = command("proposal", "mail-feedback", "--input", "-", payload={
            "disposition": "reuse", "draft_ref": "relay-draft://synthetic/reply?revision=1",
            "draft_fingerprint": sha(initial["body"]), "final_ref": "relay-draft://synthetic/reply?revision=2",
            "final_fingerprint": sha(correction),
            "note": {"target_path": "mail.md", "expected_digest": sha(BEFORE), "body": AFTER,
                     "knowledge_writeback": {"knowledge_id": POLICY, "target_scope": scope, "content_kind": "policy",
                         "proposed_rule_or_mechanism": "Use the approved academic greeting and closing",
                         "evidence_class": "synthetic", "review_requirement": "owner review"}},
        })["result"]["proposal_bundle"]["stored_items"][0]
        identity = {"proposal_id": proposal["id"], "expected_digest": proposal["proposal_digest"]}
        command("proposal", "approve", "--input", "-", payload=identity | {"approval_ref": "approval://eval/review"})
        command("proposal", "authorize-obsidian", "--input", "-", payload=identity | {
            "binding_id": "eval-vault", "approval_ref": "approval://eval/write", "confirmation": "confirmed",
            "knowledge_review": {"reviewer": "synthetic.eval", "reviewed_at": "2026-01-02T00:00:00Z",
                                 "next_review_at": "2099-01-01T00:00:00Z"},
        })
        command("proposal", "apply-obsidian", "--input", "-", payload=identity | {
            "binding_id": "eval-vault", "external_approval_ref": "approval://eval/write",
        })
        second_thread, final = draft(args, root, env, persona)
        if second_thread == first_thread or (NEW_GREETING not in final["body"] or NEW_CLOSE not in final["body"]
                or "Talk soon!" in final["body"] or "Hello Keiko," in final["body"]
                or "Methods in Practice" not in final["body"]):
            raise RuntimeError("The new session did not adopt the reviewed update in a usable draft")
        relay_blueprint(args, root, env, profile, final)
        print(json.dumps({"passed": True, "fresh_sessions": 2, "accepted_preference_in_relay_draft": True,
                          "mailbox_writes": 0, "sends": 0}))


if __name__ == "__main__":
    main()
