# OPL Persona 可组合能力与集成模型

状态：`active_design_authority`，v1

本文件定义 OPL Persona 如何把知识库、邮件、网站、表格和外部专业门户组合成
可选择、可替换、可发现的能力。它补充
[Architecture Guidance](architecture-guidance.md)，但不增加新的面向用户产品层，也不承诺
所有下述 adapter 已经实现。

## 结论

网站、邮箱、知识库等不能写死为 Persona 内部固定子系统。它们应通过同一种组合模型接入：

```text
OPL Package
  -> Capability Contract
  -> Provider Adapter
  -> User Resource Binding
  -> Persona Recipe / Profile
```

这五个概念解决不同问题，不能合并成一个“万能插件”：

| 概念 | 回答的问题 | 示例 |
| --- | --- | --- |
| OPL Package | 代码和元数据如何发现、安装、更新、停用 | `opl-relay`、`opl-persona` |
| Capability Contract | 一个能力对 Persona 保证什么语义 | `communications.mail.v1`、`publishing.site.v1` |
| Provider Adapter | 由什么实现上述语义 | Relay、Obsidian adapter、`gflab_web` adapter |
| Resource Binding | 当前用户授权操作哪个真实资源 | SYSU 邮箱、个人 Obsidian vault、实验室网站 |
| Persona Recipe / Profile | 某类角色和任务组合哪些 Binding | PI、学术编辑、审稿专家 |

OPL Package 是分发和生命周期边界，不等于领域能力本身。一个 Package 可以提供多个
Capability；同一个 Capability 也可以存在多个 Provider。Binding 是用户私有配置实例，
不能打进 Package 或 Git。Recipe 只引用 Capability 与 Binding，不复制外部系统数据。

## 公共产品层保持不变

可组合能力是 OPL Packages 的内部合同，不是新的第四个公共产品层：

```text
Package owner  identity、Capability、dependency intent、App contribution 与 publication
Native carrier install、update、repair、remove 与物理 installed readback
OPL Framework  installed descriptor discovery、carrier action 委托与状态聚合
OPL App        对话、可视化、审批、组合与状态呈现
```

Persona 是跨域判断、provenance 和 proposal 编排者；它不成为邮箱、知识库、网站、表格
或第三方门户的第二份数据库。OPL App 也不拥有这些领域语义，只消费结构化贡献并呈现
安装、配置、健康状态、任务、审批差异和回读结果。

## 首批 Capability Contracts

首批合同保持小而稳定：

| Capability ID | 最小语义 | 典型 Provider |
| --- | --- | --- |
| `knowledge.documents.v1` | 搜索、读取、提出新增或更新知识文档 | Obsidian adapter |
| `communications.mail.v1` | 检索邮件证据、生成草稿、经批准执行并回读 | OPL Relay |
| `publishing.site.v1` | 读取公开内容状态、提出内容变更、经批准发布并回读 | `gflab_web` adapter |
| `personal.profile.v1` | 按用途解析用户维护的个人资料字段及 provenance | Obsidian profile adapter |
| `forms.fill.v1` | 检查模板、映射字段、生成草稿、经批准写入并回读 | DOCX/PDF/XLSX/Portal adapter |
| `external.portal.v1` | 读取专业任务、准备受控动作、经批准提交并回读 | Browser/API portal adapter |
| `personal.inbox.v1` | 接收跨域 capture，形成待整理、待核验或待行动条目 | Persona inbox provider |

Capability ID 是稳定语义，不绑定文件路径、网站框架、邮箱客户端或 UI 页面。若
`gflab_web` 将来更换生成器或托管平台，只要 adapter 继续满足
`publishing.site.v1`，Persona Recipe 无需变化。

### 现有 ID 的兼容与迁移

通用 Capability ID 是长期合同；现有 provider-specific ID 和 action ref 是兼容入口，
不能被 App 或 Persona 静默改写：

| 长期 Capability ID | 当前兼容 ID / ref | 迁移含义 |
| --- | --- | --- |
| `knowledge.documents.v1` | `knowledge.obsidian.v1`、`knowledge.obsidian.v1#note.propose` | Obsidian 是首个 Provider；Recipe 与 Binding 使用通用 ID，resolver 返回 Provider 实际 action ref |
| `publishing.site.v1` | `website.publication.v1` 与现有 `gflab_web` proposal type | `gflab_web` 是首个 Provider；网站 proposal schema 不因 Capability 泛化而强制改名 |
| `communications.mail.v1` | 同名现有 Relay refs | 已是通用 ID，无需别名 |
| `personal.inbox.v1` | 同名现有 Persona ref | 已是通用 ID，无需别名 |

