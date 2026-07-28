# OPL App 能力管理与统一审核规划

状态：`discovery_projection_completed`；语义化 UI 与统一审核仍为 `deferred_execution`

本文件记录已经确定的产品边界和实施顺序，供后续 Framework、OPL App、Shell
和 Package owner 协调时使用。它不授权实现 UI、安装/更新/卸载、邮件发送、
网站发布或任何真实外部写入。

## 决策

OPL App 可以管理 OPL Relay 与 OPL Persona，但管理对象应是角色无关的
**Package / Capability**，而不是把两者伪装成 `standard_agent`，也不是恢复一套
自研 Package Manager。

推荐的用户可见名称是“能力与集成”（英文可用 *Capabilities & Integrations*）。
现有“智能体管理”入口可在实施时逐步迁移或保留为兼容路由；它不能继续成为只有
`kind=agent` 才能进入的产品边界。

```text
Package identity       capability、入口、依赖、App contribution 声明
Carrier                Codex Plugin Manager、Git 或其他 owner-declared carrier
OPL Framework          discovery、presence、route readiness、状态与 action 投影
OPL App / Shell        显示投影、收集用户意图、调用投影出的 action
Domain owner           邮件、提案、知识库、网站等领域语义和最终 authority
```

Relay 和 Persona 是第一批真实 Package，但它们不是 App 中的特殊案例。任意合规的
未知 Package 都必须能以同一条路径出现、维护和局部降级。

## 当前事实与剩余缺口

截至 2026-07-28，`codex plugin list --json` 已确认以下两个 carrier 都已本地安装且
启用：

| Package | Codex Plugin | 原生状态 |
| --- | --- | --- |
| `opl-relay` | `opl-relay@opl-relay` | installed, enabled |
| `opl-persona` | `opl-persona@opl-persona-local` | installed, enabled |

原先记录的 W3 缺口已经关闭：Framework 的动态 Package directory、status/action
projection 与 role-neutral contribution read/execute 路径现已能发现并调用 Relay 和
Persona。该结果证明的是“Package 已被宿主发现且其声明的贡献可路由”，不是以下任何一种
更强结论：

- 对应邮箱、Obsidian vault 或网站 Resource Binding 已配置并健康；
- App/Shell 已按 `list_detail`、`approval_diff` 等 view kind 完成语义化渲染；
- carrier 已可靠投影安装、更新、修复、卸载等全部 mutation；
- 任一 Persona proposal、邮件草稿、vault 写入或网站变更已得到批准并进入最终 authority。

因此第一个真实断点已从 W3 discovery 转移到 Resource Binding 健康回读、标准 view
renderer、统一审核和 owner adapter 的批准后闭环。后续不能继续以“尚未动态发现
Relay/Persona”为理由增加静态卡片或 Package id 特判。

## 能力管理面

“能力与集成”页面只消费 Framework 的动态 projection。每个 Package 行应显示：

- identity、名称、Package role 与声明的 capabilities；
- presence、installed/callable/readiness、局部诊断和 configured carrier route；
- 原生 carrier 已知的 installed/enabled/version/update-availability 信息；
- 该 Package 的 `app_contributions` 是否可用，以及用户的 Home/导航显隐偏好；
- Framework 实际投影出的 action，而非 App 根据 Package id 或 manifest 猜出的按钮。

动作边界如下：

| 用户意图 | 唯一执行者 | App 的职责 |
| --- | --- | --- |
| 安装、更新、修复、卸载 | configured carrier | 显示 action、要求必要确认、调用 `opl app action execute`、回读结果 |
| 查看状态、诊断 | Framework / carrier | 刷新并显示投影 |
| Home 或导航显隐、排序 | App preference owner | 保存用户偏好；不改变 Package 的 installed truth |
| 启用/停用 | 仅在 carrier 明确投影此 action 时 | 原样呈现；不得虚构通用 enable/disable |
| 发送邮件、发布网站、写入 Obsidian | Relay、网站或知识库 adapter | 不属于能力管理面 |

对于当前 Codex Plugin carrier，Framework 可以把原生 `codex plugin` 操作包装为其
已配置的单 Package action，并以 fresh `list --json` 回读为准。App 不需要、也不应
知道它在当前 carrier 上是 `plugin add`、`plugin remove` 或其他原生命令。

“显隐”不等于“卸载”，也不等于“禁用插件”。用户卸载后，普通启动、静默维护和 App
更新都不得自动装回；只有 Official Profile 的首次安装或用户明确 Restore 才能恢复。

## 明确不建设的旧管理器

为配合 Package Manager 退役，以下能力不得重新引入：

- 中央版本或 ABI resolver；
- installed lock、payload、materialization、LKG、receipt、rollback transaction；
- 固定 Package、Agent、Skill 清单；
- App/Shell 对 `opl-relay`、`opl-persona` 或任一 Package id 的分支；
- 第二套安装器、更新器、状态数据库，或由 App 保存 carrier 物理状态；
- 因 Package 管理而复制邮件、关系记忆、Obsidian vault、Persona proposal 或网站数据。

