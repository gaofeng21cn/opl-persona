# OPL Persona

本仓持有跨领域 PI 上下文、证据 provenance、review-gated proposal 合同、
Codex Plugin 与 OPL Package 描述。

- 邮件、Obsidian 和 `gflab_web` 各自保留自己的数据 authority；Persona 不复制
  邮件库、私有记忆、vault 或网站 checkout。
- `OPL_PROFILE_WORKSPACE` 是用户拥有的唯一 Profile Workspace；未注入时使用
  `~/OPL/profiles/<user>`。Persona 的机器维护状态只位于其 `data/persona`
  子目录；仓库、插件缓存和 Package 安装目录不是数据 authority。
- Obsidian vault 只能由 Profile Workspace 的 Resource Binding 解析后传入；不得在
  Persona 中硬编码 vault 路径或通过环境变量旁路 Binding。
- 所有跨系统写入必须先成为带 `source_refs` 的 `opl-persona-proposal.v1`，
  默认 `approval.external_write_allowed=false`，由对应 adapter 在用户确认后执行。
- 运行 `python3 -m pytest` 与官方 `validate_plugin.py`；私有数据、凭据和真实外部
  mutation 不进入测试或 Git。

## 文档生命周期

- 双语 README 负责公开安装与首次使用；`docs/architecture.md` 负责当前实现，
  `architecture-guidance.md` 负责跨域目标边界，`app-integration.md` 负责 App 消费约束，
  `distribution.md` 负责分发，`mail-policy.md` 负责邮件解释规则。
- 组合模型、个人资料与表格、对外专业工作各自的目标文档只定义其独立设计问题；
  未实现候选不当作 callable schema、CLI 或状态机。当前接口仅从 descriptor/source 维护。
- 改动正文同时更新双语摘要、入口与全部引用；被实现替代的设计细节移入实现 owner 后删除，
  不保留永久兼容文档、历史状态表、逐次测试清单或第二份 App/Framework 计划。
- 历史默认由 Git 保存；只有仍影响当前决定的理由、安全约束或有效目标才保留，明确其身份。
  新增文档须有现有主题不能承担的独立责任。链接、资源、结构检查可以自动化，语义不可用
  关键词、标题或文本快照裁决。
