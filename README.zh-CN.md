<p align="center">
  <img src="assets/branding/opl-persona-logo.png" alt="OPL Persona 标志" width="136" />
</p>

<p align="center">
  <a href="./README.md">English</a> | <a href="./README.zh-CN.md"><strong>中文</strong></a>
</p>

# OPL Persona

**为 PI 持续工作而设计、以证据为基础的数字分身。**

OPL Persona 让邮件、个人知识、专业背景和公开工作之间保持连贯，但不会把这些内容从原有
系统中夺走。它把 OPL Relay、用户选定的知识来源和实验室网站提供的证据整理为明确、可审核的
提案。Obsidian 或普通 Markdown 目录都可以继续作为个人知识的正文主源。

它处理的是会跨越多轮对话持续存在的工作：基于既有往来和关系证据起草邮件，把新发表的
论文转化为知识库和网站更新，或利用 PI 已有的上下文形成一篇新的技术备忘录。

## Persona 能做什么

- 把邮件、个人知识和网站工作中的证据与上下文组织到一起，但不把原始数据复制成另一套
  数据库。
- 维护一个私人、跨领域的通用收件箱，承接需要判断、整理或转化为行动的信息。
- 为邮件分诊、Obsidian 笔记和网站更新生成带来源引用与策略上下文的可审核提案。
- 让外部写入仍由原系统负责：Relay 负责邮件事实、草稿、Apple Mail 审核、发送与回执；
  Obsidian 负责笔记；网站仓库负责发布内容与部署。

Persona 是判断与协调层，不是邮件客户端，不是第二个 Obsidian 知识库，也不是网站内容管理
系统。

工作空间提供学术邮件、技术备忘录、学术网站和科研写作四种可调用工作模式。人物与跨来源
证据记忆以及自定义工作模式都是绑定已接受来源版本的派生上下文。批准记忆与每次组装 Context
前，由 Framework 核对来源；过期、变动、缺失或撤权的来源被排除，并返回原因。管理视图默认
显示候选，也能审阅 forgotten 条目；来源无效的派生正文在修复前不再展示。邮件记忆仅通过
Relay 的公开能力包 ABI 读取，不访问其数据库。分诊、捕获和笔记提案
跨 CLI 调用持久化；查看、批准和拒绝绑定精确 digest。Obsidian 应用需要独立、基于用户授权的精确
资源授权，返回持久化的真实 readback；批准提案不授权发信或发布。

`context list/select/update`、`people list/update`、`memory list/update/review` 和
`proposal list/inspect/approve/reject/authorize-obsidian/apply-obsidian` 共用 JSON 合同
（`--input <文件或->`）。并发 CLI 写入共用跨平台锁与 data/persona 内的原子保存。Studio
视图声明挂载于现有 settings.section slot；read model 提供本地化工作模式、动作表单和
绑定 digest 的行级输入。

## 分身工作空间

每个数字分身对应一个由用户拥有的 **分身工作空间（Profile Workspace）**。它保存这个人的
来源绑定、派生上下文、策略、提案状态和模块维护数据。个人正文继续留在用户维护的位置，
本地正文是可选项。典型结构如下：

```text
~/OPL/profiles/<profile>/
├── profile/            # 资料引用，或用户明确选择的本地正文
├── policies/           # 可选本地规则与模板，登记接受后使用
├── context/            # 可选本地项目正文
├── templates/          # 可复用的个人模板
├── exports/            # 明确交付给用户的输出
└── data/
    ├── relay/          # 邮件证据、草稿、关系记忆和同步状态
    └── persona/        # 角色引用、派生上下文、收件箱、提案与回执
```

通过唯一的环境变量 `OPL_PROFILE_WORKSPACE` 选择分身工作空间。未设置时，Persona 默认使用
`~/OPL/profiles/<user>`。源代码仓库、Codex 插件缓存和 OPL 能力包安装目录只包含代码
与合同，绝不保存私人邮件、知识库正文、凭据或审批记录。

邮件规则、身份、团队和项目资料通过 `data/persona/knowledge-inputs.json` 中的知识 ID
选择。Framework 按 `shared/memory/knowledge-bindings.json` 的 `registry_ref`
解析已接受来源；登记簿可位于 Profile 的 `data/knowledge-sources.json`，本地规则
模板不会自动成为有效证据。已有正文可以原地登记，无须迁移或另存一份。具体角色映射与
读取约定见[邮件政策边界](docs/mail-policy.md)。

## 本地开始

克隆仓库，安装开发用命令行工具，并初始化一个分身工作空间：

```bash
git clone git@github.com:gaofeng21cn/opl-persona.git
cd opl-persona
make install-local

export OPL_PROFILE_WORKSPACE="$HOME/OPL/profiles/<profile>"
opl-persona --json setup init
opl-persona --json setup status
```

