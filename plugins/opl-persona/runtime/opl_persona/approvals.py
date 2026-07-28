"""Pure approval state transitions for Persona proposals.

Approval changes proposal metadata only.  Domain owners still decide whether
an approved proposal is executable; no mail, website, or vault is touched here.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping


APPROVAL_SCHEMA_VERSION = "opl-persona-approval.v1"


def proposal_digest(proposal: Mapping[str, Any]) -> str:
    """Hash the immutable proposal identity, excluding mutable approval state."""

    material = dict(proposal)
    material.pop("approval", None)
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def approve_proposal(
    proposal: Mapping[str, Any],
    *,
    approval_ref: str,
    external_write_allowed: bool = False,
) -> dict[str, Any]:
    """Return a reviewed proposal, keeping external writes explicitly scoped."""

    if not isinstance(approval_ref, str) or not approval_ref.strip():
        raise ValueError("approval_ref must be a non-empty string")
    current = proposal.get("approval")
    if not isinstance(current, Mapping) or current.get("required") is not True:
        raise ValueError("proposal is not review-gated")
    if not isinstance(proposal.get("proposal_id"), str) or not proposal["proposal_id"].strip():
        raise ValueError("proposal_id must be a non-empty string")
    if current.get("status") not in {"pending", "approved"}:
        raise ValueError("proposal approval status is not approvable")
    digest = proposal_digest(proposal)
    result = copy.deepcopy(dict(proposal))
    result["approval"] = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "status": "approved",
        "required": True,
        "external_write_allowed": bool(external_write_allowed),
        "approval_ref": approval_ref.strip(),
        "proposal_id": proposal.get("proposal_id"),
        "proposal_digest": digest,
    }
    return result
