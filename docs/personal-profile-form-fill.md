# OPL Persona 个人资料与表格填写架构

Owner: `opl-persona`
Purpose: `personal_profile_form_fill_target_design`
State: `active_target_design`
Machine boundary: 本文仅定义未实装的个人资料字段目录与批量填表目标合同；当前已支持的单步/多步本机填表与回读见[可恢复任务手册](external-professional-work.md)，通用跨仓边界与 App 视图原则见[架构指引](architecture-guidance.md)。

## 目标与当前差距

当前 `opl-persona` 只导出 `opl-persona` Skill 及现有上下文、记忆、Inbox、Obsidian、邮件、网站与可恢复任务模块。目标设计需要补齐两层而不新建仓库或第二知识库：

- `personal_profile` / `form_fill` Core：持有 `personal_field.v1` 字段身份、来源、当前性、用途白名单、映射、`opl-persona-proposal.v1` 负载与回读 receipt；
- `personal-form-fill` Skill：将自然语言填表请求路由到 Core，不得仅靠 prompt 记忆或绕过 Core 审批。

个人资料正文（身份、证件、银行、税务、履历等）永久保留在用户选定的唯一主源（Obsidian 或普通工作目录），遵循 [Framework 知识来源与记忆政策](https://github.com/gaofeng21cn/one-person-lab/blob/main/docs/policies/knowledge-source-and-memory-policy.md)。Persona 仅在 `<profile>/profile/` 保存不可入 Git 的引用、规则和映射模板：

```text
~/OPL/profiles/<user>/profile/
├── field-registry.yaml   # field_id、classification、value_ref/source_refs（无个人值）
├── policies.yaml         # 用途、核验与审批规则
└── form-maps/            # 可版本化的表单字段映射（无个人值）
```

## 字段与回读合同

每个可填字段使用稳定 `personal_field.v1` 记录：

```text
field_id             例如 identity.legal_name.zh 或 payment.bank_account
classification       public | professional | confidential | highly_sensitive
value_ref            obsidian://...（或选定主源定位）
source_refs          原始简历、证明、邮件或用户确认引用
verified_at          最后人工或权威回读日期
allowed_purposes     lecture_fee | travel | cv | academic_service | ...
display_policy       full | masked | never_in_chat
```

- `field_id` 是接口契约，禁止模型按相似标题猜测或跨用途复用；缺失来源、用途或有效期限时返回 `needs_user_input`。
- 所有输出沿用 `opl-persona-proposal.v1`：`form_fill_request.v1` → 字段与缺失检查 → `opl-persona-proposal.v1`（目标模板/站点 identity、字段映射、`value_ref`、预期 `base digest`、掩码 diff）→ 用户批准 → owner adapter 执行 → `form_fill_receipt.v1` 权威回读。
- 首批目标：`personal.form.docx_draft`、`personal.form.pdf_draft`、`personal.form.xlsx_draft`、`external.portal.form_draft`、`external.portal.form_submit`。
- 聊天、审批队列与 activity log 默认仅显示字段名、来源与掩码，不保存或泄露原始敏感字段值；上传证件、传输银行信息、网站提交与对外承诺均须逐次精确确认，未知外部结果禁止自动重试。

## Adapter 边界与验收

| Adapter | 负责 | 不负责 |
| --- | --- | --- |
| DOCX / XLSX / PDF | 读取字段、保留原布局、生成 draft、回读已写文件 | 推断个人资料或提交网站 |
| 浏览器 / Portal | 在已授权会话中填入、预览、提交和回读 | 保存密码、绕过 MFA 或扩大 scope |
| 人工导出 | 生成字段清单和可复制内容 | 伪造已填写/已提交 receipt |

新表格优先新增 `form schema + field map`，仅在同类稳定模板或站点高频复用时增加薄 adapter。验收分四步推进（资料盘点 → 单模板闭环 → 格式扩展 → 外部提交），每阶段必须证明字段来源/用途/当前性、零敏感值泄露、目标与批准 proposal 一致及 owner adapter 实际回读。