`setup init` 可以重复运行，只创建缺失的控制目录与处理政策，不会覆盖已有内容。
`setup status` 只说明运行配置是否就绪，不代表个人事实完整；初始化不要求外部知识库，
也不要求再填一份身份正文。

如果选择当前工作区维护个人正文，可显式创建本地模板：

```bash
opl-persona --json setup init --local-knowledge
```

已有笔记目录时，保存带范围的引用；Obsidian 知识库使用 `obsidian`，普通目录使用 `markdown`：

```bash
opl-persona --json binding set \
  --id my-knowledge --provider obsidian --path "/path/to/Obsidian"
opl-persona --json binding check --id my-knowledge
```

绑定时 Persona 不会读取知识库正文，只保存本机资源引用。邮件配置由 OPL Relay
使用同一个分身工作空间单独完成。

这里的 Resource Binding 服务于笔记适配器。已接受知识的身份、版本与读取授权由 Framework
统一管理，Persona 的笔记绑定不能替代通用知识授权。`people update`、`memory update` 和
`context update` 必填 `source_versions`，以对象记录各个已接受 `knowledge_id` 对应的
精确 `sha256:...` 版本。新的独立偏好先在选定正文主源中接受，再由 Persona 引用。
已有 v1 工作区可运行 `opl-persona --json workspace-migrate`，保留原文件备份并进入来源复核；
旧批准不会使未经核实的来源继续生效。家族级规范以
[OPL 知识来源与记忆政策](https://github.com/gaofeng21cn/one-person-lab/blob/main/docs/policies/knowledge-source-and-memory-policy.md)为唯一归口。

完整的提案合同与职责边界见
[实现架构](./docs/architecture.md)；跨仓目标设计见[架构指引](./docs/architecture-guidance.md)。

## 在 Codex 中使用

本仓包含一个 Codex 插件（Codex Plugin）。Codex 既可以从本地检出目录添加插件市场，也可以
从 Git 仓库读取。两种方式都使用正式插件市场标识 `opl-persona`。

从本地检出目录安装：

```bash
codex plugin marketplace add "$(pwd -P)" --json
codex plugin list --marketplace opl-persona --available --json
codex plugin add opl-persona@opl-persona --json
```

从 GitHub 安装：

```bash
codex plugin marketplace add https://github.com/gaofeng21cn/opl-persona.git --ref main --json
codex plugin list --marketplace opl-persona --available --json
codex plugin add opl-persona@opl-persona --json
```

安装后请新开一个 Codex 任务，使其加载已安装的插件快照。日常使用时，直接用自然语言
交代工作即可，插件会路由到能力包声明的动作。它先形成提案；已有授权覆盖精确目标和改动时
沿用该授权，缺失或扩大授权范围时再交用户审阅。

若通过 Git 插件市场使用，可先刷新快照，再重新安装插件：

```bash
codex plugin marketplace upgrade opl-persona --json
codex plugin add opl-persona@opl-persona --json
```

## 分发方式

目前有两条不同的分发路径：

| 路径 | 当前状态 | 含义 |
| --- | --- | --- |
| Codex 插件 | Codex 原生 carrier；当前状态以 `codex plugin list --json` 为准 | 安装并暴露 Persona Skill 载体，但 checkout 或插件缓存不成为数据 authority。 |
| OPL Package publication | Persona owner descriptor 与不可变 GHCR payload | 独立发布 Package identity 与 bytes；`latest-stable` 是 owner moving channel，不是 installed-state proof。 |

Persona 仓持有 descriptor、capability 声明、source provenance 与 Package publication。
OPL Base 可以下载、校验并 handoff 所选 OCI bytes；配置的原生 carrier 持有物理安装、
更新、修复、卸载及其 readback。OPL Framework 只发现 installed descriptor、委托
carrier action，并为 OPL App 聚合 presence 与 callability；Persona 不实现第二套更新器。
稳定 owner channel 为：

```text
ghcr.io/gaofeng21cn/one-person-lab-packages/opl-persona:latest-stable
```

GitHub Release 不属于 Persona 的分发权威。Codex Git 路径和 OPL 能力包路径共享源码出处，
但安装、更新和状态分别由各自 carrier 负责。publication 必须从公开不可变 GHCR digest
回读，installed/current 状态必须从配置的原生 carrier 单独回读；二者都不能从 README、
source tag 或 Framework projection 单独推断。

详情见[分发说明](./docs/distribution.md)。

## 开发检查

```bash
python3 -m pytest -q
actionlint .github/workflows/ci.yml
```

发布前，维护者还应运行 Codex 官方插件创建工具（Plugin Creator）提供的
`validate_plugin.py`；其安装路径不会硬编码到本仓。GitHub Actions 还会在测试之外运行可移植的
结构检查。

## 许可证

OPL Persona 采用 [Apache License 2.0](./LICENSE)。
