from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .app_contributions import handle_request
from .core import (
    build_inbox_capture_proposals,
    build_mail_triage_proposals,
    build_memo_proposals,
    build_obsidian_note_proposals,
    build_publication_proposals,
    dump_json,
)
from .paths import PersonaPaths
from .obsidian import memo_proposals_from_file
from .bindings import (
    DEFAULT_OBSIDIAN_BINDING_ID,
    check_resource_binding,
    list_resource_bindings,
    set_resource_binding,
)


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
    setup = sub.add_parser("setup", help="检查或初始化 Profile Workspace")
    setup_actions = setup.add_subparsers(dest="setup_action", required=True)
    setup_status = setup_actions.add_parser("status", help="显示首次配置步骤")
    setup_status.set_defaults(setup_handler="status")
    setup_init = setup_actions.add_parser("init", help="创建缺失的 Profile 模板")
    setup_init.set_defaults(setup_handler="init")
    binding = sub.add_parser("binding", help="管理 Profile Workspace 资源绑定")
    binding_actions = binding.add_subparsers(dest="binding_action", required=True)
    binding_list = binding_actions.add_parser("list", help="列出 refs-only 绑定")
    binding_list.set_defaults(binding_handler="list")
    binding_set = binding_actions.add_parser("set", help="绑定一个本地资源目录")
    binding_set.add_argument("--id", required=True, dest="binding_id")
    binding_set.add_argument("--provider", required=True, choices=["obsidian"])
    binding_set.add_argument("--path", required=True, help="资源目录；只保存为 file URI")
    binding_set.add_argument(
        "--capability-id",
        default="knowledge.obsidian.v1",
        choices=["knowledge.obsidian.v1", "knowledge.documents.v1"],
    )
    binding_set.add_argument("--scope", action="append", default=["notes.read"])
    binding_set.set_defaults(binding_handler="set")
    binding_check = binding_actions.add_parser("check", help="检查绑定目录是否可用")
    binding_check.add_argument("--id", required=True, dest="binding_id")
    binding_check.set_defaults(binding_handler="check")
    sub.add_parser(
        "app-contribution",
        help="Serve the Package-owned app contribution JSON ABI.",
    )
    proposal = sub.add_parser("proposal")
    proposal_sub = proposal.add_subparsers(dest="kind", required=True)
    for kind in ("publication", "memo", "mail-triage", "inbox-capture", "obsidian-note"):
        command = proposal_sub.add_parser(kind)
        command.add_argument("--input", required=True, help="JSON file or - for stdin")
    memo_file = proposal_sub.add_parser("memo-file", help="从 Obsidian Markdown 只读生成 memo 提案")
    memo_file.add_argument("--path", required=True)
    memo_file.add_argument(
        "--binding",
        default=DEFAULT_OBSIDIAN_BINDING_ID,
        help="Profile Workspace resource binding id",
    )
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
        elif args.command == "setup":
            result = (
                paths.setup_status()
                if args.setup_handler == "status"
                else paths.init_workspace()
            )
            result = {"ok": True, "setup": result}
        elif args.command == "binding":
            if args.binding_handler == "list":
                result = {
                    "ok": True,
                    "bindings": {
                        binding_id: binding.to_dict()
                        for binding_id, binding in list_resource_bindings(paths.workspace).items()
                    },
                }
            elif args.binding_handler == "check":
                result = {"ok": True, "binding": check_resource_binding(paths.workspace, args.binding_id)}
            else:
                resource = Path(args.path).expanduser().resolve()
                if not resource.is_dir():
                    raise ValueError(f"binding path must be an existing directory: {resource}")
                binding = set_resource_binding(
                    paths.workspace,
                    binding_id=args.binding_id,
                    capability_id=args.capability_id,
                    provider_id=args.provider,
                    resource_ref=resource.as_uri(),
                    scopes=tuple(dict.fromkeys(args.scope)),
                    policy={"approval_required": True},
                )
                result = {"ok": True, "binding": binding.to_dict()}
        elif args.kind == "publication":
            result = build_publication_proposals(_read_input(args.input))
        elif args.kind == "memo":
            result = build_memo_proposals(_read_input(args.input))
        elif args.kind == "mail-triage":
            result = build_mail_triage_proposals(_read_input(args.input))
        elif args.kind == "inbox-capture":
            result = build_inbox_capture_proposals(_read_input(args.input))
        elif args.kind == "obsidian-note":
            result = build_obsidian_note_proposals(_read_input(args.input))
        else:
            result = memo_proposals_from_file(
                Path(args.path),
                binding_id=args.binding,
            )
        sys.stdout.write(dump_json(result))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"opl-persona: {exc}\n")
        return 2
