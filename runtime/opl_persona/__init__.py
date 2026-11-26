"""OPL Persona: cross-domain context and reviewable output proposals."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def _ensure_opl_client() -> None:
    try:
        import opl_client  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    candidates: list[Path] = []
    env_root = os.environ.get("OPL_PYTHON_SDK_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root))
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / ".worktrees/opl-v2/sdks/python-client/src")
        candidates.append(parent / "one-person-lab/sdks/python-client/src")
    for candidate in candidates:
        if (candidate / "opl_client/__init__.py").is_file() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            return


_ensure_opl_client()

from .core import (  # noqa: E402
    build_mail_triage_proposals,
    build_memo_proposals,
    build_publication_proposals,
)
from .policy import MarkdownPolicyLoader, PolicySnapshot, load_markdown_policies, load_policy  # noqa: E402

__all__ = [
    "PolicySnapshot",
    "MarkdownPolicyLoader",
    "build_mail_triage_proposals",
    "build_memo_proposals",
    "build_publication_proposals",
    "load_markdown_policies",
    "load_policy",
]
