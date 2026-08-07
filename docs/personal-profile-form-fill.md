# OPL Persona 个人资料与表格填写架构

Owner: `opl-persona`
Purpose: `personal_profile_form_fill_target_design`
State: `active_target_design`
Machine boundary: 本文定义 Persona-owned 个人资料引用与表格填写目标边界。当前 Package descriptor、runtime 与 tests 尚未导出 `personal_profile` / `form_fill` Core、`personal-form-fill` Skill、form action、adapter 或 receipt；下文字段合同、CLI、proposal target 与分阶段闭环在对应 owner source/tests 和目标文件或门户 readback 出现前都不是当前可调用行为或完成证明。

本文件是 OPL Persona 中“个人资料与表格填写（Personal Profile and Form Fill）”
子域的目标设计权威。它扩展
[Architecture Guidance](architecture-guidance.md)，并为
[对外专业工作](external-professional-work.md)提供受控的个人字段输入；不改变
Obsidian、邮件、第三方门户或 OPL App 的既有 authority。

## 当前实现边界

当前 owner descriptor 只导出一个 `opl-persona` Skill，以及 context、memory、Inbox、
Obsidian、mail 和 website proposal modules。现有 Resource Binding 只为用户选择的
Obsidian 资源提供 opaque binding 与 owner-side resolution；它不等于个人字段 registry、
表格解析器、form adapter 或提交 route。本文提出的 Core、Skill、action 名和 receipt
shape 都是后续 owner contract 候选，不得被 App、Framework 或自动化当成已安装、已发布
或可执行接口。

## 目标与结论

大学教授经常需要填写讲课、差旅、个人简历、学术任职、报销、收款等表格。可靠填表
应直接使用用户维护的个人资料，而不是让模型从多个简历、附件和旧表格中猜测哪个版本
最新。

本子域的目标是：

> 以 Obsidian 中的个人资料和字段来源为事实基础，按用途准备表格内容，并以
> review-gated proposal 输出准确的本地表格或网站草稿。

它必须同时提供一个**核心模块**和一个薄 **Codex Skill**：

- `personal_profile` / `form_fill` Core 负责字段身份、来源、当前性、用途、映射、
  proposal 与 receipt；
- `personal-form-fill` Skill 将自然语言请求路由到 Core，并说明当前资料、缺失字段与
  审核动作；
- Skill 不是个人信息数据库，不能仅靠 prompt 保存字段，也不能绕过 Core 的用途、
  approval 和 readback。

不新建 Repo、独立“个人资料 App”、第二套知识库或通用表格渲染器。它是
`opl-persona` 的可扩展内部模块；现有 Office、PDF、浏览器和网站 adapter 是它的
执行 surface。

## Authority 与数据边界

| 数据类别 | Authority | Persona 的使用方式 |
| --- | --- | --- |
| 履历、单位、职称、研究方向、成果、任职、讲课资料 | 用户维护的 Obsidian note / vault attachment | 通过稳定 `source_ref` 读取、核验和引用 |
| 公共主页和团队简介 | `gflab_web` 与已核验的 Obsidian 资料 | 作为公开表述的辅助证据，不替代 Obsidian 资料 |
| 联系方式、办公/通讯地址与邮编 | 用户维护的 Obsidian note | 按本次用途读取并填入对应字段 |
| 身份证、护照、银行账户、开户行、税务、收款信息及其他个人资料 | 用户维护的 Obsidian note / vault attachment | 按需读取；只在获准的目标字段中使用 |
| 邮箱和邮件关系事实 | Relay / 邮件 provider | 仅按已授权用途取用，不把邮箱历史自动变为 profile 值 |
| 表格字段、提交状态和正式结果 | 目标文件或第三方表单 | adapter 回读后生成 receipt |

个人资料统一由 Obsidian 管理，包括用户认为需要保留的身份、证件、金融、税务和
收款字段；本设计不要求迁移到 macOS Keychain，也不额外建立一套秘密值库。Obsidian
是这些个人资料值的 authority，Persona 只保存可审计的引用、来源、当前性、用途和
审批状态。

个人资料值仍不得复制到 Git、Plugin cache、Package 安装目录、聊天记录、截图、
proposal log 或 OPL App durable state。需要在外部表格中使用时，只把本次批准的字段
传给对应 adapter；聊天、审批队列和 activity log 默认展示字段名、来源和必要的掩码。

Persona workspace 只保存可审计的引用和 policy：

```text
~/OPL/profiles/<user>/
├── profile/field-registry.yaml       # field id、classification、value/source ref
├── profile/policies.yaml             # 用途、核验和审批规则
└── profile/form-maps/                # 可版本化的表单字段映射；无个人值
```

这些是私有运行态，不进入源仓、Plugin cache 或 OPL App 的领域状态；它们不是新的值库，
Obsidian 仍拥有个人资料事实。

## 字段与来源合同