Capability ID、provider action ref 和 proposal artifact schema 是三类 identity：

- Recipe 与 Resource Binding 只依赖通用 Capability ID；
- Provider 声明自己实现的通用 Capability，并返回其可调用的 opaque action ref；
- proposal schema 可以保留更具体的目标语义，例如 `knowledge.obsidian.note.v1`，不能被
  当作另一个 Capability ID。

迁移按以下顺序进行：

1. Provider 先同时声明通用 Capability 与 legacy alias，并保持旧 action ref 可调用；
2. 新 Recipe、Binding 与 App projection 只写通用 ID，但执行时使用 Provider 返回的 ref；
3. consumer-zero 与 installed/effective readback 均证明旧 ID 无调用者后，才移除 alias；
4. 已发布 ID 永不改作其他语义。迁移期间不得让 App 维护第二份硬编码 alias 表。

第一版统一操作词汇只有：

```text
inspect / health
read / search
propose
apply_approved
readback
```

Provider 可以只实现其中一部分，但必须显式声明支持项，不能用“已安装”推断“可写”或
“已发布”。所有外部 mutation 继续服从 `opl-persona-proposal.v1`；`apply_approved`
只能执行用户批准的精确 proposal，随后必须 `readback`。

## Provider Adapter 与 Resource Binding

Provider Adapter 隔离具体工具和工作流。例如网站 adapter 可以使用 Git、Hugo、Netlify、
站点 API 或浏览器，但 Persona 只依赖 `publishing.site.v1`。浏览器、Office 工具和邮件
客户端是执行 surface，不是新的 domain authority。

Resource Binding 把 Provider 连接到用户的真实资源。最小私有配置合同为：

```yaml
schema_version: opl-persona-resource-binding.v1
binding_id: my-knowledge
capability_id: knowledge.documents.v1
provider_id: obsidian
resource_ref: vault-ref://personal
allowed_operations: [read, search, propose, apply_approved, readback]
allowed_scopes: [notes/technical-memos]
approval_policy_ref: persona-policy://knowledge-write-v1
credential_ref: null
enabled: true
```

`capability_id` 必须是通用 ID；`resource_ref` 与可选 `credential_ref` 必须是不含 secret
和正文的 opaque reference。Binding 配置位于 `<profile>/data/persona` 的私有配置表面，不进入
Git、Package、Plugin cache、App state 或公开日志。

`health` 与 `currentness` 不是 Binding 文件中的持久事实。每次检查由 Provider fresh
回读并产生独立结果：

```yaml
schema_version: opl-persona-binding-health.v1
binding_id: my-knowledge
checked_at: 2026-07-28T00:00:00Z
status: healthy
supported_operations: [read, search, propose, apply_approved, readback]
authority_readback_ref: vault-readback://...
issues: []
```

允许的状态是 `healthy`、`degraded`、`unavailable`、`unauthorized` 与 `unconfigured`。
未执行 fresh health readback 时只能报告 `unknown`，不能从 Package installed/enabled
状态推断 Binding 可用。

Binding 只保存资源引用、scope 和策略。邮箱内容、Obsidian 内容、个人资料值、网站源码、
Cookie、token 和密码仍由各自 authority 或用户选择的安全位置管理。当前个人资料设计中，
包括身份、证件、金融、税务和收款字段在内的用户资料值统一由用户维护的 Obsidian
资料库管理；Persona Binding 只保存可审计引用，不建立第二套值库。

典型 Binding：

```text
my-knowledge       -> knowledge.documents.v1 / Obsidian / personal vault
my-profile         -> personal.profile.v1 / Obsidian / profile notes
sysu-mail          -> communications.mail.v1 / OPL Relay / SYSU account
gflab-site         -> publishing.site.v1 / gflab_web / laboratory site
editorial-manager  -> external.portal.v1 / browser adapter / journal account
```

同一 Provider 可以创建多个 Binding；停用一个 Binding 不应卸载 Provider，也不应影响其他
资源。删除 Package、删除 Binding、撤销凭据和删除外部数据是四种不同动作。

## Persona Recipe / Profile

Recipe 是面向角色和工作流的能力组合，不是复制代码的新 Package：

```text
PI recipe
  knowledge.documents.v1  required/recommended
  personal.profile.v1     recommended
  communications.mail.v1  optional
  publishing.site.v1      optional
  forms.fill.v1            optional
  external.portal.v1      optional
```

