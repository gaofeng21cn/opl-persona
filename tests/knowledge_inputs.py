"""Synthetic Framework-accepted source fixtures; never a runtime file fallback."""

import hashlib
import json
from pathlib import Path


POLICY_ID = "owner.mail-policy"
POLICY_REF = "knowledge://owner.mail-policy"
POLICY_BODY = "# Mail rules\n\nPrioritize manuscript matters."


def configure_knowledge_inputs(monkeypatch, workspace: Path, *, roles=None, bodies=None):
    roles = roles if roles is not None else {"mail_policy": [POLICY_ID]}
    bodies = bodies if bodies is not None else {POLICY_ID: POLICY_BODY}
    inputs = workspace / "data" / "persona" / "knowledge-inputs.json"
    inputs.parent.mkdir(parents=True, exist_ok=True)
    inputs.write_text(json.dumps({
        "schema_version": "opl-persona-knowledge-inputs.v1", "roles": roles,
    }), encoding="utf-8")

    def read_source(identifier, paths):
        assert paths.workspace == workspace.resolve()
        if identifier not in bodies:
            raise ValueError(f"knowledge source {identifier} requires current Framework readback")
        body = bodies[identifier]
        return {"knowledge_id": identifier, "content": body,
                "source_ref": f"knowledge://{identifier}",
                "sha256": "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()}

    monkeypatch.setattr("opl_persona.policy.read_knowledge_source", read_source)
    return bodies
