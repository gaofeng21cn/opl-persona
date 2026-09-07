# OPL Persona 可组合能力与集成模型

Owner: `opl-persona`
Purpose: `persona_composable_capability_target_design`
State: `active_target_design`

本文定义可替换能力的目标组合关系。当前 exports、Binding schema、Inbox 状态和可执行动作
只在[实现架构](architecture.md)及其源码维护；本文不新增另一套机器合同或兼容入口。
个人资料、表格、专业门户与 Recipe catalog 尚不是当前可调用能力。

## 对象分工

| 对象 | 负责的问题 | 约束 |
| --- | --- | --- |
| Package | 能力代码与 descriptor 的安装单元 | owner 声明 identity、依赖和 publication；原生 carrier 执行物理生命周期 |
| Capability | Provider 对消费者保证的领域语义 | 不把 UI 页面、文件路径或安装包当成语义 identity |
| Provider Adapter | 实现能力并返回实际 action refs | 保留外部系统 authority，不接管跨域判断 |
| Resource Binding | 用户选择并授权的具体资源 | 私有 refs、scopes、policy；不复制秘密或正文 |
| Persona Recipe | 为角色和工作组合能力与 Binding | 不复制代码或数据，不成为另一个 runtime |

一个 Package 可以提供多个能力，同一能力可以有多个 Provider。同一 Provider 可以绑定多个
资源；移除 Binding 不应卸载 Provider 或影响其他资源。Package 移除、Binding 移除、凭据撤销
和外部数据删除是四个独立动作。

Framework 发现 installed descriptor、委托 carrier 并聚合状态；App 消费结构化贡献。
Persona 只持有跨域判断、provenance 和 proposal。详细消费规则归
[App 集成](app-integration.md)，领域分工归[架构指引](architecture-guidance.md)。

## 能力与真实调用

邮件、知识、网站、个人资料、表格、门户和 Inbox 是组合需求，不是一张预注册的产品清单。
已导出的 `knowledge.obsidian.v1`、`website.publication.v1`、`communications.mail.v1`
和 `personal.inbox.v1` 仍按 descriptor 与调用者的实际合同使用。
`knowledge.documents.v1` 已被 Obsidian Binding 接受，但不表示存在通用 Provider resolver。
`publishing.site.v1`、`personal.profile.v1`、`forms.fill.v1` 和 `external.portal.v1`
只属于设计候选，不能由 App 根据本文推导可调用动作。

后续增加通用能力时，由真实 Provider 声明所支持语义并返回 opaque action ref；消费者使用
该声明，不在 App 建立硬编码映射。Capability identity、action ref 与 proposal schema
各自负责不同合同。旧出口在真实调用者切换后一起退役，不创建永久别名或兼容层；已经发布的
identity 不得复用为另一种语义。

Provider 只暴露实际支持的 inspect/health、read/search、propose、approved apply 或 readback。
某个 Provider 可以只读；安装不能推导可写。所有跨系统写入仍使用精确的
`opl-persona-proposal.v1`、用户批准、owner adapter 和最终 authority readback。

## Binding 与健康

Binding 存放在选定 Profile Workspace 的 `data/persona` 下。资源正文、邮件、网站 checkout、
个人资料值和 Cookie/token/密码继续由资源 owner 或用户选择的安全存储持有。
Persona 仅保存资源引用、scope、policy 和观察信息，不将它们复制进 Git、Package、Plugin cache
或 App durable state。个人资料值统一归用户维护的 Obsidian，详见
[个人资料与表格](personal-profile-form-fill.md)。

Provider 的 fresh probe 决定当前可达性、支持操作和授权范围；保存的健康观察不能成为永久事实。
当前目录 probe 只证明目录可达，不证明 note 写权限、资料质量或端到端工作流。
未探测或无法验证时保留 unknown，不从 installed/enabled 状态猜测资源健康。

## Recipe

Recipe 声明角色需要或偏好的 Capability、Binding 选择规则和审批策略。
PI 当前以知识库作为核心资源；这不使 Obsidian 成为所有未来 Persona 的硬 runtime 依赖。
邮件、网站、表格和专业门户保持可选，未使用这些资源的用户仍可使用其余能力。

Recipe 不写死邮箱客户端、网站生成器、vault 路径或期刊站点。用户应能从可发现能力、已安装
Provider、已配置 Binding 中选择组合，并可检查、修改、停用 Recipe。
具体 Recipe registry 和 UI 只有在真实角色出现稳定复用需求后才实现。

## 输入输出与 Inbox

能力可以提供输入，也可以接收已批准的输出。Inbox 是跨域 capture 的私有 staging：保存
稳定 source refs、有界标题与摘要、状态及 route refs；完整邮件、网页、vault 文档和网站源码
从其 owner 重新读取。Inbox 不升级为邮箱、知识库或外部任务系统。

“已交给 owner”与“目标已写入”分开记录。报告交付完成前必须取得相应 owner 的成功回读；
本地状态转换不能替代它。当前 Inbox 存储和状态枚举归 `inbox.py`，不另定义设计状态机。

## 扩展条件

优先复用当前能力与 owner adapter：用户资源差异归 Binding，角色差异归 Recipe。
只有独立发布、权限或真实跨 Package 复用证明需要时才新建 Package 或仓库，
不为每个站点、表格或用户预建插件、CMS、浏览器框架或凭据系统。

先用选定资源证明真实输入、proposal、批准、owner 执行与回读，再抽取稳定共性。
表格与门户的独立设计分别归其主题文档；安装、架构图和本地测试不代表这些目标已完成。