每个可填字段都使用稳定 `personal_field.v1` 记录。其最小结构是：

```text
field_id             例如 identity.legal_name.zh 或 payment.bank_account
classification       public | professional | confidential | highly_sensitive
value_ref            obsidian://...
source_refs          原始简历、证明、邮件或用户确认的引用
verified_at           最后人工或权威回读日期
allowed_purposes      lecture_fee | travel | cv | academic_service | ...
display_policy        full | masked | never_in_chat
```

`field_id` 是 API；文件路径、简历段落和表单标题不是 API。模型不能根据相似表述自行
填充字段，也不能将一个用途的授权扩大到其他用途。敏感等级只用于决定展示和审批
强度，不改变个人资料统一由 Obsidian 管理这一事实。

字段目录必须能回答：“此字段来自哪里、是否仍有效、可用于什么表、是否能在聊天中显示”。
缺任何一项时，Core 应返回 `needs_user_input`，而不是从旧 CV 或相邻字段猜测。

## 表格、proposal 与回读合同

本子域不创建第二套跨系统写入原语。所有输出仍使用现有
`opl-persona-proposal.v1`，但 form payload 必须绑定具体的表单、字段和目标：

```text
form_fill_request.v1
  -> field discovery and missing-field report
  -> opl-persona-proposal.v1 (exact template, field map, value refs, diff)
  -> user approval
  -> owner adapter writes a draft or submits the exact form
  -> form_fill_receipt.v1 with authoritative readback
```

首批 proposal targets：

```text
personal.form.docx_draft
personal.form.pdf_draft
personal.form.xlsx_draft
external.portal.form_draft
external.portal.form_submit
```

proposal 与 receipt 至少要含：目标模板/站点 identity、字段名、字段来源、预期 base
digest、应用范围、敏感字段 mask、用户批准记录和回读 reference。个人资料值仅可在获准的
最终字段中写入；聊天、审批队列和 activity log 默认只展示字段名、来源与掩码。

“生成草稿”“保存本地文件”“填入网站”“提交网站表单”“签字/上传证件”是不同状态。
上传证件、传输银行信息、提交网站、发送电子邮件或作出对外承诺始终需要精确、逐次的
用户确认；未知外部结果不得自动重试。

## Adapter 与可扩展性

Core 只定义字段、映射、proposal 和验证，不自己解析每一个 Office 文档或操作每一个
网页。adapter 按目标格式实现，优先复用现有平台能力：

| Adapter | 负责 | 不负责 |
| --- | --- | --- |
| DOCX / XLSX / PDF | 读取字段、保留原布局、生成 draft、回读已写文件 | 推断个人资料或提交网站 |
| 浏览器 / Portal | 在已授权会话中填入、预览、提交和回读 | 保存密码、绕过 MFA 或扩大 scope |
| 人工导出 | 生成字段清单和可复制内容 | 伪造已填写/已提交 receipt |

因此一份新表格首先是 `form schema + field map`，不是新代码模块。只有同一类模板或
站点反复出现、且其结构稳定时，才添加薄 adapter。对外专业门户使用本模块的
`personal_field.v1`，但仍受其自身 role、site scope 与 per-task approval 约束。

## OPL App 与 Codex Plugin 目标形态

目标形态下，Codex Plugin 将提供 `personal-form-fill` Skill，以及必要的 Core CLI
action：

```text
profile audit       汇总缺失、过期和不完整来源的字段
form inspect        识别模板、字段、约束和目标输出
form draft          生成带来源和掩码的 proposal
form apply          仅对已批准 proposal 调用目标 adapter
form readback       验证文件或网站的实际结果
```

OPL App 不需要专用“个人资料页面”。它通过既有的角色无关视图渲染：

```text
task_board      待填表与资料补全任务
approval_diff   字段级来源、掩码和模板 diff
artifact_view   模板、草稿和已填文件
activity_log    adapter 回读与 receipt
```

App 不能拥有个人值、浏览器 cookie 或领域写入逻辑。

## 分阶段落地与验收

1. **资料盘点**：在 Obsidian 中建立字段目录、来源与 `verified_at`；不复制到 Persona、
   Git 或插件缓存。
2. **单模板闭环**：选择一个真实、常用的讲课/行程/CV 模板，完成
   inspect → draft → approval → 写入副本 → readback。
3. **格式扩展**：按实际频率增加 DOCX、PDF、XLSX 或网页 adapter，不重复实现 Core。
4. **外部提交**：在字段级审批、提交确认和外部 receipt 已验证后，再支持收款、证件
   上传和网站提交。

完成不是“模型能回答个人资料”或“预览看起来正确”。每个可宣称的闭环都必须证明：

- 每个字段有合法来源、用途和当前性；
- 个人资料值未泄漏至 Git、日志、聊天或缓存；
- 保存/提交的目标与批准 proposal 精确一致；
- owner adapter 已回读实际文件或第三方系统结果。
