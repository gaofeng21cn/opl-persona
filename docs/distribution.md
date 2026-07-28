# OPL Persona 分发说明

状态：`active_delivery_boundary`

本文只说明 Persona 代码、Codex Plugin 与未来 OPL Package 的分发边界，不声明任何尚未
完成的 OPL App 安装或更新能力。

## 三类物理位置

| 位置 | 保存内容 | 是否保存用户数据 |
| --- | --- | --- |
| GitHub 仓库与本地检出仓库 | 源代码、Plugin、Package 描述、测试、公开文档 | 否 |
| Codex Plugin 缓存 | Codex 安装后的 Plugin 快照 | 否 |
| `~/OPL/profiles/<profile>/` | 该用户的 Profile Workspace、规则、提案与模块状态 | 是 |

Profile Workspace 是用户的数字分身目录。Persona 使用
`<profile>/data/persona`，Relay 使用同一 Workspace 下的
`<profile>/data/relay`。二者通过 `OPL_PROFILE_WORKSPACE` 选择同一个 Profile，
不能各自引入第二个数据根。

Obsidian vault 和网站仓库继续保留在用户选定的外部位置。Persona 只保存受控 Binding、
provenance 和 proposal state，不复制 vault、网站检出目录、邮件正文、账户凭据或审批内容。

## 当前可用分发

### Codex Plugin Marketplace

仓库根的 `.agents/plugins/marketplace.json` 当前发布 `opl-persona` Plugin。Codex 可以从：

1. 本地检出目录读取这个 Marketplace；
2. 从 GitHub Git 仓库拉取一个 Marketplace 快照。

Marketplace 内部的 `source: local` 是相对于 Marketplace 根目录的路径。在 Git Marketplace
场景下，这个目录位于 Codex 已取得的快照中，因此不是要求用户手工维护 Plugin 缓存。

当前 Marketplace 名称为 `opl-persona-local`。它是当前描述符的标识，不表示 Git Marketplace
不能使用，也不等同于未来 OPL Package 的远端通道。

使用 Git Marketplace 时，刷新快照和重新安装 carrier 的命令是：

```bash
codex plugin marketplace upgrade opl-persona-local --json
codex plugin add opl-persona@opl-persona-local --json
```

这条路径只管理 Codex Plugin carrier。它不能证明 OPL Package 已安装、Resource Binding 已配置，
或者任何外部资源已经健康可用。

### 本地开发 CLI

`make install-local` 生成用户本地的 `opl-persona` 启动器。它指向当前检出仓库的运行时，用于
开发与调试；它不是发布器，也不是长期的 Package 管理方式。

## 尚未发布的 OPL 托管通道

OPL App 要能自动发现、安装、更新、修复与卸载 Persona，必须由 OPL Framework 的通用 Package
生命周期实现。目标发布链路为：

```text
Persona release candidate
  -> OPL Framework repository index
  -> immutable Package payload + manifest URL + digest
  -> Framework materialization and lifecycle action projection
  -> OPL App generic Package management UI
```

该通道的关键事实由 OPL Framework 持有：

- `package_repository_index.v1` 负责候选版本与兼容性选择；
- Package payload manifest、不可变 digest 和发布状态绑定可安装字节；
- Framework 负责 materialization、install、update、repair 与 uninstall；
- OPL App 只呈现通用状态并调用 Framework 投影的 action，不解析 Persona 的私有安装细节。

因此 Persona 不应自行增加更新器、第二份锁文件、伪远端 manifest 或 App 特判。GitHub Release、
容器镜像或其他存储介质可以成为该通道未来的 payload 承载方式，但在 Framework 的登记、digest
校验和 installed readback 完成前，它们都不能被称为 OPL 托管发布。

## 发布前检查清单

本仓负责以下准备：

- 版本化源代码、双语用户入口、MIT 许可证和品牌资产；
- 可从本地或 Git Marketplace 安装的 Codex Plugin carrier；
- 单元测试、Plugin 校验与 GitHub CI；
- 明确的 Profile Workspace 数据边界。

跨仓发布前仍需由相应 owner 完成：

- 在 Framework repository index 中登记 Persona；
- 生成并发布不可变 payload、manifest 和 digest；
- 证明 Framework 的 install/update/repair/uninstall action 可用；
- 证明 OPL App 的通用管理视图通过动态 Package projection 显示 Persona；
- 对已安装字节、版本、动作与外部资源健康状态完成独立 readback。

完成这些条件之前，Persona 的正确表述是：可作为 Codex Plugin 使用，正在为 OPL 托管 Package
分发做准备。