一个 Package 的 carrier 操作失败，只影响该 Package 和其直接依赖。其他 Package、
其他已安装能力和既有领域数据必须继续可用。

## 暂缓的标准视图与统一审核

以下产品切片方向正确，但**本轮暂缓执行**：

1. 在 OPL App 正式 mount 标准 `list_detail`、`timeline`、`approval_diff`、
   `task_board`、`artifact_view` 与 `activity_log` renderer。
2. 提供一个角色无关的“待审核”入口，把各 Package 的 `approval_diff` 贡献聚合为可扫描
   的队列。
3. 让 Persona proposal 审核和 Relay Apple Mail 草稿审核在同一个视图语言中呈现，同时
   保持它们的领域动作、状态和 authority 分离。

统一的是审核体验，不是状态库或执行权。每个审核项至少应具有：

- `package_id`、`proposal_or_draft_id`、read-model `data_ref` 与 action `action_ref`；
- evidence/provenance、目标系统、变更 diff 或草稿 fingerprint；
- required confirmation、允许的下一步、当前 owner；
- 执行后 authority readback 与 receipt reference。

推荐的邮件路径仍分两段：

```text
Persona proposal review
  -> Relay creates a draft
  -> user reviews or edits in Apple Mail
  -> Relay inspects and fingerprints the actual draft
  -> explicit send confirmation
  -> Relay send readback
```

Persona 的“批准提案”只允许进入该 proposal 的下一条 owner route；它不代表已经写入
网站、知识库或邮件系统。Relay 的“发送”只能对回读确认的 Apple Mail 草稿执行。App
只渲染结构化数据、调用 opaque action、显示结果，绝不成为第二邮件引擎或直接外部写入者。

## 实施状态与顺序

本规划不改变正在执行的 legacy Package Manager 退役任务。已完成的 W3 producer 路径
和仍待实施的 W4/UI 路径必须分开记录：

```text
W3 Framework                                      COMPLETED
  fresh carrier discovery + status/actions projection
       |
       v
Package owners
  canonical Relay/Persona descriptors and contributions  COMPLETED
       |
       v
Resource Binding + owner adapters                 ACTIVE SEPARATE LANES
  private binding config + health + approved apply/readback
       |
       v
W4 App / Shell                                    PARTIAL / DEFERRED
  role-neutral inventory + semantic renderers + local unavailable state
       |
       v
Unified review slice                              DEFERRED
  standard renderers + unified approvals + Relay/Persona data/action bridges
```

实施时每一层各自持有以下职责：

| Owner | 必须交付 | 不得交付 |
| --- | --- | --- |
| Framework | fresh directory、presence/callability、carrier action refs、route readiness | 新的 resolver 或 durable lifecycle manager |
| Relay / Persona | descriptor、能力与 contribution、领域 read model/action contract | App UI 或 App-side carrier state |
| OPL App | 角色无关的管理与审核产品合同、偏好、验收 | 领域状态、版本选择、carrier 语义 |
| Shell | 基于 contract 的通用渲染、确认、刷新和局部错误态 | Package id 分支、manifest/lock/receipt 解析 |

后续若 fresh carrier readback 再次无法发现一个已安装 Package，应把它作为 currentness
回归修复，仍不得用静态 Relay/Persona 卡片或手工维护的 catalog 绕过。正常情况下，
实施重点已经是消费现有 projection，而不是再造 discovery。

## 已完成门禁与未来验收条件

下列第 1 项已完成；其余结果仍是独立门禁，不能用文档、fixture、单元测试或 Package
installed 状态替代：

1. **已完成**：fresh App state 能为已安装的 Relay 与 Persona 返回动态
   directory/status/action projection，contribution read/execute 可到达 owner route。
2. 一个未知的合规测试 Package 无需改动 App/Shell 源码即可进入同一管理页面；invalid
   Package 仅自身不可用。
3. 安装、更新、修复、卸载均通过 projected action 到达 configured carrier；普通
   invocation 不触发更新，单包故障不阻断其他 Package。
4. Home/导航显隐与排序作为 App preference 可回读；卸载选择跨重启和普通维护仍被尊重。
5. Relay 与 Persona 的 contribution 在没有 package-id special case 的情况下通过
   标准 view renderer 显示。
6. 每一项统一审核都保留其 evidence、确认、owner action 和最终 authority readback；
   App 不能绕过 Relay 直接发送，也不能绕过网站/知识库 adapter 直接写入。

## 当前行动

W3 discovery、status/action projection 与 Relay/Persona contribution 路由已经完成，
不再是当前前置。现在允许按独立 write set 推进 Resource Binding、Persona Inbox、
Obsidian approved-apply、网站 owner route 和 Relay 草稿 handoff。

OPL App/Shell 的标准 view mount、统一审核队列、通用 Package mutation 控件仍保持
`deferred_execution`。这些 UI 只有在相应 read model、opaque action、确认要求与最终
authority readback 都可由 owner route 提供后才实施，不能由 App 自行补造领域状态。
