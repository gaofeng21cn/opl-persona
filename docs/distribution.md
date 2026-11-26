# OPL Persona 分发说明

Owner: `opl-persona`

Purpose: `persona_distribution_authority`

State: `active_current`

Machine boundary: 本文定义 Persona source distribution 与 owner boundary，不是
publication、installed 或 runtime readback。Descriptor/source provenance、公开不可变
GHCR payload、原生 carrier installed bytes、Framework projection 与 OPL App consumption
是独立 authority；本文件不能证明 GHCR digest、installed/current state、Resource Binding、
外部资源可用或 product ready。

本文说明 Persona 代码、Codex 插件（Codex Plugin）与 OPL 托管能力包的分发边界。

## 三类物理位置

| 位置 | 保存内容 | 是否保存用户数据 |
| --- | --- | --- |
| GitHub 仓库与本地检出仓库 | 源代码、插件、能力包描述、测试、公开文档 | 否 |
| Codex 插件缓存 | Codex 安装后的插件快照 | 否 |
| `~/OPL/profiles/<profile>/` | 该用户的分身工作空间、规则、提案与模块状态 | 是 |

分身工作空间（Profile Workspace）与 `data/persona/` / `data/relay/` 的目录与数据隔离边界见[实现架构](architecture.md#runtime-data)。Obsidian、普通知识目录和网站仓库继续保留在用户选定的位置；Persona 仅保存受控 Resource Binding、带来源版本的派生上下文和自身提案状态，不复制原始正文或外部凭据。

## 当前可用分发

### Codex 插件同步

OPL Pack 在安装或开发链接（`opl pack link .`）时通过 `carriers/codex-sync` 从根目录唯一 `opl-package.json`（`opl.package.v2`）自动生成 Codex marketplace 投影，仓内不再维护 `.agents/plugins/marketplace.json` 或 `plugins/opl-persona/` 镜像目录。

### 本地启动器安装

`make install-local` 默认（`INSTALL_MODE=codex`）向 `<prefix>/bin/opl-persona` 安装指向 `$OPL_STATE_DIR/packages/opl-persona/<version>/bin/opl-persona` 的启动器：运行前校验 `opl-package.json`（`opl.package.v2`）身份与最高语义版本号。如需独立部署，可显式设置 `INSTALL_MODE=standalone` 将 `opl-package.json`、`bin/`、`runtime/`、`skills/` 与 `assets/` 复制到 `<prefix>/share/opl-persona`。两种模式均不发布 OCI release；正式 Package 更新统一通过 Framework OCI 生命周期完成。

## OPL 托管通道

Persona owner 通过根目录 `opl-package.json` 声明 `identity`、`dependencies`、`permissions`、`provides`、`ui.declarative` 与 `distribution`；确定性内容锁 `opl-release.lock.json` 由 `opl pack build` 生成。
`codex_surface.configured_codex_plugin_carrier` 里声明 Codex 插件市场来源与唯一
publication 通道，再独立发布不可变 GHCR payload。安装与 publication 是两个 authority 面：
Skill 同步策略只允许 Codex 作用域；不会隐式复制到工作空间或单项任务目录。

```text
Persona owner descriptor + immutable GHCR publication
  -> OPL Base download / verify / bytes handoff
  -> configured native carrier install / update / repair / remove
  -> native installed readback
  -> Framework discovery / delegation / aggregation
  -> OPL App generic Package projection
```

稳定通道地址为：

```text
ghcr.io/gaofeng21cn/one-person-lab-packages/opl-persona:latest-stable
```

该通道的 owner 边界固定为：

- Persona owner 持有 descriptor、source provenance、immutable payload 与 publication；
- OPL Base 只下载、校验并 handoff OCI bytes，不保存第二份 resolver、installed lock 或 LKG；
- 配置的 Codex Plugin Manager 等原生 carrier 持有物理 lifecycle 与 installed readback；
- Framework 只发现 installed descriptor、委托 carrier action，并聚合
  presence/callability；OPL App 呈现该通用 projection，不解析 Persona 私有安装细节。

因此 Persona 不应自行增加更新器、第二份锁文件、伪远端清单或 App 特判。该通道由
GHCR OCI 载荷承载；GitHub Release 不参与安装或更新。是否可安装、可更新或已是当前版本，
必须分别由公开不可变 GHCR digest 与配置的原生 carrier fresh readback 证明；Framework
projection 只能聚合这些结果，不能从本仓文档、源码 tag 或 descriptor 存在推断。

## 源仓检查清单

本仓负责以下准备：

- 版本化源代码、双语用户入口、Apache License 2.0 和品牌资产；
- 可从本地或 Git 插件市场安装的 Codex 插件载体；
- 单元测试、插件校验与 GitHub 持续集成；
- 明确的分身工作空间数据边界。

Package projection 与原生 carrier 的独立核验边界见本仓 `AGENTS.md` 与测试套件；任一单项通过均不等于 Resource Binding、外部资源或产品 ready。
