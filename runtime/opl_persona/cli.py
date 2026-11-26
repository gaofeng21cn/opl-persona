from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .app_contributions import handle_request
from .tool_registry import ToolRegistry
from .core import (
    build_inbox_capture_proposals,
    build_mail_triage_proposals,
    build_memo_proposals,
    build_obsidian_note_proposals,
    build_publication_proposals,
    dump_json,
)
from .paths import PersonaPaths
from .proposals import ProposalStore
from .tasks import TASK_ACTIONS, TASKS_REF
from .workspace import WorkspaceStore, workspace_lock
from .obsidian import memo_proposals_from_file
from .bindings import (
    DEFAULT_OBSIDIAN_BINDING_ID,
    check_resource_binding,
    list_resource_bindings,
    set_resource_binding,
)


WORKSPACE_COMMANDS = {
    "task": {"list": ("read", TASKS_REF),
             **{verb: ("execute", ref) for verb, ref in TASK_ACTIONS.items()}},
    "context": {"list": ("read", "personal.context.v1#contexts"),
                "select": ("execute", "personal.context.v1#context.select"),
                "update": ("execute", "personal.context.v1#context.update")},
    "people": {"list": ("read", "personal.memory.v1#people"),
               "update": ("execute", "personal.memory.v1#person.update")},
    "memory": {"list": ("read", "personal.memory.v1#memories"),
               "update": ("execute", "personal.memory.v1#memory.update"),
               "review": ("execute", "personal.memory.v1#memory.review")},
    "proposal": {"list": ("read", "personal.context.v1#proposals"),
                 "inspect": ("execute", "personal.context.v1#proposal.inspect"),
                 "approve": ("execute", "personal.context.v1#proposal.approve"),
                 "reject": ("execute", "personal.context.v1#proposal.reject"),
                 "mail-feedback": ("execute", "communications.mail.v1#draft.feedback.propose"),
                 "authorize-obsidian": ("execute", "knowledge.obsidian.v1#note.authorize"),
                 "apply-obsidian": ("execute", "knowledge.obsidian.v1#note.apply")},
}


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
    sub.add_parser("workspace-migrate", help="将旧工作区记录保留备份并标记为待来源复核")
    workspace_init = sub.add_parser("workspace-init")
    workspace_init.add_argument("--local-knowledge", action="store_true", help="选择本工作区为个人正文主源并创建缺失模板")
    setup = sub.add_parser("setup", help="检查或初始化 Profile Workspace")
    setup_actions = setup.add_subparsers(dest="setup_action", required=True)
    setup_status = setup_actions.add_parser("status", help="显示首次配置步骤")
    setup_status.set_defaults(setup_handler="status")
    setup_init = setup_actions.add_parser("init", help="创建缺失的 Profile 控制目录")
    setup_init.add_argument("--local-knowledge", action="store_true", help="选择本工作区为个人正文主源并创建缺失模板")
    setup_init.set_defaults(setup_handler="init")
    binding = sub.add_parser("binding", help="管理 Profile Workspace 资源绑定")
    binding_actions = binding.add_subparsers(dest="binding_action", required=True)
    binding_list = binding_actions.add_parser("list", help="列出 refs-only 绑定")
    binding_list.set_defaults(binding_handler="list")
    binding_set = binding_actions.add_parser("set", help="绑定一个本地资源目录")
    binding_set.add_argument("--id", required=True, dest="binding_id")
    binding_set.add_argument("--provider", required=True, choices=["obsidian", "markdown"])
    binding_set.add_argument("--path", required=True, help="资源目录；只保存为 file URI")
    binding_set.add_argument(
        "--capability-id",
        default="knowledge.documents.v1",
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
    browser = sub.add_parser("browser", help="管理 Profile 中的独立浏览器会话")
    browser_actions = browser.add_subparsers(dest="browser_action", required=True)
    for action in ("open", "inspect", "close"):
        command = browser_actions.add_parser(action)
        command.add_argument("--session", required=True, help="Profile 中的浏览器会话名称")
        if action == "open":
            command.add_argument("--url", required=True, help="打开经过确认的页面")
            command.add_argument("--headless", action="store_true", help="不打开可见窗口")
            command.add_argument("--shared", action="store_true", help="在用户已授权的 Chrome 中创建独立标签页")
            command.add_argument("--chrome-port", type=int, help="指定已授权的本机 Chrome 调试端口")
    tool = sub.add_parser("tool", help="读取工具配置和审核证据")
    tool_actions = tool.add_subparsers(dest="tool_action", required=True)
    capture = tool_actions.add_parser("capture-window", help="读取已选中窗口的审核图像")
    capture.add_argument("--input", required=True, help="目标对象 JSON 文件或 -")
    catalog = tool_actions.add_parser("connector", help="查看已安装连接器的操作目录")
    catalog.add_argument("--package-id", required=True)
    issue = tool_actions.add_parser("github-issue", help="核对 GitHub Issue、标签和当前账号")
    issue.add_argument("--repo", required=True)
    issue.add_argument("--number", type=int, required=True)
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
    for action in WORKSPACE_COMMANDS["proposal"]:
        command = proposal_sub.add_parser(action)
        command.add_argument("--input", required=action != "list", help="JSON file or - for stdin")
    for group in ("context", "people", "memory", "task"):
        group_parser = sub.add_parser(group)
        actions = group_parser.add_subparsers(dest="workspace_action", required=True)
        for action in WORKSPACE_COMMANDS[group]:
            command = actions.add_parser(action)
            command.add_argument("--input", required=action != "list", help="JSON file or - for stdin")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "app-contribution":
            code, response = handle_request(json.load(sys.stdin))
            sys.stdout.write(dump_json(response))
            return code
        paths = PersonaPaths.resolve()
        action = args.kind if args.command == "proposal" else getattr(args, "workspace_action", None)
        route = WORKSPACE_COMMANDS.get(args.command, {}).get(action)
        if route:
            operation, ref = route
            code, response = handle_request({"schema_version": "opl-package-app-contribution-request.v1",
                                            "operation": operation, "ref": ref,
                                            "input": _read_input(args.input) if args.input else {}})
            sys.stdout.write(dump_json(response))
            return code
        if args.command == "doctor":
            result = paths.doctor()
        elif args.command == "workspace-migrate":
            result = {"ok": True, "migration": WorkspaceStore(paths).migrate_workspace()}
        elif args.command == "workspace-init":
            with workspace_lock(paths):
                result = paths.init_workspace(local_knowledge=args.local_knowledge)
        elif args.command == "setup":
            with workspace_lock(paths):
                result = paths.setup_status() if args.setup_handler == "status" else paths.init_workspace(local_knowledge=args.local_knowledge)
            result = {"ok": True, "setup": result}
        elif args.command == "browser":
            browser = ToolRegistry(paths).browser_session(args.session)
            if args.browser_action == "close":
                browser.close()
                result = {"ok": True, "browser_session": args.session}
            else:
                observation = (browser.open(args.url, headless=args.headless, shared=args.shared,
                                            chrome_port=args.chrome_port) if args.browser_action == "open"
                               else browser.inspect())
                result = {"ok": True, **observation}
        elif args.command == "tool":
            registry = ToolRegistry(paths)
            if args.tool_action == "capture-window":
                result = {"ok": True, "capture": registry.desktop_capture(_read_input(args.input))}
            elif args.tool_action == "connector":
                result = {"ok": True, "catalog": registry.connector_catalog(args.package_id)}
            else:
                result = {"ok": True, "issue": registry.github_issue(args.repo, args.number)}
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
                with workspace_lock(paths):
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
        if args.command == "proposal":
            result = ProposalStore(paths).persist_bundle(result)
        sys.stdout.write(dump_json(result))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        sys.stderr.write(f"opl-persona: {exc}\n")
        return 2