知识库是当前 PI Persona 的核心 Binding，因为它保存长期知识、技术备忘录和用户维护的
个人资料；但它不是所有未来 Persona 的硬 runtime 依赖。邮件、网站和专业门户必须保持
可选：不使用这些服务的用户仍可使用 Persona 的知识与判断能力。

Recipe 只能声明需要或偏好的 Capability、选择 Binding 的规则和审批策略，不能写死
`gflab_web`、Apple Mail、Obsidian 路径或某个期刊站点。用户可以从 App 或 Codex 对话中
查看“可用 Capability → 已安装 Provider → 已配置 Binding → 可启用 Recipe”，再自由组合。

## 输入、输出与通用 Inbox

每个 Capability 可以是输入、输出或双向：

- 邮件既提供证据，也接收经批准的草稿与发送动作；
- 知识库既为写作和判断提供输入，也接收技术备忘录、论文摘要和个人资料更新；
- 网站既提供当前公开状态，也接收新闻、论文和列表更新 proposal；
- 专业门户既提供编辑/审稿任务，也接收经批准的表单和决定；
- `personal.inbox.v1` 接收论文、网页、邮件、任职、想法等 capture，再路由到知识、行动、
  通信或发布 proposal。

通用 Inbox 是 staging 与 triage surface，不是长期知识库或第二邮箱。条目只有在目标
authority 实际写入并回读后，才可标记为已迁移；保留 source reference，避免丢失来源。

最小私有条目合同为：

```yaml
schema_version: opl-persona-inbox-item.v1
item_id: inbox-...
captured_at: 2026-07-28T00:00:00Z
source_refs: [email-store://..., https://...]
source_kind: mail
summary: bounded derived summary
status: captured
routes: []
```

Inbox 只持久化稳定 `source_refs`、有界摘要、状态和路由记录，不复制邮件正文、网页归档、
Obsidian 文档或网站 checkout。需要完整内容时由对应 authority 重新读取。建议状态机为：

```text
captured -> triaged -> proposal_ready -> routed -> resolved
                    \-> dismissed
```

每个 route 至少记录目标 `capability_id`、`binding_id`、proposal ref、owner action ref
和 authority receipt/readback ref。`routed` 只表示已交给 owner；只有目标 authority
回读成功后才进入 `resolved`。原始邮件即使被 capture，仍由 Relay 邮箱存储拥有，不会
迁入 Persona Inbox。

## 发现、组合与状态

发现应按以下顺序呈现，而不是把“安装插件”当成全部状态：

```text
discover Package
  -> enumerate Capability declarations
  -> inspect Provider implementation and supported operations
  -> configure/authorize Resource Binding
  -> select Persona Recipe
  -> health check and currentness readback
```

建议的用户可见状态是：`available`、`installed`、`configured`、`healthy`、`degraded`、
`approval_required`。状态必须来自 Provider 和 authority 的 fresh readback；Package
descriptor、测试 fixture 或本地候选不能证明真实资源已可用。

## 模块扩展规则

新增模块时依次判断：

1. 是否已有 Capability Contract 可以复用；
2. 能否只新增 Provider Adapter，而不新增 Core 或 Repo；
3. 用户差异是否只需要一个 Resource Binding；
4. 角色差异是否只需要调整 Recipe；
5. 只有出现独立发布、权限、团队 ownership 或真实跨 Package 复用需求时，才新建 Package
   或 Repo。

不要为每个网站、期刊、表格或用户创建插件，也不要先造通用 CMS、浏览器框架、凭据系统
或大型插件总线。第一条真实闭环应优先复用现有 Relay、Obsidian、`gflab_web`、Office 与
浏览器能力，证明 contract 后再抽象。

## 分阶段落地

1. **合同固化**：以本文档为设计 SSOT，后续在 Package descriptor 中逐步增加通用
   Capability 声明和 legacy alias，不改变现有 proposal 安全边界。
2. **三源闭环**：以 Obsidian、Relay、`gflab_web` 验证一次“论文 → 知识库 + 网站 + 邮件”
   的 proposal/readback 链路。
3. **Binding 管理**：carrier-neutral Package discovery/status/action projection 已可用；
   下一步由 Provider 提供 Binding health/readback，OPL App 只呈现其结果。
4. **专业输出扩展**：按真实频率加入表格和外部专业门户 adapter，不预制低频站点。
5. **Recipe 组合**：形成 PI、学术编辑、审稿专家等 Recipe；Recipe 始终可检查、可调整、
   可停用。

完成标准不是“架构图已存在”或“Package 已安装”，而是选定 Binding 上的真实输入、精确
proposal、用户批准、owner adapter 执行及 authority readback 能够完整闭环。
