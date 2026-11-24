# OPL Persona 可恢复任务与工具操作手册

Owner: `opl-persona`
Purpose: `resumable_tasks_and_local_tool_handbook`
State: `active_current`
Machine boundary: 本文记录当前已实装的可恢复任务（`personal.context.v1#tasks`）与本机/连接器工具操作入口；源码与测试归 `plugins/opl-persona/runtime/opl_persona/` 与 `tests/`。未实现的个人字段目录与网站门户目标边界见[架构指引](architecture-guidance.md)和[个人资料与表格填写](personal-profile-form-fill.md)。

Persona 可以在已登录的网页填表，在 macOS 窗口点击或拖动，也可以调用支持操作回执的连接器。一个任务可串联这些操作和已有的笔记提案。Studio 的「可恢复任务」与 Codex 共用任务记录；邮件、笔记和网站的专用接口仍各自负责业务数据。

## 任务准备与执行

1. 由用户登录目标系统并打开记录。网页表单使用 `agent-browser` 0.42 或更新版本：
   - `opl-persona browser open --session <名称> --url <网址>` 打开独立浏览器；各会话账号状态存于个人工作区 `data/persona/browser/`，可并行处理。
   - `opl-persona browser inspect --session <名称>` 读取当前网址、标签页 ID 和可访问内容。
   - `opl-persona browser close --session <名称>` 关闭会话（已保存的登录状态留在原资料目录）。
   - 如需复用已登录 Chrome 会话，先在 Chrome 允许本机调试连接，再加 `--shared`（有明确获准端口时加 `--chrome-port <端口>`）；关闭会话时只关闭该会话标签页。
   - 原生窗口用 `agent-desktop list-windows` 取得窗口和进程身份，再用 `snapshot` 核对控件和记录。
2. 用 `opl-persona task prepare --input -` 准备任务。输入包含 `task_id`、`title`，以及 `plan.source_refs` 和有序的 `plan.steps`（每步含 `kind`、`title`、`input`）：
   - `fill`：接受 `target`、唯一文字字段名称 `field`、`before` 和拟填写 `value`。
   - `submit`：接受 `target`、按钮名称 `button`、已审字段和值 `fields`，以及回执目标 `result`。
   - `proposal`：通过 `proposal_id` 与 `expected_digest` 引用现有提案，沿用其负责人审核和应用入口。
   - `tool`：`input` 包含 `provider`、`action` 与 `arguments`。
   - 浏览器 `target` 含 `browser_session`、`tab_id`、`page_url`、可见记录标识 `marker` 和可见账号标识 `account_marker`；原生窗口 `target` 含 `app`、`window_id`、`process_instance` 和 `marker`（窗口内门户同样需要精确网址与账号）。
   - 提交结果沿用同一标签页/窗口、账号、站点和该记录专属回执标识。任务仅处理经审核的普通字段；登录、MFA、CAPTCHA 与受保护字段由用户直接在网站处理。
3. 查阅当前步骤提案并批准。调用 `task run` 时提供任务编号、当前 `proposal_id`、`expected_digest` 和用户确认 `confirmation: "confirmed"`。原生窗口操作前将目标窗口切到前台；浏览器会话始终绑定所选标签页。账号、记录或字段变化时回到任务重新核对目标。
4. 换对话或重启后用 `task list`、`task inspect` 找原任务；结果待核对时运行 `task check` 读取原操作结果并保存回执。门户窗口重开后传入新的 `window: {window_id, process_instance}`，独立浏览器在同一会话重开原回执页后传入新的 `tab_id`，二者均需核对原网址、账号和回执标识。已派发且待核对的步骤会暂缓同一工具通道内的新写入，其他通道可继续工作。

## 图形窗口与连接器

- **图形窗口操作**：先把窗口切到前台，用 `opl-persona tool capture-window --input -` 读取目标窗口图像、尺寸和摘要（输入与原生表单相同的 `target` 对象）。使用 `agent-desktop` 的 `click` 或 `drag` 动作，提供 `target`、审核图像摘要 `before` 与相对图像左上角的像素坐标 `at: [x, y]`（拖拽另需 `to: [x, y]`）。结果图像显示在任务的 `pending_readback`，核对后在 `task check` 的 `review` 对象提供原 `operation_id`、结果图像 `digest` 和 `confirmation: "confirmed"` 完成核验。
- **GitHub Issue 标签**：使用现有 `gh` 登录。`opl-persona tool github-issue --repo <仓库> --number <编号>` 读取账号、Issue ID、状态和标签版本，将 `repo`、`number`、`account`、`issue_id`、`expected_revision` 和 `label` 交给 `github` 的 `issue.label.add` 动作，执行后回读 Issue 标签。
- **独立连接器 Package**：通过 `opl-persona tool connector --package-id <ID>` 查看支持工具执行合同的已安装 Package 操作目录。`opl-package` 的 `execute` 动作接收 `package_id`、`operation`、`target_ref`、`expected_revision` 和业务 `input`；凭据与业务回执由连接器维护。协议详情见[连接器合同](architecture.md#connector-package-contract)。
