from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .app_contributions import handle_request
from .core import build_memo_proposals, build_publication_proposals, dump_json
from .paths import PersonaPaths
from .obsidian import memo_proposals_from_file


def _read_input(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8") if path != "-" else sys.stdin.read())
    if not isinstance(value, dict):
        raise ValueError("input must be a JSON object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opl-persona")
    parser.add_argument("--json", action="store_true", help="reserved for CLI compatibility")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("workspace-init")
    sub.add_parser(
        "app-contribution",
        help="Serve the Package-owned app contribution JSON ABI.",
    )
    proposal = sub.add_parser("proposal")
    proposal_sub = proposal.add_subparsers(dest="kind", required=True)
    for kind in ("publication", "memo"):
        command = proposal_sub.add_parser(kind)
        command.add_argument("--input", required=True, help="JSON file or - for stdin")
    memo_file = proposal_sub.add_parser("memo-file", help="从 Obsidian Markdown 只读生成 memo 提案")
    memo_file.add_argument("--path", required=True)
    memo_file.add_argument("--vault", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "app-contribution":
            code, response = handle_request(json.load(sys.stdin))
            sys.stdout.write(dump_json(response))
            return code
        paths = PersonaPaths.resolve()
        if args.command == "doctor":
            result = paths.doctor()
        elif args.command == "workspace-init":
            result = paths.init_workspace()
        elif args.kind == "publication":
            result = build_publication_proposals(_read_input(args.input))
        elif args.kind == "memo":
            result = build_memo_proposals(_read_input(args.input))
        else:
            result = memo_proposals_from_file(
                Path(args.path),
                vault=Path(args.vault) if args.vault else None,
            )
        sys.stdout.write(dump_json(result))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"opl-persona: {exc}\n")
        return 2
