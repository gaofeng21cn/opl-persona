"""Consume authorized Framework knowledge reads and validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .paths import PersonaPaths


KNOWLEDGE_DOMAIN = "persona"


def read_knowledge_source(knowledge_id: str, paths: PersonaPaths) -> dict[str, str]:
    """Read one accepted private source through Framework's authorized resolver."""
    if not isinstance(knowledge_id, str) or not re.fullmatch(r"[a-z][a-z0-9._-]*", knowledge_id):
        raise ValueError("knowledge_id is invalid")
    command = ["opl", "knowledge", "read-source", "--workspace", str(paths.workspace),
               "--domain", KNOWLEDGE_DOMAIN, "--id", knowledge_id, "--json"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False,
                                env=os.environ | {"OPL_PROFILE_WORKSPACE": str(paths.workspace)})
        if result.returncode:
            raise ValueError("Framework knowledge source is not available for this caller")
        envelope = json.loads(result.stdout)
        source = envelope.get("knowledge_source") if isinstance(envelope, dict) else None
        if (not isinstance(envelope, dict) or envelope.get("version") != "g2" or not isinstance(source, dict)
                or source.get("knowledge_id") != knowledge_id or not isinstance(source.get("content"), str)
                or not isinstance(source.get("source_ref"), str) or not source["source_ref"]):
            raise ValueError("Framework returned an invalid knowledge source identity")
        body = source["content"].encode("utf-8")
        if not 0 < len(body) <= 256 * 1024 or source.get("sha256") != "sha256:" + hashlib.sha256(body).hexdigest():
            raise ValueError("Framework knowledge source content differs from its revision")
        return {key: source[key] for key in ("knowledge_id", "sha256", "content", "source_ref")}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"knowledge source {knowledge_id} requires current Framework readback") from exc


def source_dependencies(value: object) -> list[dict[str, str]]:
    if not isinstance(value, dict) or not value:
        raise ValueError("source_versions must map accepted knowledge identities to revisions")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for identifier, revision in value.items():
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9._-]*", identifier):
            raise ValueError("source_versions knowledge_id is invalid")
        if not isinstance(revision, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", revision):
            raise ValueError("source_versions sha256 is invalid")
        if identifier in seen:
            raise ValueError("source_dependencies knowledge identities must be unique")
        seen.add(identifier)
        result.append({"knowledge_id": identifier, "sha256": revision})
    return result


def verify_knowledge_dependencies(value: object, paths: PersonaPaths) -> dict[str, Any]:
    """Return a fresh body-free verdict from the selected Profile's bindings."""
    try:
        dependencies = source_dependencies(value)
    except ValueError:
        return {"valid": False, "issues": ["source_dependencies_missing_or_invalid"]}
    try:
        with tempfile.TemporaryDirectory(prefix="persona-knowledge-") as temporary:
            request_path = Path(temporary) / "dependencies.json"
            with request_path.open("x", encoding="utf-8") as handle:
                os.chmod(request_path, 0o600)
                json.dump(dependencies, handle)
            command = ["opl", "knowledge", "verify-dependencies", "--workspace", str(paths.workspace),
                       "--domain", KNOWLEDGE_DOMAIN, "--dependencies", str(request_path), "--json"]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False,
                                    env=os.environ | {"OPL_PROFILE_WORKSPACE": str(paths.workspace)})
        if result.returncode:
            raise ValueError("Framework dependency verification failed")
        envelope = json.loads(result.stdout)
        verdict = envelope.get("knowledge_dependencies") if isinstance(envelope, dict) else None
        if (not isinstance(envelope, dict) or envelope.get("version") != "g2"
                or not isinstance(verdict, dict) or type(verdict.get("valid")) is not bool
                or not isinstance(verdict.get("issues"), list)
                or not all(isinstance(issue, str) for issue in verdict["issues"])
                or (verdict["valid"] and verdict["issues"])):
            raise ValueError("Framework returned an invalid dependency verdict")
        return {"valid": verdict["valid"], "issues": verdict["issues"]}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"valid": False, "issues": ["framework_knowledge_verification_unavailable"]}
