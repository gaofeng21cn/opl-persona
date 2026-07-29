<p align="center">
  <img src="assets/branding/opl-persona-logo.png" alt="OPL Persona 标志" width="136" />
</p>

<p align="center">
  <a href="./README.md">English</a> | <a href="./README.zh-CN.md"><strong>中文</strong></a>
</p>

# OPL Persona

**为 PI 持续工作而设计、以证据为基础的数字分身。**

OPL Persona 让邮件、个人知识、专业背景和公开工作之间保持连贯，但不会把这些内容从原有
系统中夺走。它把 OPL Relay、Obsidian 知识库和实验室网站提供的证据整理为明确、可审核的
提案；在用户确认之前，不会改变任何外部系统。

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

## 分身工作空间

每个数字分身对应一个由用户拥有的 **分身工作空间（Profile Workspace）**。它保存这个人的
私有资料上下文、偏好、策略、提案状态和模块维护数据。典型结构如下：

```text
~/OPL/profiles/<profile>/
├── profile/            # 此人是谁，以及长期有效的资料引用
├── policies/           # 个人处理规则
├── context/            # 持续工作的上下文
├── templates/          # 可复用的个人模板
├── exports/            # 明确交付给用户的输出
└── data/
    ├── relay/          # 邮件证据、草稿、关系记忆和同步状态
    └── persona/        # 通用收件箱、提案、审批与回执
```

通过唯一的环境变量 `OPL_PROFILE_WORKSPACE` 选择分身工作空间。未设置时，Persona 默认使用
`~/OPL/profiles/<user>`。源代码仓库、Codex 插件缓存和 OPL 能力包安装目录只包含代码
与合同，绝不保存私人邮件、知识库正文、凭据或审批记录。

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

`setup init` 可以重复运行，只创建缺失模板，不会覆盖已有内容。请先填写
`profile/identity.md`，再把 Obsidian 知识库绑定到当前工作空间：

```bash
opl-persona --json binding set \
  --id my-knowledge --provider obsidian --path "/path/to/Obsidian"
opl-persona --json binding check --id my-knowledge
```

绑定时 Persona 不会读取知识库正文，只保存本机资源引用。邮件配置由 OPL Relay
使用同一个分身工作空间单独完成。

完整的提案合同与职责边界见
[架构指引](./docs/architecture-guidance.md)。

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
交代工作即可，插件会路由到能力包声明的动作。它始终先形成提案，不会在没有确认的
情况下修改邮件、Obsidian 知识库或网站。

若通过 Git 插件市场使用，可先刷新快照，再重新安装插件：

```bash
codex plugin marketplace upgrade opl-persona --json
codex plugin add opl-persona@opl-persona --json
```

## 分发方式

目前有两条不同的分发路径：

| 路径 | 当前状态 | 含义 |
| --- | --- | --- |
| Codex 插件 | 已可通过本地检出目录或 Git 插件市场快照安装 | 让 Codex 安装 Persona 的专业能力入口。 |
| OPL 托管能力包 | 已准备接入统一 GHCR 通道，尚待发布 | Framework 完成发布和摘要回读后，由 OPL App 通过通用能力包生命周期完成发现、安装、更新、修复和卸载。 |

GitHub 仓库是代码来源和 Codex 插件市场的输入。OPL App 通道将由 OPL Framework 的仓库
索引、不可变 GHCR 能力包载荷、清单与摘要回读共同管理，Persona 不实现自己的更新器。
预定的稳定通道地址为：

```text
ghcr.io/gaofeng21cn/one-person-lab-packages/opl-persona:latest-stable
```

GitHub Release 不属于 Persona 的分发权威。Codex Git 路径和 OPL 能力包路径共享源码出处，
但安装、更新和状态分别由各自平台负责。在 Framework 完成发布并回读远端摘要之前，上述
GHCR 地址不能视为已上线。

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

OPL Persona 采用 [MIT License](./LICENSE)。
