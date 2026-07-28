# OPL Persona 分发说明

状态：`active_delivery_boundary`

本文只说明 Persona 代码、Codex 插件（Codex Plugin）与未来 OPL 托管能力包
（OPL managed Package）的分发边界，不声明任何尚未完成的 OPL App 安装或更新能力。

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

## 尚未发布的 OPL 托管通道

OPL App 要能自动发现、安装、更新、修复与卸载 Persona，必须由 OPL Framework 的通用能力包
生命周期实现。目标发布链路为：

```text
Persona 发布候选
  -> OPL Framework 仓库索引
  -> 不可变能力包载荷 + 清单地址 + 摘要
  -> Framework 物化与生命周期动作投影
  -> OPL App 通用能力包管理界面
```

该通道的关键事实由 OPL Framework 持有：

- `package_repository_index.v1` 负责候选版本与兼容性选择；
- 能力包载荷清单、不可变摘要和发布状态绑定可安装字节；
- Framework 负责物化、安装、更新、修复与卸载；
- OPL App 只呈现通用状态并调用 Framework 投影的动作，不解析 Persona 的私有安装细节。

因此 Persona 不应自行增加更新器、第二份锁文件、伪远端清单或 App 特判。GitHub Release、
容器镜像或其他存储介质可以成为该通道未来的载荷承载方式，但在 Framework 的登记、摘要校验和
已安装状态回读完成前，它们都不能被称为 OPL 托管发布。

## 发布前检查清单

本仓负责以下准备：

- 版本化源代码、双语用户入口、MIT 许可证和品牌资产；
- 可从本地或 Git 插件市场安装的 Codex 插件载体；
- 单元测试、插件校验与 GitHub 持续集成；
- 明确的分身工作空间数据边界。

跨仓发布前仍需由相应负责人完成：

- 在 Framework 仓库索引中登记 Persona；
- 生成并发布不可变载荷、清单和摘要；
- 证明 Framework 的安装、更新、修复和卸载动作可用；
- 证明 OPL App 的通用管理视图通过动态能力包投影显示 Persona；
- 对已安装字节、版本、动作与外部资源健康状态完成独立回读。

完成这些条件之前，Persona 的正确表述是：可作为 Codex 插件使用，正在为 OPL 托管能力包分发
做准备。
