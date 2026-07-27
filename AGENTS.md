# OPL Persona

本仓持有跨领域 PI 上下文、证据 provenance、review-gated proposal 合同、
Codex Plugin 与 OPL Package 描述。

- 邮件、Obsidian 和 `gflab_web` 各自保留自己的数据 authority；Persona 不复制
  邮件库、私有记忆、vault 或网站 checkout。
- `OPL_PERSONA_HOME` 是私有运行态数据根，`OPL_PERSONA_WORKSPACE` 是可替换的人类
  工作空间；仓库、插件缓存和 Package 安装目录不是数据 authority。
- 所有跨系统写入必须先成为带 `source_refs` 的 `opl-persona-proposal.v1`，
  默认 `approval.external_write_allowed=false`，由对应 adapter 在用户确认后执行。
- 运行 `python3 -m pytest` 与官方 `validate_plugin.py`；私有数据、凭据和真实外部
  mutation 不进入测试或 Git。
