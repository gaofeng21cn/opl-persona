"""Small, private resource binding records used by Persona owner adapters.

Bindings identify an external authority and its allowed scope.  They never
contain credentials, tokens, content, or a copy of the authority's data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlparse


SCHEMA_VERSION = "opl-persona-resource-binding.v1"
BINDING_STORE_SCHEMA_VERSION = "opl-persona-resource-bindings.v1"
HEALTH_SCHEMA_VERSION = "opl-persona-resource-health.v1"
DEFAULT_OBSIDIAN_BINDING_ID = "my-knowledge"
_BINDING_STORE_NAME = "resource-bindings.json"
_SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "credential",
    "private_key",
    "access_key",
    "api_key",
)
_HEALTH_STATUSES = {"healthy", "degraded", "unavailable", "unknown"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _safe_policy(value: object, *, path: str = "policy") -> Any:
    """Allow JSON policy metadata while rejecting secret-shaped keys."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = _text(key, f"{path} key")
            if any(part in key_text.casefold() for part in _SENSITIVE_KEY_PARTS):
                raise ValueError(f"{path} cannot contain credential material")
            result[key_text] = _safe_policy(item, path=f"{path}.{key_text}")
        return result
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_policy(item, path=f"{path}[]") for item in value]
    raise ValueError(f"{path} must contain JSON-compatible metadata only")


@dataclass(frozen=True)
class ResourceBinding:
    """A refs-only binding from a capability provider to one user resource."""

    capability_id: str
    provider_id: str
    resource_ref: str
    scopes: tuple[str, ...]
    policy: Mapping[str, Any]
    health: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability_id", _text(self.capability_id, "capability_id"))
        object.__setattr__(self, "provider_id", _text(self.provider_id, "provider_id"))
        object.__setattr__(self, "resource_ref", _text(self.resource_ref, "resource_ref"))
        scopes = tuple(dict.fromkeys(_text(item, "scope") for item in self.scopes))
        if not scopes:
            raise ValueError("scopes must contain at least one scope")
        object.__setattr__(self, "scopes", scopes)
        object.__setattr__(self, "policy", _safe_policy(self.policy))
        health = _safe_policy(self.health)
        if not isinstance(health, Mapping):
            raise ValueError("health must be an object")
        status = health.get("status", "unknown")
        if status not in _HEALTH_STATUSES:
            raise ValueError(f"health.status must be one of: {', '.join(sorted(_HEALTH_STATUSES))}")
        object.__setattr__(self, "health", dict(health))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "resource_ref": self.resource_ref,
            "scopes": list(self.scopes),
            "policy": dict(self.policy),
            "health": dict(self.health),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResourceBinding":
        if value.get("schema_version") not in {None, SCHEMA_VERSION}:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
        scopes = value.get("scopes", [])
        if not isinstance(scopes, (list, tuple)):
            raise ValueError("scopes must be a list")
        policy = value.get("policy", {})
        health = value.get("health", {"status": "unknown"})
        if not isinstance(policy, Mapping) or not isinstance(health, Mapping):
            raise ValueError("policy and health must be objects")
        return cls(
            capability_id=value.get("capability_id", ""),
            provider_id=value.get("provider_id", ""),
            resource_ref=value.get("resource_ref", ""),
            scopes=tuple(scopes),
            policy=policy,
            health=health,
        )

    def with_health(self, health: Mapping[str, Any]) -> "ResourceBinding":
        return replace(self, health=dict(health))


def read_binding_health(
    binding: ResourceBinding,
    *,
    probe: Callable[[str], object] | None = None,
) -> dict[str, Any]:
    """Return a refs-only health readback; a probe must not return content."""

    checked_at = _now()
    if probe is None:
        return {
            "schema_version": HEALTH_SCHEMA_VERSION,
            "resource_ref": binding.resource_ref,
            "status": "unknown",
            "checked_at": checked_at,
            "reason": "probe_not_configured",
        }
    try:
        result = probe(binding.resource_ref)
    except Exception as exc:  # pragma: no cover - defensive owner boundary
        return {
            "schema_version": HEALTH_SCHEMA_VERSION,
            "resource_ref": binding.resource_ref,
            "status": "unavailable",
            "checked_at": checked_at,
            "reason": type(exc).__name__,
        }
    if isinstance(result, bool):
        status = "healthy" if result else "unavailable"
        reason = "probe_ok" if result else "probe_failed"
        details: dict[str, Any] = {}
    elif isinstance(result, Mapping):
        status = result.get("status", "unknown")
        if status not in _HEALTH_STATUSES:
            raise ValueError(f"probe returned unsupported status: {status!r}")
        reason = result.get("reason", "probe_result")
        details = {
            key: item
            for key, item in dict(_safe_policy(result)).items()
            if key not in {"schema_version", "resource_ref", "status", "checked_at", "reason"}
        }
    else:
        raise ValueError("probe must return a boolean or metadata object")
    return {
        "schema_version": HEALTH_SCHEMA_VERSION,
        "resource_ref": binding.resource_ref,
        "status": status,
        "checked_at": checked_at,
        "reason": _text(reason, "health reason"),
        **details,
    }


def binding_for_resource(
    *,
    capability_id: str,
    provider_id: str,
    resource_ref: str,
    scopes: list[str] | tuple[str, ...],
    policy: Mapping[str, Any] | None = None,
) -> ResourceBinding:
    """Construct a new unprobed binding without persisting anything."""

    return ResourceBinding(
        capability_id=capability_id,
        provider_id=provider_id,
        resource_ref=resource_ref,
        scopes=tuple(scopes),
        policy=policy or {},
        health={"status": "unknown", "reason": "not_checked"},
    )


def binding_store_path(workspace: Path) -> Path:
    """Return the private, Profile-owned binding store location."""

    return workspace.expanduser().resolve() / "data" / "persona" / _BINDING_STORE_NAME


def load_resource_binding(
    workspace: Path,
    binding_id: str,
) -> ResourceBinding:
    """Load one binding from the selected Profile Workspace and fail closed."""

    selected_id = _text(binding_id, "binding_id")
    path = binding_store_path(workspace)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"Profile resource binding store not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Profile resource binding store is invalid: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("Profile resource binding store must be an object")
    if payload.get("schema_version") != BINDING_STORE_SCHEMA_VERSION:
        raise ValueError(f"binding store schema_version must be {BINDING_STORE_SCHEMA_VERSION}")
    bindings = payload.get("bindings")
    if not isinstance(bindings, Mapping):
        raise ValueError("binding store bindings must be an object")
    value = bindings.get(selected_id)
    if not isinstance(value, Mapping):
        raise KeyError(f"Profile resource binding not found: {selected_id}")
    return ResourceBinding.from_dict(value)


def binding_file_root(
    binding: ResourceBinding,
    *,
    provider_id: str,
    capability_ids: set[str],
    required_scope: str,
) -> Path:
    """Resolve a local owner root from a refs-only binding."""

    if binding.provider_id != provider_id or binding.capability_id not in capability_ids:
        raise ValueError(f"binding is not a {provider_id} resource binding")
    if required_scope not in binding.scopes:
        raise ValueError(f"binding does not grant {required_scope}")
    parsed = urlparse(binding.resource_ref)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise ValueError("binding resource_ref must be a local file URI")
    root = Path(unquote(parsed.path)).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"bound resource root not found: {root}")
    return root
