# OPL Persona 分发说明

状态：`active_delivery_boundary`

本文说明 Persona 代码、Codex 插件（Codex Plugin）与 OPL 托管能力包的分发边界。

## 三类物理位置

| 位置 | 保存内容 | 是否保存用户数据 |
| --- | --- | --- |
| GitHub 仓库与本地检出仓库 | 源代码、插件、能力包描述、测试、公开文档 | 否 |
| Codex 插件缓存 | Codex 安装后的插件快照 | 否 |
| `~/OPL/profiles/<profile>/` | 该用户的分身工作空间、规则、提案与模块状态 | 是 |

分身工作空间（Profile Workspace）是用户的数字分身目录。Persona 使用
`<profile>/data/persona`，Relay 使用同一分身工作空间下的
`<profile>/data/relay`。二者通过 `OPL_PROFILE_WORKSPACE` 选择同一个分身，不能各自引入
第二个数据根。

Obsidian 知识库和网站仓库继续保留在用户选定的外部位置。Persona 只保存受控资源绑定
（Resource Binding）、来源证据和提案状态，不复制知识库、网站检出目录、邮件正文、账户凭据
或审批内容。

## 当前可用分发

### Codex 插件市场

仓库根的 `.agents/plugins/marketplace.json` 当前发布 `opl-persona` 插件。Codex 可以从：

1. 本地检出目录读取这个插件市场；
2. 从 GitHub 仓库拉取一个插件市场快照。

插件市场内部的 `source: local` 是相对于插件市场根目录的路径。在 Git 插件市场场景下，这个
目录位于 Codex 已取得的快照中，因此不要求用户手工维护插件缓存。

本地检出目录和 Git 插件市场统一使用正式标识 `opl-persona`。这个标识只代表 Codex 插件市场，
不等同于未来 OPL 托管能力包的远端通道。

使用 Git 插件市场时，刷新快照和重新安装插件的命令是：

```bash
codex plugin marketplace upgrade opl-persona --json
codex plugin add opl-persona@opl-persona --json
```

这条路径只管理 Codex 插件载体。它不能证明 OPL 能力包已安装、资源绑定已配置，或者任何外部
资源已经健康可用。

### 本地开发命令行工具

`make install-local` 生成用户本地的 `opl-persona` 启动器。它指向当前检出仓库的运行时，用于
开发与调试；它不是发布器，也不是长期的能力包管理方式。

## OPL 托管通道

Persona owner 通过 `plugins/opl-persona/opl-package.json` 声明 Package identity、
capability、dependency intent、App contribution 与 content lock，并独立发布不可变
GHCR payload。安装与 publication 是两个 authority 面：

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

- 版本化源代码、双语用户入口、MIT 许可证和品牌资产；
- 可从本地或 Git 插件市场安装的 Codex 插件载体；
- 单元测试、插件校验与 GitHub 持续集成；
- 明确的分身工作空间数据边界。

托管通道验证必须分别证明：Package owner 的 immutable version 与 `latest-stable`
解析到预期公开 digest；配置的原生 carrier 能回读 exact installed bytes；Framework
projection 与 carrier readback 一致；OPL App 只通过通用 Capability Package projection
呈现 Persona；所有 lifecycle action 都保持 Profile Workspace 不变。任一单项通过都不
等于 runtime、Resource Binding、外部资源或产品 ready。
