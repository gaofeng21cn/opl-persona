# Persona 的 App 集成边界

Owner: `opl-persona`
Purpose: `persona_app_consumer_boundary`
State: `active_reference`

本文只定义 Persona contribution 的消费与审核边界。当前可调用 refs 归
[实现架构](architecture.md)及 Package descriptor；App 产品、导航、标准 renderer 和
发布验收归 `one-person-lab-app`，Framework projection 归 Framework，物理安装归原生 carrier。

## 动态贡献

Persona 和 Relay 使用角色无关的 `app_contributions`，不要求 `standard_agent` 身份。
App 读取 Framework 返回的 identity、presence、callability、data refs 和 action refs，
通过同一套标准视图消费任意合规 Package。未知 Package 不需要新增静态卡片或 package-id 分支；
单包无效或不可用只影响它和直接依赖，不阻断其他能力。

Package descriptor 声明入口不代表相应账号、vault 或网站已配置。Carrier installed readback、
Framework route readback、Provider Binding 健康以及 App 实际渲染是不同证据。
Persona 不在本仓保存 App 功能完成表、已安装包清单或其他 owner 的待办。

## 状态与动作

| 对象 | 决策与执行 owner | App 消费边界 |
| --- | --- | --- |
| 安装、更新、修复、卸载 | 配置的原生 carrier | 仅调用 Framework 投影的动作并回读；不自建 updater、resolver、installed lock、payload、LKG 或状态库 |
| 启用、停用 | 实际支持该操作的 carrier | 不从 manifest 推断一个通用开关 |
| 导航显隐、排序 | App preference owner | 不改变 installed truth；显隐不等于卸载或停用 |
| Resource Binding | 对应 Provider 与用户 | 显示 refs-only 健康和诊断，不复制凭据或资源正文 |
| Proposal | Persona | 显示来源、目标与精确变更，调用已声明动作 |
| 邮件、vault、网站写入 | 对应领域 adapter | 保留各自授权和回执，不由 App 直接执行领域写入 |

卸载是用户选择，普通启动、维护和更新不能自动装回；首次 Official Profile 安装或明确
Restore 由其平台 owner 处理。Package、Binding、凭据和外部数据具有独立生命周期。

## 审核投影

统一审核只统一视图语言。每项审核必须引用 Package identity、proposal/draft identity、
`data_ref`、`action_ref`、目标 owner、evidence/provenance、diff 或 draft fingerprint、
必要确认，以及执行后的 authority receipt。App 不持久化第二份领域审批状态。

Persona proposal 的批准只允许该精确 proposal 进入相应 adapter。网站本地 apply 不等于发布；
Obsidian 写入需要 Binding scope、proposal digest 与目标文件 precondition；Relay 草稿审核
与发送是两个动作：

```text
Persona proposal review
  -> Relay draft creation
  -> Apple Mail review/edit
  -> current draft fingerprint
  -> explicit send approval
  -> authoritative send readback
```

App 不绕过 Relay 发信，也不绕过网站或知识库 adapter 写入。缺少可执行 owner handler 时，
显示 owner 返回的局部不可用状态，不根据描述文本补造成功结果。

## 集成验收

在目标主机上分别回读 carrier state、Framework contribution route 和 App 可见视图。
用未知合规 Package 验证通用路由，用局部失败验证其他能力可继续使用。
维护动作只由投影 route 到达 carrier；普通 invocation 不触发更新，卸载选择跨重启仍保留。
审核项必须将实际确认、owner action 与最终回执连起来。

验收只证明被实际执行的范围；源码、模拟输入、descriptor 或历史截图不能证明私有 Binding
可用、外部写入完成或 App 已发布。跨仓下一动作由各 owner 的当前合同决定。
