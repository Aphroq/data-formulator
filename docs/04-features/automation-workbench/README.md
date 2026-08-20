# Automation Workbench 工程记录

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 分支 | `feat/automation-workbench` |
| Worktree | `D:\projects\dfm-wt-automation` |
| 本机实例 | `automation`：后端 5570、Vite 5176、数据目录 `D:\projects\dfm-runtime\automation` |
| 基线 | Recipe Core `3cd7ee12`；6 个 M3-A 提交已线性重放，M3-A tip 为 `fd1f347c` |
| 当前阶段 | M4 强杀恢复、验收加固、typed values、报告瘦身、显式 AI 解读、参数语义优先收口、复杂真实数据回归、复杂 AI 参数推荐联动及 SiliconFlow 参数推荐 live 验收已完成；之后再做默认浏览器 E2E、报告 AI live、真实外部 connector 和进程监督/长期运行决策 |
| 交接 | [Automation Workbench 分支交接](./HANDOFF.md) |

## 目标

为 Published RecipeVersion 增加同主机持久化 Schedule、Run、Worker 和 Runs Inbox。

## 范围

- SQLite migration 和 Recipe/Schedule/Run repository 集成。
- Scheduler 唯一入队。
- lease Worker、续租、恢复、取消和有限重试。
- `data_formulator_worker` 入口。
- Schedule 设置和 Runs Inbox。
- schema drift → Needs Review。
- `AUTOMATION_ENABLED`。

不包含运行期 Agent、TrustGraph、Copilot 专用集成或第二套 Recipe 编译/执行逻辑。2026-08-20 的参数能力分成两个阶段：现有 AnalystAgent 在交互分析中声明少量 typed slot，并由服务端随签名代码持久化；保存 Recipe 时的可选 LiteLLM Client 调用复用 Workflow 上下文，只推荐其中真正值得在以后运行时改变的少量选择，再与 Compiler candidate 对齐。报告上的“AI 解读”同样是用户显式触发的一次性后处理，只解释已校验的 Run 结果样本。三者都不新增 Agent runtime；模型调用不进入 Automation Run、Scheduler 或 Worker。

## M3-A：Automation 导航与 Recipe 管理

### 用户问题与本阶段目标

Recipe Core 已经可以保存、校验、发布和手动运行 Recipe，但入口仍以“Recipes”技术对象为中心。M3-A 建立一个易发现、不过度设计的 Automation 工作台：入口复用 Data Formulator 现有的工作区侧栏，与会话、数据连接器和知识处于同一层级；不再增加一层 `App / Automation` 导航，也不改名或重组原有 Workflow Replay、知识和会话概念。

最初实现曾把一个 Recipe identity 称为 Automation project。2026-08-19 的跨层核对确认该术语会与现有项目/Workspace 概念冲突，产品模型现已收口为 `Workspace → Recipe → RecipeVersion → Run/Schedule`。源码的数据结构和当前中英文文案都已统一为 Recipe，不增加 Project id、容器或 repository。

本阶段的用户路径只有一条：

```text
现有工作区
  → 完成分析并 Save as Recipe
  → 原有侧栏 Automation
  → 选择 Recipe 和版本
  → dry run → publish → run now / archive
```

### 参考产品与取舍

| 参考 | 可复用模式 | 本项目取舍 |
| --- | --- | --- |
| [Open WebUI Workspace](https://docs.openwebui.com/features/workspace/) | 用稳定入口承载可复用资产；列表默认按最近更新组织 | 在现有工作区侧栏增加一个 Automation 入口和最近更新 Recipe 列表，不复制另一套全局导航 |
| [Langflow Projects](https://docs.langflow.org/1.8.0/concepts-flows) | 以 Project 作为相关 Flow 的管理容器 | 不采纳 Project 容器；本项目已有 Workspace/项目语义，Automation 直接管理 Recipe，版本保留在 Recipe 内 |
| [n8n Executions](https://docs.n8n.io/workflows/executions/all-executions/) | 执行记录既有全局入口，也能回到具体工作流上下文 | M3-A 先只展示当前操作结果；M3-D 已用持久化 Run 契约增加 Runs Inbox，并让 Needs Review 回到固定 RecipeVersion |

### 信息架构

- 工作区左栏：沿用现有添加数据、会话、数据连接器、知识这一层，只新增 `Automation`；原有 `About / App` 顶部导航保持不变。
- Automation 页面继续显示同一条工作区左栏；从会话、连接器或知识入口返回 App 时，打开对应的原有面板。
- Automation 页头不再提供重复的“打开应用”按钮；返回分析区统一使用同一条工作区侧栏。
- `/automation`：Recipe 列表 + 当前 Recipe 详情，保留 `/recipes` 重定向以兼容已有链接。
- Recipe 列表：每个 Recipe 只显示一次，展示名称、最新版本状态、版本数和更新时间。
- Recipe 详情：首屏只保留说明、版本状态和当前可执行的主操作；参数、输入、步骤、hash 与归档动作收进按需展开的“配方详情”。Published 版本另有定时运行管理，持久化 Run 统一进入运行记录。
- 创建入口：仍由分析产物的 `Save as Recipe` 触发；Automation 空状态和页头只引导返回 App，不新增无血缘的“空白自动化”。

### 范围与非范围

本阶段包含：

- 复用现有图标侧栏的尺寸、交互和 Tooltip，并为 Automation 保留可访问名称和选中态。
- 将现有 Recipes 页面升级为轻量 Automation Recipe 管理页。
- Recipe 级列表、版本切换、现有 dry run / publish / manual run / archive 操作。
- 中英文文案、旧 URL 兼容、聚焦前端测试和构建验证。

本阶段不包含：

- 节点画布、任意 DAG 编辑、模板市场或文件夹层级。
- Schedule 表单、Scheduler、Worker、Runs Inbox 或伪造的运行统计。
- 新建空白 Recipe、修改 Published RecipeVersion，或从聊天/Redux 推断 Recipe。
- 新数据库表或新的状态管理框架。

### 复用方案

- UI 继续使用仓库现有 React Router、MUI、Redux selector 和 i18next，不引入新的导航或组件库。
- 数据继续使用 `recipeApi.ts` 和 Recipe Core API；列表对象就是 Recipe，不增加中间容器。
- 当前 Workspace 和 identity 授权仍由后端上下文决定，前端不缓存另一份资源所有权状态。
- 状态和版本排序直接采用 repository 已有的 `updated_at DESC`、`created_at DESC` 契约。

### 实施顺序

1. 先写导航/Recipe 分组的失败测试，锁定 feature flag、Recipe 只出现一次、版本切换和旧路由兼容。
2. 从现有 `DataSourceSidebar` 抽出小型、可复用的工作区 rail；App 页面继续使用原有面板逻辑，Automation 页面只复用同一层入口。
3. 增加 `/automation`，把 `/recipes` 变成保留 query string 的兼容重定向；更新 Save as Recipe 跳转。
4. 将 Recipes 视图作为 Automation Workbench，Recipe 列表不再平铺版本，并加入 Recipe 内版本选择。
5. 完成中英文文案、聚焦测试、全量前端测试、生产构建和工程记录。

### 验收标准

- `AUTOMATION_ENABLED=false` 时原有工作区侧栏不显示 Automation，直接访问页面仍失败关闭。
- 启用后，Automation 与会话、数据连接器、知识处于同一条 rail；当前入口有明确选中态，不出现第二条 `App / Automation` 左栏。
- 原有会话、知识、Workflow Replay、About 和 App 的名称、含义与入口行为不因本阶段改变。
- 一个含多个 RecipeVersion 的 Recipe 在列表中只出现一次，且可在详情内切换版本。
- 各版本只能执行其状态允许的操作，现有参数 typed binding 保持不变。
- dry run 完成后，当前页先展示验证结论、步骤和耗时；Run ID、输出位置、指纹与原始安全错误只在“技术信息”内按需展开。持久化手动 Run 返回 queued 后进入运行记录，切换版本时清除旧的 dry run 结果。
- `Save as Recipe` 打开 `/automation?version=...`，旧 `/recipes?version=...` 无损重定向。
- 页面在常用桌面宽度可用；窄屏导航不遮挡内容并保持键盘/读屏可达。
- 不新增调度、Worker、LLM 调用或复杂编排依赖。

### M3-A 实施结果

- Automation 复用原有工作区图标侧栏，与会话、数据连接器和知识处于同一层；没有新增 `App / Automation` 外层左栏。
- 原有 `About / App` 顶部导航及会话、知识、Workflow Replay 的概念和行为保持不变。
- `/automation` 按 Recipe identity 聚合列表，Recipe 内可切换不可变 RecipeVersion；现有 dry run、publish、run now、archive 和 typed parameter binding 原样复用。
- `Save as Recipe` 改为进入 `/automation?version=...`；旧 `/recipes` 路径保留 query/hash 后重定向。
- `AUTOMATION_ENABLED=false` 时导航入口隐藏且直接访问失败关闭；无活动 Workspace 时不展示跨 Workspace 数据。
- M3-A 当时为 dry run 和同步手动运行展示轻量结果面板；M3-D 已把手动运行改为持久化入队，轻量结果面板仅保留 dry run，后台历史由运行记录展示。2026-08-19 的体验收口进一步把 Run ID、输出路径和指纹下沉到折叠的技术信息。
- 已继承 Recipe Core M2-D 的过期请求丢弃、URL 版本同步、immutable 版本元数据和“动作结果先落地、后续刷新失败只告警”语义；M3-D 又为 Schedule、Run 列表和 artifact 对话框增加作用域切换时的旧请求丢弃。
- M3-A 没有加入节点画布、Scheduler、Worker、Runs Inbox、新数据库表或新的状态管理依赖；这些后台能力只在后续 M3-B/C/D 按既定边界增量接入，节点画布与新状态框架仍未引入。

## 开发前源码审计（2026-08-19）

| 优先级 | 已核对事实 | 处理结论 |
| --- | --- | --- |
| P0 | `app.py` 未配置 `FLASK_SECRET_KEY` 时仍使用进程内随机 secret；always-on CoreSkill 需要维持原有交互行为 | 已在 Recipe Core `3cd7ee12` 恢复 app-secret fallback；Recipe 写操作、Service、Compiler 和无请求 Executor 只接受稳定 key，API 安全映射为 `SERVICE_UNAVAILABLE` |
| P0 | `tests/conftest.py` 为所有测试默认注入 `DF_CODE_SIGNING_SECRET` | 已增加显式删除两种稳定 key 的交互、API、Service、Compiler 和 Executor 回归 |
| P1 | `recipes.json`、`Recipes.tsx` 测试标题和列表标签曾出现 `Projects / 自动化项目` | 已收口为 `Recipes / 配方`，数据模型仍只有 Recipe/RecipeVersion |
| P1 | 当前实现只有 `/automation`，`/recipes` 已重定向；旧系统设计仍写两个最终页面 | 已同步产品和系统设计为单一入口，不恢复独立 Recipes 导航 |
| P1 | 原 `RecipeRepository.SCHEMA_VERSION == 2`，初始化会拒绝任何未知更高 migration | 已抽取唯一 `AutomationDatabase` owner；v3 引入 Schedule/Run，v4 增加 attempt 恢复字段，当前 v5 增加 Schedule policy 与 Run value snapshot，两个 repository 可交替打开同一库 |

Recipe 修复验证：聚焦后端 67 passed、1 skipped；全量后端 2251 passed、16 skipped、1 xfailed；Recipe 前端 399 passed，生产构建通过。Automation 术语收口聚焦前端 11 passed。

## M3-B 实施契约：Schedule 与持久化 Run

### 单一数据库与 schema v5

- `DATA_FORMULATOR_HOME/automation/automation.db` 仍是唯一目录数据库。
- `AutomationDatabase` 已统一绝对路径、WAL、foreign keys、`busy_timeout`、显式事务和 v1 → v2 → v3 → v4 → v5 顺序 migration；`RecipeRepository` 与 `AutomationRepository` 共同使用。
- v3 已在现有 `recipes` / `recipe_versions` 上增加 `schedules` / `runs`，v4 为 Run 增加 active/cleanup attempt id，v5 为 Schedule 增加 `parameter_policy_json`、为 Run 增加不可变 `parameter_values_json`；合同测试覆盖空库初始化、v2 顺序原地升级、带存量 Schedule/Run 的 v3/v4 → v5 保留、重复初始化、事务回滚和未知未来版本失败关闭。
- 所有查询和写入都带 `identity_id + workspace_id`；Schedule 外键固定同 scope 的 RecipeVersion，创建时必须验证其状态为 `published`。

### Schedule 契约

- v1 持久化规范化五段 Cron 和 IANA timezone；每日调度由 UI 转换为受控 Cron，不另建执行语义。
- v1 Cron 求值只接受数值、列表、升序范围和步长，day-of-month/day-of-week 使用 union 语义；春季不存在的墙上分钟跳过，秋季重复墙上分钟只执行一次。
- `version_id` 创建后不可修改。切换新版本需要创建新 Schedule，现有 Schedule 不随 Recipe 发布静默迁移。
- enabled Schedule 引用的 RecipeVersion 不得归档；用户必须先显式停用。引用 archived version 的 Schedule 保留审计关系，但不得重新启用。
- `next_run_at` 以 UTC 保存；单次 scheduler tick 在一个事务中入队当前到期 Run 并推进下一次时间。
- Schedule 保存按固定 RecipeSpec 校验的 typed policy：普通值为 literal，date/datetime 可绑定计划运行日及受限天数偏移。入队时按 Schedule timezone 解析并冻结实际值；后续编辑 Schedule 不反改旧 Run。
- 服务停机跨过多个周期时，一个 Schedule 最多创建一个补偿 Run，再把下一次推进到当前时刻之后，避免无界积压。
- 显式停用期间不形成补偿任务；重新启用时按启用时刻重新计算严格晚于当前时间的下一次。
- v1 不删除 Schedule，只允许更新名称、表达式、timezone 和 enable/disable，以保留 Run 外键与审计上下文。

### Run、lease 与制品契约

```text
queued → running → succeeded | failed | needs_review | cancelled
   └──────────────→ cancelled
running ── retryable failure / expired lease, attempts < 3 ──→ queued
```

- `(schedule_id, scheduled_for)` 唯一；重复 tick 只能得到一个逻辑 Run，两个独立 repository/SQLite 连接在 `BEGIN IMMEDIATE` 写锁下真实争抢同一到期 Schedule 时也只能入队一次。
- 队列状态使用新的 Automation Run enum；Recipe Core 的 artifact status 只扩展必要终态，不能承载 queued/running。
- 逻辑 `run_id` 对外稳定；每次 Executor 尝试使用新的 artifact run id。Run row 保存可校验的最终 artifact reference、binding hash、尝试次数、安全错误、本次不可变 typed values，以及仅供 Worker 恢复使用的 active/cleanup attempt id；内部恢复字段不进入公共 API。参数只允许非敏感业务值，凭据、连接参数和绝对路径仍不得进入 SQLite。
- claim 写入 lease owner + 随机 fencing token；renew/finish/fail 都校验 owner、token 和未过期时间。过期 Worker 即使晚到，也不能覆盖新尝试结果。
- queued 取消直接终结；running 取消只写请求，由 Worker 在步骤边界确认并产出 cancelled manifest。
- repository 强制最多 3 次总尝试（初次 + 2 次重试）和 `available_at` 延迟领取，但只接受调用方给出的显式 retryable 决定；Worker 已只把现有 connector classifier 的 `retry=true` 与明确识别的 SQLite locked/busy 接入该决定。schema drift、签名、scope、参数、代码和输出校验永不重试。
- `succeeded` / `needs_review` 必须保存完整且安全的相对 artifact reference；逻辑 Run id 不得复用为 attempt artifact id。`failed` / `needs_review` 必须保存成对的安全错误 code/message，`succeeded` / `cancelled` 不得夹带错误。
- Scheduled Run 与持久化 manual Run 都固定 RecipeVersion，但可为该版本已编译的 typed slots 提供值。manual enqueue 在服务端校验并补全默认值；Schedule policy 在每个计划时刻解析。两条路径都先把完整实际值写入 Run，再由 Worker 执行，重试不重新求值。

### M3-B 实施切片

1. [x] **B1 迁移所有权**：唯一 DB helper、当前 v1 → v2 → v3 → v4 → v5、重复初始化、失败回滚、未来版本拒绝；未注册 route。
2. [x] **B2 Schedule repository**：列表/编辑、数值 Cron、timezone/DST、停机补偿、重复 tick 幂等，以及同事务入队并推进 `next_run_at` 已完成。
3. [x] **B3 Run repository**：合法状态转换、claim/fencing/renew、取消、延迟/有限重试和过期 lease 恢复已完成，全部使用注入时钟且无真实 sleep。
4. [x] **B4 单次 tick/execute**：`scheduler.tick()` 与 `worker.run_once()` 均已完成；Worker 复用显式 Workspace/connector opener 和 `RecipeExecutor`，完成 claim → execute → finish/retry、独立 attempt artifact、安全错误分类、步骤边界续租/取消和 Needs Review。
5. [x] **C1 常驻执行边界**：长步骤 heartbeat、正式 `data_formulator_worker`、可中断 Scheduler/Worker 循环、安全启动/退出和跨 runtime 持久化 Run 恢复已完成。
6. [x] **D1 API/UI 闭环**：Schedule/Run scoped API、持久化 manual enqueue/cancel、校验后 artifact 查询、Schedule 设置、Runs Inbox 与 Needs Review 回跳已完成。

当前实现没有引入 Cron 第三方依赖、Flask 后台线程或并发 2。Cron/timezone/DST、停机补偿、事务回滚、lease/fencing、步骤边界取消、长步骤续租、分类重试、强杀恢复和 attempt 清理均有合同测试；one-shot 原语仍可独立测试，正式常驻生命周期只由独立 `data_formulator_worker` 进程负责。Web route 只做 scoped 管理与查询，不承担 Scheduler/Worker 循环。

### M3-C 常驻 Worker 契约

- 每个 claim 后先同步续租并确认 fencing，再启动该 attempt 专属的 daemon heartbeat；默认 lease 30 秒、heartbeat 10 秒。步骤仍同步执行，但 heartbeat 定时使用独立 SQLite 连接续租，因此单个 load/transform/chart 超过原始 lease 也不会被错误重领。
- heartbeat 观察到取消后继续续租，直到 Executor 到达步骤边界并写 cancelled artifact；heartbeat 失去 token、续租异常或无法停止时统一转成 `AutomationWorkerLeaseLostError`，旧 Worker 不提交逻辑 Run 终态。Worker 在 Executor 创建目录前持久化 active attempt id；lease 过期时 repository 把它转成 cleanup id，并在清理完成前阻止下一次 claim。无 manifest attempt 被隔离删除并留下 retired tombstone，已有 manifest 的孤立 attempt 保留且不能误接为成功结果。
- `AutomationRuntime` 每个周期执行 `scheduler.tick()`，再最多调用一次 `worker.run_once()`；默认每秒轮询，等待可由 stop event 中断。循环只对白名单 SQLite locked/busy 继续下一周期，其他异常安全退出。
- wheel 新增 `data_formulator_worker = data_formulator.automation.cli:main`。入口加载与 Web 相同的 `.env` 位置，并在创建数据库、Workspace opener 或 connector registry 前验证 `AUTOMATION_ENABLED=true`、稳定签名和 local Workspace；配置与意外错误都不回显原始异常。
- `--once` 只执行一个 Scheduler/Worker 周期；默认模式安装 SIGINT/SIGTERM handler，在当前同步周期结束后退出。Worker 不监听端口，也不伪造 Flask request。
- 跨 runtime 合同先由一个 Runtime tick 把 due Schedule 写成 queued Run，再重新构造全部 repository、Scheduler 和 Worker，第二个 Runtime 能从同一 data home 执行该 Run。Web/桌面应用当前不会自动拉起或监督 Worker。

### M3-D API 与界面契约

- `AutomationService` 要求 Automation/Recipe repository 指向同一绝对数据库，并在创建 Schedule 或持久化 manual Run 前验证稳定签名、Published RecipeVersion、typed values/policy 和默认值完整性；失败时不创建 Schedule/Run 行。
- `/api/automation` 已提供 Schedule list/create/update/enable/disable，Run manual enqueue/list/get/cancel、manifest/events/result 只读查询、成功 Run 最终输出表的 sample/download，以及显式 `POST /runs/<id>/analysis`。所有访问由当前 identity + durable local Workspace 限定，feature flag 在存储初始化前失败关闭。
- 服务端独占首个 `next_run_at`、manual `scheduled_for`/`available_at` 和逻辑 Run id；写接口只允许 manual `parameters` 或 Schedule `parameter_policy` 进入 RecipeSpec 已声明 slot，严格拒绝未知参数、类型不匹配、越界偏移、过大 canonical JSON、额外执行字段和 malformed JSON。公共 Run 响应返回本次非敏感冻结值，但不返回 lease owner、fencing token 或 lease expiry。
- manifest/events/result 及输出表 sample/download 都从逻辑 Run 解析 attempt reference，并通过 `RecipeRunArtifactStore.load()` 校验 scope、安全相对路径、manifest hash、descriptor 与全部文件 hash；sample/download 只允许成功 Run 在 Recipe 中声明的最终输出表。active Run、中间表、缺失或损坏制品失败关闭，不返回未经验证的内容。
- 单一 `/automation` 页面已接每日时间 → Cron、固定版本 Schedule 创建/编辑/启停、手动/定时 typed values，以及持久化运行记录的状态过滤、刷新、取消、Needs Review 回跳和经校验的运行详情。成功 Run 的主动作是“查看结果”，直接读取这一次 Run 的不可变制品，并复用现有图表、表格、分页、排序、筛选、搜索和 CSV 下载；报告头只保留一行状态/时间/触发方式/冻结参数，每个输出只显示一条说明，重复目标、只读提示和分析步骤不再占据主阅读流。失败/Needs Review 才以步骤证据和技术信息为主。默认定时表单只显示名称、运行时间和该 Recipe 的值；自定义 Cron 和 timezone 仅在“更多设置”中出现。
- 报告上的“AI 解读”只在用户点击后调用当前所选模型；无模型时禁用并说明原因。后端先用正常 result 路径验证 Run、manifest、descriptor 和文件 hash，再发送最多 60,000 字节的不可变目标/参数/步骤、冻结值和最多 10 个输出的限量样本。模型只能返回摘要、1～3 条带证据发现和可选 caveat；非法结构失败关闭，Run 仍保持 `succeeded`。前端解读是易失状态，没有聊天、追问、持久化、Replay 或新 Data Thread。
- Published RecipeVersion 的“运行一次”在主操作旁展示可编辑 typed values，并随 `version_id` 一起持久化入队。Schedule 各自保存 fixed/run-relative values；运行记录和结果页都显示 Run 真正冻结的值。Workspace/版本快速切换时旧响应会被丢弃。

### M3-D 界面体验收口（2026-08-19）

- 基于真实 Automation 页面、已有 Movies Recipe、定时记录和 `needs_review` Run 截图审查，而不是只看组件代码。主任务收口为“运行一次、设置定时、查看结果”。
- 中文导航与页名统一为“自动化”；“调度”“运行收件箱”“运行审计”等工程术语分别改为“定时运行”“运行记录”“运行详情”。首屏不再显示 Recipe hash、Run ID、attempt 次数、Manifest、artifact 文件名或内部错误码。
- 定时运行改为按需打开表单，默认只填写名称和时间；普通每日 Cron 显示为“每天 HH:mm”，自定义 Cron 与时区下沉到更多设置。暂停的定时不再展示误导性的“下次运行”。
- 运行记录改为紧凑分隔列表；Schema drift 在主流程中解释为数据源结构变化并给出“更新配方”动作。运行详情先展示结果、触发方式和步骤，原始错误、Run ID 与输出文件统一收进“技术信息”。
- Recipe 参数、输入、步骤、hash 和归档动作统一收进“配方详情”；草稿默认展开以便填写参数，已发布版本默认折叠。dry run 结果同样只先展示验证结论和步骤，输出路径与指纹按需查看。
- 用户需要改的运行值不再藏在“配方详情”：Published 版本把本次手动值放在“运行一次”之前，定时任务在表单中保存自己的值，运行记录直接摘要本次冻结值。机器 parameter id 会转成可读名称，Schedule 启用态明确显示“已启用”而不是误导性的“运行中”。
- 保持现有 MUI、i18next、API、状态机和持久化模型不变；没有引入新设计系统、前端状态框架或后端行为。

### M3-D 运行结果边界与真实浏览器复核（2026-08-20）

- 先在原有 Data Thread 中逐步打开 Workflow overview、输出表格和图表，确认原产品的结果形式是 Vega 图表与可查询/下载的数据表。Automation 只复用这套呈现语言和现有渲染组件，不复制聊天、步骤编辑、字段拖拽或重放入口。
- Workflow Replay 的合同不变：它把历史工作流交给 Agent 做语义重做，允许模型重新理解上下文，结果可以变化。Automation Run 则执行固定 Published RecipeVersion，正常路径禁止 LLM；“查看结果”只读取该次 Run 已保存的不可变制品，不重新执行 Recipe。
- 结果快照不会把表复制进活动 Workspace，不创建 Data Thread，不写 Redux 会话，也不调用 Agent/Replay。若以后需要“继续分析”，必须是明确的另一个复制动作，并向用户说明会创建新会话；不能让“查看结果”暗中变成重放。
- 成功 Run 使用 `VegaChartRenderer`、`FreeDataViewFC` 与 `SelectableDataGrid` 展示图表和表格；失败或 Needs Review 保留步骤证据、错误和技术信息。后端每次读取重新校验 scope、路径、manifest 与文件 hash，只向 sample/download 暴露 Recipe 声明的最终输出，拒绝中间表。
- 本机浏览器用固定端口 Web/Vite 和独立 Worker 新建 3,201 行 Movies 的 `load → transform → chart` Published RecipeVersion，并由定时 Schedule 产生一次成功 Run。结果页显示 12 个类型、2,926 部有类型电影、Drama 789 部和全球票房 `40,476,168,953`；表格搜索 `Drama` 得到 1 行，CSV 下载可用。Run 执行期间把 LLM 调用替换为直接抛错，运行仍成功，证明结果来自确定性 Recipe 而非 Agent。
- 视觉对照证据保存在 Codex audit 目录：原工作流 overview/table/chart、Automation Run result，以及同视口组合对照图。浏览器验收仍是人工复核，不冒充仓库默认 E2E。

### M3-D 报告瘦身与显式 AI 解读（2026-08-20）

- 原 Workflow 的优势不是“把同一结果再跑一遍”，而是保留分析目标、运行参数和有序处理步骤；原 Report 的优势是只读、连续的窄栏阅读流，可以把多个最终图表/表格放在同一份结果中。Automation 把这套结构作为稳定上下文，但不把全部结构性文本都塞给用户看，也不复制 Agent 会话或报告编辑器。
- `GET /runs/<id>/result` 在既有 artifact 完整性校验后，从该 Run 固定的不可变 RecipeSpec 返回稳定 `report` 投影。结果页将状态、时间、触发方式和冻结参数合并成一行，删除重复的配方说明、只读解释、二级标题与可见分析步骤；每个最终输出只保留 `display_instruction` 或 `subtitle` 中的一条。图表直接展示，支撑数据默认折叠；仅有表格的最终输出仍直接展示，并继续复用既有查询、筛选和 CSV 下载。
- 新增 `POST /runs/<id>/analysis` 作为明确的报告后处理动作。它先调用 `load_run_result()` 验证不可变制品，再从目标、参数定义、步骤、冻结值和已保存结果样本构造有上限上下文；复用现有 LiteLLM Client 与 `workflow_distill` reasoning profile，严格要求 `summary + 1..3 insights{finding,evidence} + caveat`，不接受自由聊天或未经证据支持的延伸。
- 前端只提供一个次要“AI 解读”按钮和短结果区；切换 Run/Workspace/模型时丢弃旧响应，生成区使用 `aria-live`，并明确告知会把已保存的结果样本发送给当前模型。解读不重跑 Recipe、不修改参数、不调用 Replay、不创建 Workspace/Data Thread、不写 Run/Report artifact，失败也不改变成功状态。

### M3-D typed values 与结果差异闭环（2026-08-20）

- `RecipeCompiler` 从持久化 load 血缘发现 filter value / limit，并从不可变 transform 血缘发现已经声明和验证的 scalar slot。参数 id 和固定 binding 由 Compiler 确定性生成，聊天文本和 Redux 状态不参与推断；Save as Recipe 当前默认不选候选，用户手动选择或让 AI 推荐少量有意义的现有候选。
- schema v5 为 Schedule 保存 parameter policy、为 Run 保存不可变实际值。manual 值、literal policy 和随运行日解析的 date/datetime 都通过同一个 Recipe binding 类型校验；值 canonical JSON 上限为 64 KiB，日期偏移限制在 ±3660 天。Schedule 编辑不会改变已经 queued 的 Run。
- Worker 只读取 Run snapshot，不重新读取或解析 Schedule；同一 Run 的重试保持相同值。正常执行仍禁止 LLM、TrustGraph、Replay 和代码生成。凭据与连接参数不属于参数体系，也不会进入 Schedule/Run JSON。
- DataOperation 在 connector 返回过滤列时本地再次执行 source filters，再恢复原始 projection 和 limit，修复 `SampleDatasetsLoader` 等忽略 filter pushdown 时参数看似变化、结果却不变的问题。新 Recipe 使用 logical schema fingerprint，行数/Parquet metadata 变化不再误报 schema drift，字段或类型变化仍进入 `needs_review`；旧完整 schema hash 继续兼容。
- 默认集成用仓库 3,201 行 Movies、真实 loopback HTTP、正式 `SampleDatasetsLoader`、Artifact Lineage、dry run、publish 和生产 `AutomationWorker.run_once()` 跑同一 Published RecipeVersion 两次：Drama 为 789 部、全球票房 `40,476,168,953`；Comedy 为 675 部、全球票房 `50,384,049,282`。两次 Run 的冻结值、binding hash 和输出均不同，且 LLM 调用被替换为直接抛错仍成功。
- 本机浏览器在真实 `/automation` 页面复核参数候选产生的版本、手动值、Schedule 固定值、运行记录摘要和结果弹窗。结果首屏同时显示 `Major Genre: Comedy`、单条图表和实际表格行；同视口前后对照保存在 `automation-schedule-before-after.png` 与 `automation-result-before-after.png`。这仍是人工产品证据，不冒充默认浏览器 E2E。

### Save as Recipe 参数创作优化（2026-08-20）

- 参数绑定的真相源仍是 `RecipeCompiler.parameter_candidates()`。保存对话框里的 AI 不能读取聊天后自行生成 slot，也不能改 candidate 的 parameter id、类型、step/target/filter index/slot name；Compiler 只接受已知 candidate id 的用户确认配置。Analyst 在更早的 transform 创作阶段声明 slot 是另一条受服务端验证和 Artifact Lineage 约束的路径。
- 保存对话框展示 Compiler 候选但默认不选；推荐项置顶，其他可调整值折叠供手动选择。用户选择后可保持当前 typed 默认值，或切换为“每次运行填写”；后者编译为 required 且无 default，因此 dry run、手动 Run 和 Schedule 都必须显式提供值。
- “推荐运行参数”是可选按钮，不是保存前置条件。它使用当前所选模型，复用 `buildLeafEvents`、`buildSessionWorkflowContext` 和 `WorkflowDistillAgent` 的上下文摘要思路，只推荐少量关键候选、可读名称、短说明及 `ask|keep`。无模型时按钮禁用并解释原因；模型失败时显示非阻断警告，用户仍可直接保存。
- 后端 `/api/recipes/parameter-suggestions` 重新从当前 durable Artifact Lineage 取得候选；模型只返回推荐子集与可选未匹配语义。服务端对 id 去重并取 candidate 交集，忽略未知/重复项，对非关键元数据使用 candidate 默认文案；只有无法解析顶层响应时失败。原始模型输出不进入 API 错误或日志。
- RecipeSpec 的 parameter 增加可选 `description`；空说明不进入 canonical JSON，因而旧 Recipe round-trip 和旧版本读取保持兼容。运行与定时表单直接显示说明；`ask`/`keep` 只影响默认值，不改变 binding 或执行步骤。
- 3,201 行 Movies 集成已改用确认配置编译 `Major Genre`：显示名为 `Movie genre`、带说明、模式为 `ask`。dry run 显式传入 Drama；随后同一版本分别运行 Drama/Comedy，保存结果仍不同，Worker 内 LLM 调用仍被强制抛错证明执行路径没有被助手污染。
- 这项跨越 Save as Recipe UI、Recipe route/spec/compiler 和 Automation 消费端的公共契约应在提交拆分时优先形成可回迁 Recipe Core 的基础提交；Automation 侧只消费带说明、默认策略和固定 transform slot binding 的不可变 RecipeSpec。

### Save as Recipe 参数语义优先收口（2026-08-20，已实现）

上一版已经证明 typed values 能真实改变 Movies 的筛选和 Top N 结果，但保存体验的顺序不对：Compiler 先给候选、UI 默认全部选中，模型再被要求逐项整理。这样会把“技术上能替换的值”误当成“用户每次运行真正想改的值”，也无法清楚解释没有有用候选时该怎么办。当前实现已按下述三步收口。

收口后的路径只保留三步：

1. **理解分析**：一次现有模型调用先阅读与原 Workflow Distill 相同的目标、用户请求、表格和图表上下文，只判断 0～4 个会实质改变结果的运行选择。没有值得暴露的参数也是正常结果。
2. **对齐绑定**：同一请求携带 Compiler candidate 摘要供模型引用；服务端重新读取 durable candidates，只对返回 id 去重并取交集。AI 不需要为每个候选返回记录，也不能让候选外的值进入 Recipe。
3. **用户确认**：默认不选中任何 candidate；AI 只预选匹配成功的推荐，其他可调整值折叠供手动选择。用户决定 `ask` 或 `keep` 后，现有 Compiler 按当前 typed binding 生成 RecipeSpec。

如果模型识别出重要选择但当前血缘没有对应 slot，只在保存对话框显示一句“当前还不能直接调整，可回到分析让 Analyst 生成可调版本”。该提示不持久化，不建立 `ParameterIntent` 表或状态枚举，也不从保存对话框自动改写 transform。无模型、调用失败、没有推荐或没有候选时，用户都可以直接保存固定 Recipe。

这次收口同时删掉不产生用户价值的防御性复杂度：建议响应不再要求完整覆盖 candidate，不因未知/重复建议 id 让整次调用失败，也不为未匹配项建立独立生命周期。严格边界只保留在最终 compile 和执行处：candidate id、类型、binding 与运行值仍由 Compiler/RecipeSpec 校验；正常 Run、Schedule 和 Worker 仍不调用模型。

界面只需要三个变化：按钮改为“推荐运行参数”，推荐项置顶，未推荐候选放入“其他可调整值”；不增加参数向导、证据详情、匹配状态表或自动修复按钮。

验收使用真实 Workflow 上下文、受控模型响应和现有 Movies 数据：真实 Compiler 从 Lineage 取得 `top_n` candidate，推荐子集再编译为 integer typed slot；同一 Published RecipeVersion 由生产 Worker 分别以 3/7 运行并得到 3/7 行不同结果，Worker 内禁止 LLM 的回归继续通过。另有零候选但存在重要 Workflow 选择、空推荐、未知/重复 id、模型失败和固定 Recipe 保存回归；受控响应不冒充真实 provider 产品验收。

2026-08-21 又补齐复杂联动：真实两层 Movies 血缘先产生 `start_year/min_movies/min_roi/top_directors` 四个 typed candidates，Workflow 语义明确把“两部电影”定义为固定质量门槛，只让起始年份、最低 ROI 和每类导演数按 Run 调整，并提出当前无 slot 的“最低 IMDb 评分”。受控模型边界返回三个已知 candidate 和一个 unmatched 提示；Compiler 只生成三个 Recipe 输入，未推荐的 `min_movies` 继续使用 Artifact 默认值 `2`。该版本完成 dry run、publish、一次定时 Run 和一次手动 Run，分别得到 22/18 行，并逐表匹配独立中间/最终 Pandas 基线；执行期继续强制禁止 LLM。当前可见模型列表为空，因此这项测试证明复杂推荐后的产品链路，不冒充 live provider 的语义质量验收。

### Transform typed slot 与真实结果闭环（2026-08-20）

- `visualize` 工具可选声明最多 4 个 `string | integer | number | boolean | date | datetime` scalar slot。当前结果必须用声明中的默认值生成，代码只能通过字面量 `params["slot_id"]` 读取；空声明保持旧 Artifact canonical bytes 和 hash 不变。
- [`transform_parameters.py`](../../../py-src/data_formulator/recipes/transform_parameters.py)规范化并限额声明，要求每个 slot 被代码使用，并只允许比较/算术及 Top N、窗口、区间、类别、分位数等数据值位置。Python/SQL 动态文本、字符串插值、文件路径、动态表/列/对象/callable 和未批准的调用参数在记录、编译、交互刷新和执行前失败关闭；简单 scalar alias 同样被追踪，不能绕过文件/字段边界。
- Slot 定义、类型、默认值和说明与签名代码一起进入 immutable transform Artifact，artifact id 覆盖该声明。Compiler 产生 `transform_parameter` binding 和固定 `slot_name`；binder 只写独立 `parameter_values`，Executor 合并 immutable default 与 Run override 后通过 Sandbox `parameters=` 注入 `params`，从不修改代码字符串。
- 原有派生表交互刷新继续复用同一签名代码，并携带 Artifact 创作时的 slot/default；它不会调用 LLM。前端把 slot 声明保存在既有 `derive` 信息中，没有建立平行刷新或执行系统。
- 默认产品数据测试用 3,201 行 Movies 汇总的 `top_n` slot 编译同一 Published RecipeVersion，并由生产 `AutomationWorker` 分别运行 3 和 7：最终结果分别为 3/7 行，前三行一致但累计电影数、binding hash 和制品内容不同；Worker 内任何 LLM 调用都被替换为抛错。这直接证明参数改变中间处理和最终结果，不是反复查看同一快照。

### 复杂真实数据处理回归（2026-08-21）

- 默认产品集成继续从仓库 3,201 行、16 列 Movies 数据经 loopback HTTP 和正式 `SampleDatasetsLoader` 加载，不使用两行 DataFrame 或伪造成功结果。新增 Recipe 的真实拓扑为 `load → director_metrics transform → ranked_directors transform → chart`。
- 第一层 Transform 按上映年份、导演和电影类型清洗数据，计算作品数、制作成本、全球票房、利润、平均 IMDB 评分与 ROI；第二层按 ROI 过滤，再在每个电影类型内按组合利润排名。`start_year`、`min_movies`、`min_roi`、`top_directors` 四个 typed slot 分布在两层不可变签名代码中，Compiler 固定各自 step/slot binding。
- 同一 Published RecipeVersion 运行三种业务口径：近期成熟导演得到 22 行、覆盖 72 部电影、利润 `20,035,909,513`；宽口径得到 56 行、157 部电影、利润 `44,053,344,636`；高 ROI 精选得到 18 行、69 部电影、利润 `21,326,749,404`。第一种由 Schedule literal policy 入队，后两种由 manual Run 入队；三次 binding hash 各不相同。
- 测试为每组参数用独立 Pandas 路径重算中间 `director_metrics` 和最终 `ranked_directors`，再逐 DataFrame、行数、电影数与利润核对 Worker 制品，并断言八条 `load/transform/transform/chart` 开始/成功事件。Worker 内任何 LLM 调用都被替换为抛错。
- 随后保持 schema、RecipeVersion 和宽口径参数不变，把真实 Avatar 记录的全球票房增加 `123,456,789` 并再次从 HTTP 刷新。新 Run 的 binding hash 与原宽口径相同，但 James Cameron 组合利润和最终总利润精确增加同一数值；旧 Run 的不可变 Parquet 仍与刷新前基线一致。这覆盖了“参数不变但源数据更新”的另一种真实自动化价值。
- 另一个默认产品测试把同一复杂血缘交给参数推荐边界：四个 Compiler candidates 中只把 `start_year/min_roi/top_directors` 编译为运行输入，`min_movies=2` 固定，缺少 typed slot 的“最低 IMDb 评分”只作为未匹配提示。推荐后的 Published RecipeVersion 由 Schedule 和 manual Run 跑出 22/18 行，逐表核对 209/337 个中间导演组合、最终类型数、电影数与利润，并证明未推荐候选没有静默变成第四个输入。

### M3-D 产品端到端验收（2026-08-19）

- 使用固定 `automation` 实例启动真实 Web（5570）、Vite（5176）和独立 `data_formulator_worker`，三者共享 `D:\projects\dfm-runtime\automation`，未启动 Docker，也未把 Worker 循环放进 Flask。
- 在真实 `local:lenovo` identity 和 durable local Workspace 中，通过 Artifact Lineage → Recipe 编译 → dry run → publish 创建基于内置 Movies sample dataset 的 Published RecipeVersion。验收同时确认：`locallenovo` 只是 identity 的目录安全名，业务 scope 必须始终保留 namespaced identity `local:lenovo`。
- 浏览器从 Automation 页面排入 manual Run；独立 Worker 完成执行后，Runs Inbox 展示 `succeeded`，审计对话框通过后端校验读取 manifest、`events.jsonl` 和隔离 Workspace 文件清单。
- 浏览器用 `51 19 * * *`、`Asia/Shanghai` 创建固定版本 Schedule 后关闭页面；独立 Worker 在 `2026-08-19 19:51:00` 到期时仍创建并完成 scheduled Run。重新打开页面后，Runs Inbox 能反查该 Run 及两条 load 事件；测试 Schedule 随后已停用。
- Worker 停止期间入队的 Run 保持 `queued`、尝试次数为 0；重新启动独立 Worker 后被领取并成功完成。另一个 queued Run 经 UI 取消后保持 `cancelled`，Worker 再次启动也未执行它。
- 使用受控 drift connector opener 但保持同一生产 `AutomationWorker.run_once()`、RecipeExecutor、repository 和 artifact store 路径，把 Movies schema 改为不兼容表结构；Run 一次尝试后进入 `needs_review`，保存 `schema_drift` 安全错误、可校验 manifest 和 `started → needs_review` 事件，UI 同时显示人工检查引导与 Recipe 回跳。
- 上述记录是一次本机人工产品验收，不是默认测试套件；保存下来的 Recipe/Run 只有 `load` 步骤和两条 load 事件，因此它证明了浏览器、双进程和页面关闭场景，但不能单独证明 `load → transform → chart` 三步执行。

### M4 强杀与 attempt 制品恢复（2026-08-19）

- `AutomationDatabase` 升级到 schema v4，新增 `active_attempt_run_id` 与 `cleanup_attempt_run_id`。Worker 只有持有未过期 owner/token 时才能登记物理 attempt；过期恢复原子转移清理责任，claim 查询拒绝 cleanup 未完成的 Run。
- `RecipeRunArtifactStore.resolve_abandoned_attempt()` 只接受精确 run id 和当前 Run 行声明的 Workspace。无 manifest 目录先原子改名到隔离路径，再写 retired tombstone 并删除；目录尚不存在时同样写 tombstone，关闭旧进程迟到创建的竞态。manifest 已存在时保留不可变目录，不生成引用，也不把它挂到后续逻辑 Run。
- 自动化验收启动真实子进程，让 Worker 完成 claim、attempt 登记并进入阻塞 load 后调用进程终止；测试推进 lease 时钟后由新 Worker 回收无 manifest 目录、领取同一逻辑 Run 的第二次尝试并成功完成。repository、artifact store 和 fencing 的聚焦回归同时覆盖清理门禁、compare-and-set 和旧 token 失效。

### M4 可重复数据、竞争与迁移验收（2026-08-19）

- 新增默认执行的 `test_automation_product_integration.py`：读取仓库 `public/df_movies.json` 的 3,201 行、16 列真实样例，通过本机 loopback HTTP 和正式 `SampleDatasetsLoader`/`ExplicitConnectorOpener` 下载，而不是在测试中捏造成功响应或两行 DataFrame。
- 测试从真实 Connector load 建立 Artifact Lineage，确定性编译 `load → transform → chart`，执行 dry run、publish、Schedule tick，并清空 loader cache、重建 repository/opener/Worker 后完成 Scheduled Run。断言六条步骤事件、12 个类型、2,926 部有类型电影、Drama 789 部和汇总票房 `40,476,168,953`，同时拦截任何 LLM 调用。
- 同一固定 Published RecipeVersion 随后从 HTTP 端点取得不兼容 schema；测试确认没有复用旧缓存、只尝试一次、以 `schema_drift` 进入 `needs_review`，且只留下 `load started → needs_review` 事件。
- Scheduler 回归现在使用两个独立 `AutomationRepository` 和两个线程：第一个连接持有真实 SQLite `BEGIN IMMEDIATE` 写锁，第二个连接在同一到期 Schedule 上阻塞；释放后一个 tick 得到 1 个 Run、另一个得到 0 个，数据库最终仍只有 1 个逻辑 Run。
- migration 回归覆盖包含 Published RecipeVersion、enabled Schedule 和 queued Run 的真实 schema v3 → v4 → v5，以及带 attempt 字段的 v4 → v5；确认业务行、状态和排期不丢失，新 policy/value JSON 默认为 `{}`，queued Run snapshot 建立后不可修改。浏览器验收目前仍是人工记录；仓库尚未建立默认运行的浏览器自动化，也没有把 loopback 端点冒充用户的真实外部服务。

## M3/M4 实施顺序

1. [x] Recipe Core 修复稳定签名配置回归，Automation rebase 到新基线并完成三项基础验证。
2. [x] 本分支完成“自动化项目 → Recipe/配方”术语收口及聚焦前端测试。
3. [x] 完成 M3-B Schedule/Run repository 和单次 `scheduler.tick()`。
4. [x] 实现 `worker.run_once()`，接入白名单错误分类、步骤边界续租/取消、固定版本/Run value snapshot 和 Web/Worker 数据根一致性。
5. [x] 增加覆盖长步骤的 lease heartbeat、正式 `data_formulator_worker` 入口和 Scheduler/Worker 本机进程生命周期。
6. [x] 增加 Schedule/Run API、持久化 manual enqueue/cancel、校验后 artifact/result 查询、Schedule UI、Runs Inbox、成功结果快照和 Needs Review 处置。
7. [x] 使用真实 Web + 独立 Worker 完成页面关闭、Worker 重启恢复、取消、schema drift 和 UI 处置的一次性人工产品验收；其持久制品只有 `load` 步骤，不把它写成三步自动回归。
8. [x] 完成运行中 Worker 强杀后的 lease 恢复、无 manifest attempt 定点回收、迟到创建 tombstone 和第二次尝试验收。
9. [x] 增加 3,201 行 Movies 的三步默认自动化集成、两个 SQLite 连接真实竞争和带业务行的 v3/v4 → v5 migration 回归。
10. [x] 审核原 Workflow 输出形式，补齐成功 Run 的只读图表/表格结果、完整 CSV 下载和真实三步浏览器复核；保持 Workflow Replay 与 Automation 的语义边界。
11. [x] 增加安全参数候选、手动/定时 typed values、Run snapshot 与结果值展示；用同一 Movies Recipe 的 Drama/Comedy 实际结果证明值变化会改变输出。
12. [x] 增加可选 AI 参数整理、Workflow 上下文复用、candidate id 失败关闭、`ask/keep` 编译语义和运行表单说明；保持执行期无 LLM。
13. [x] 增加 Analyst transform scalar slot、受控 AST/typed binding/独立 Sandbox 注入、交互刷新传递和 Movies Top 3/7 真实结果差异；不开放任意参数编辑器或源码替换。
14. [x] 把成功 Run 结果整理为只读分析报告，复用不可变 RecipeVersion 的目标、参数与步骤，连续显示全部最终输出，图表优先且支撑数据按需展开。
15. [x] 精简报告冗余文案与元信息层级；增加显式一次性 AI 解读、完整性校验后的限量上下文、严格结构化输出和易失 UI 状态，保持正常 Run/Worker 无 LLM。
16. [x] 收口 Save as Recipe 参数体验：Workflow 语义优先、AI 只返回推荐子集、candidate 默认不选、简单交集与未匹配提示；不新增状态机或自动改代码流程。
17. [x] 增加四参数、两层 Transform、定时/手动多口径及 schema-compatible 源数据刷新的复杂 Movies 产品回归，并独立核对中间与最终制品。
18. [x] 增加复杂 Movies 的 AI 参数推荐联动：四候选语义选三、固定未推荐默认值、未匹配提示、重新编译、dry run、发布及定时/手动真实结果闭环。

## 开发记录

| 日期 | 阶段 | 实质变更 | 验证 | 提交 |
| --- | --- | --- | --- | --- |
| 2026-08-18 | 准备 | 确定 SQLite、单 Worker、lease、状态机和 Recipe Core 依赖边界 | 设计审查 | `docs: establish project plan` |
| 2026-08-18 | 准备 | 增加仓库级 Agent 指南并记录分支创建前置条件 | 文档链接与范围核对 | `docs: add repository agent guide` |
| 2026-08-18 | 准备 | Agent 指南中文化，工程记录迁入 Feature 独立目录 | 文档链接、目录和旧路径检查 | `docs: localize agent guide and organize feature records` |
| 2026-08-18 | 准备 | 补充上游文档检索规则和无 Docker 开发约束 | 上游指南入口、文档链接和范围检查 | `docs: preserve upstream guidance and prohibit docker` |
| 2026-08-18 | 准备 | 预留多 Worktree 本机实例和资源隔离约定 | 端口、数据目录、Worker/SQLite 边界和文档链接检查 | `docs: define multi-worktree runtime isolation` |
| 2026-08-18 | M3-A 规划 | 确定左侧 Automation 入口、项目/版本信息架构、Recipe Core 复用边界和非范围 | Markdown 结构、外部参考链接、diff 范围检查 | `docs: plan lightweight automation workbench` |
| 2026-08-19 | M3-A 实现 | 增加响应式全局左栏、Automation 项目/版本管理页、旧路由兼容、feature flag 和中英文文案 | 前端 49 files / 400 tests；后端 2220 passed；生产构建；桌面与 600px 窄屏浏览器检查 | `feat: add lightweight automation workbench` |
| 2026-08-19 | M3-A 反馈完善 | 增加当前会话最近运行结果面板，展示状态、Run ID、步骤、耗时、输出位置、最终产物与错误，不扩展持久化 Runs Inbox | Automation 聚焦测试、前端全量测试、生产构建 | `feat: show latest automation run result` |
| 2026-08-18 | M3-A 导航优化 | 移除新增的 `App / Automation` 外层左栏，将 Automation 接入原有工作区 rail，并恢复原有 `About / App` 顶部导航；会话、知识和 Workflow Replay 概念不变 | 前端 49 files / 402 tests；后端 2220 passed、13 skipped、1 deselected、1 xfailed；生产构建；真实页面导航、返回原面板、加载数据入口与控制台检查 | `fix: integrate automation into workspace navigation` |
| 2026-08-18 | M3-A UI 收口 | 删除 Automation 页头残留的“打开应用”按钮，并移除空状态中对 App 层级的表述 | Automation 聚焦测试、生产构建、真实页面检查 | `fix: remove redundant automation app action` |
| 2026-08-19 | M3-A 基线同步 | 将 5 个既有 Automation 提交线性 rebase 到 Recipe Core M2-D；解决页面/测试重叠，保留详细运行结果并继承防串请求、URL 版本和刷新失败语义 | Automation 页面 7 passed；前端 49 files / 405 tests；后端 2239 passed、16 skipped、1 xfailed；生产构建和相关 ESLint 通过 | `fix: align automation with recipe core` |
| 2026-08-19 | M3-B 开发准备 | 核对分支拓扑、单一 Automation 入口、schema v2 迁移冲突和 Worker/Executor 复用点；在 Recipe 关闭签名 P0，Automation 线性同步新基线并把 Project 术语收口为 Recipe | Recipe 聚焦 67 passed、1 skipped；全量后端 2251 passed、16 skipped、1 xfailed；Recipe 前端 399 passed、生产构建通过；Automation 聚焦前端 11 passed；文档检查通过 | `fix: prepare automation persistence` |
| 2026-08-19 | M3-B1 持久化契约 | 抽取唯一 `AutomationDatabase` migration owner 并升级 schema v3；增加固定 Published RecipeVersion 的 Schedule、归档保护、独立 Automation Run 状态/字段及按计划时刻幂等 queued 入队；未接 route、线程或 Worker | 聚焦 22 passed；Recipe/Automation 119 passed、2 skipped；全量后端 2262 passed、16 skipped、1 xfailed；前端 49 files / 405 tests；生产构建和 wheel 构建通过 | `9f3056ef feat: establish automation persistence contracts` |
| 2026-08-19 | M3-B2/B3 调度与状态机 | 增加数值五段 Cron、timezone/DST、单次事务型 Scheduler tick、停机补偿和重启用排期；补全 Run claim/renew/fencing、取消、延迟/有限重试、过期恢复及安全终态引用/错误合同；未接 Worker、route、线程或 UI | 聚焦 58 passed；Recipe/Automation 155 passed、2 skipped；全量后端 2298 passed、16 skipped、1 xfailed；前端 49 files / 405 tests；生产构建和 wheel 构建通过 | `e8110e27 feat: add automation scheduling lifecycle` |
| 2026-08-19 | M3-B4 单次 Worker | 增加 request-independent `worker.run_once()`、统一绝对数据根、独立 attempt artifact、connector/SQLite 白名单重试、步骤成功/失败边界续租与取消、schema drift → Needs Review；未接常驻线程、CLI、route 或 UI | Worker/Executor 21 passed、1 skipped；全量后端 2312 passed、16 skipped、1 xfailed；前端 49 files / 405 tests；生产构建和 wheel 构建通过 | `c1181e30 feat: execute queued automation runs` |
| 2026-08-19 | M3-C 常驻 Worker | 增加长步骤 fenced heartbeat、取消期间续租、正式 console script、可中断常驻 Runtime、安全配置错误、SQLite contention 周期重试及 persisted Run 跨 runtime 重建执行；仍未接 route/UI，当前并发 1 | Worker/Runtime/CLI 31 passed；Recipe/Automation 190 passed、2 skipped；全量后端 2333 passed、16 skipped、1 xfailed；前端 49 files / 405 tests；生产构建、模块编译、wheel 和 CLI 探针通过 | `61eba9eb feat: run automation worker service` |
| 2026-08-19 | M3-D API/UI | 增加 scoped Schedule/Run API、服务端排期、持久化 manual enqueue/cancel、校验后 manifest/events 查询，以及 Schedule 设置、Runs Inbox、Needs Review 回跳和审计对话框；不把 Worker 循环放进 Flask | Recipe/Automation 208 passed、2 skipped；全量后端 2351 passed、16 skipped、1 xfailed；前端 51 files / 412 tests；相关 ESLint、生产构建、模块编译和 wheel 构建通过 | `1f5f181d feat: complete automation workbench APIs` |
| 2026-08-19 | M3-D 人工产品验收 | 使用真实 Web、Vite、独立 Worker 和 Published Movies Recipe 验证 manual Run、关页后定时执行、Runs Inbox/审计、Worker 重启恢复、queued 取消和 schema drift → Needs Review；测试 Schedule 已停用 | manual/scheduled/restarted Run 均 1 次尝试成功；queued 取消保持 0 次尝试；drift Run 1 次尝试进入 `needs_review`，manifest/events 均经 UI 反查；该 Recipe 只有 `load` 步骤 | `docs: record automation product e2e` |
| 2026-08-19 | M4 强杀恢复 | schema v4 持久化 active/cleanup attempt id；过期 Run 清理前禁止重领；无 manifest 目录隔离删除并写 retired tombstone；已有 manifest 的孤立 attempt 保留不误挂；真实执行中 Worker 子进程强制终止后由第二个 Worker 恢复 | 聚焦 Automation/Executor 97 passed、1 skipped；全量后端 2354 passed、16 skipped、1 xfailed；前端 51 files / 412 tests；Node 24.19.0 生产构建通过；真实 hard-kill 子进程验收通过 | `feat: recover abandoned automation attempts` |
| 2026-08-19 | M4 验收加固 | 用仓库 Movies 3,201 行真实数据和正式 HTTP sample connector 覆盖三步 Recipe、进程边界重建、精确聚合与 schema drift；增加两个 SQLite 连接写锁竞争和带存量业务行的 v3 → v4 migration | 聚焦 113 passed、1 skipped；产品数据用例连续 2 次、最终并发争抢用例连续 10 次通过；全量后端 2357 passed、16 skipped、1 xfailed；前端 51 files / 412 tests；Node 24.19.0 生产构建通过 | 待提交 |
| 2026-08-19 | M3-D 界面体验收口 | 以真实数据页面重排主任务和信息层级；简化中英文文案、按需定时表单、紧凑运行记录、友好错误与折叠技术信息，并同步聚焦测试 | Automation 前端 12 passed；前端 51 files / 412 tests；后端 2357 passed、16 skipped、1 xfailed；Node 24.19.0 生产构建；真实主界面、定时表单、运行列表和运行详情截图复核 | 待提交 |
| 2026-08-20 | M3-D 运行结果 | 先审原 Workflow 的表格/图表输出，再为成功 Run 增加经完整性校验的 result/sample/download 与只读结果页；不复制 Workspace、不创建 Data Thread、不调用 Agent/Replay | 后端结果/真实数据聚焦 2 passed；前端 API/运行记录 9 passed；全量后端 2357 passed、16 skipped、1 xfailed；前端 51 files / 414 tests；生产构建；3,201 行 Movies 定时 Run 浏览器复核，精确聚合、搜索和下载通过 | 待提交 |
| 2026-08-20 | M3-D typed values | 增加安全参数候选、schema v5 Schedule policy/Run snapshot、manual/定时值 UI、Worker 冻结值执行、logical schema fingerprint 与 connector filter fallback；结果页显示可读参数和紧凑小结果 | 聚焦后端 11 passed；全量后端 2368 passed、16 skipped、1 xfailed；前端 52 files / 417 tests；Node 24.19.0 生产构建通过；同一 Published RecipeVersion 的真实 Drama/Comedy 结果经浏览器同视口对照 | 待提交 |
| 2026-08-20 | 参数创作优化 | 保存配方可选用现有模型与 Workflow 上下文整理 Compiler 候选的选择、名称、说明和 `ask/keep`；新增严格建议 API、确认配置编译和参数说明展示，运行期仍无 LLM | 后端 Compiler/route/helper 43 passed；3,201 行 Movies Drama/Comedy 数据用例 1 passed；全量后端 2374 passed、16 skipped、1 xfailed；前端 52 files / 419 tests；Node 24.19.0 生产构建通过 | 待提交 |
| 2026-08-20 | Transform typed slot | Analyst `visualize` 声明受控 scalar slot，Artifact/Compiler/binder/Executor/Sandbox/交互刷新全链路复用；阻止动态代码、SQL、文件、字段和 callable；Movies `top_n=3/7` 产生不同真实 Run 结果 | 新增链路聚焦后端 54 passed；全量后端 2393 passed、16 skipped、1 xfailed；前端 52 files / 420 tests；bundled Node 24.19.0 生产构建通过 | 待提交 |
| 2026-08-20 | M3-D 最终分析报告 | 复用原 Workflow 的目标/参数/步骤脉络和原 Report 的连续阅读流；服务端从不可变 RecipeVersion 投影报告上下文，前端连续显示全部最终输出、图表优先、数据按需展开，不新增 LLM/Replay/编辑器 | Automation route + Movies 产品数据 20 passed；报告/运行记录前端 9 passed；全量后端 2393 passed、16 skipped、1 xfailed；前端 53 files / 422 tests；Node 24.19.0 生产构建；真实 Comedy Run 浏览器复核 | 待提交 |
| 2026-08-20 | 报告瘦身与显式 AI 解读 | 报告头合并状态/时间/触发/冻结值，移除重复说明与可见步骤；新增经 Run 制品校验、限量样本、严格结构输出的一次性 AI 解读，易失展示且不进入 Run/Worker | 新增报告分析/route 后端 22 passed；报告/API/运行记录前端 13 passed；全量后端 2398 passed、16 skipped、1 xfailed（2415 collected）；前端 53 files / 423 tests；Node 24.19.0 构建；真实 Comedy 报告浏览器与同视口前后对照复核 | 待提交 |
| 2026-08-20 | 参数语义优先规划 | 对照原 Workflow 的少量语义参数设计，冻结“Workflow 判断价值 → Compiler 对齐 binding → 用户确认”的最小闭环；删除默认全选、逐候选模型输出、独立匹配状态机和保存时自动改代码设想 | 产品/架构/实施/状态/Feature/Handoff 事实来源同步；Markdown 链接、占位符与 diff 检查 | 待提交 |
| 2026-08-20 | 参数语义优先实现 | 建议 helper 先读 Workflow、只返回最多 4 个推荐/未匹配选择；API 取 candidate 交集；保存对话框默认不选、推荐置顶、其他候选折叠，零候选仍可解释未匹配语义 | 参数/route/Movies 聚焦后端 28 passed；Recipe/Automation 252 passed、2 skipped；后端全量 2399 passed、16 skipped、1 xfailed；前端聚焦 7 passed、全量 53 files / 424 tests；Node 24.19.0 生产构建、compileall、diff check 与真实页面复核通过 | 待提交 |
| 2026-08-21 | 复杂真实数据回归 | 以 3,201 行 Movies 建立两层 Transform，四个 typed slot 驱动导演组合聚合、ROI 过滤与类型内排名；用 1 个定时 Run、2 个手动口径和 1 次同 schema 源数据刷新核对中间/最终制品与不可变历史 | 复杂案例 1 passed；产品/参数/Compiler/Executor 聚焦 48 passed、1 skipped；Recipe/Automation 253 passed、2 skipped；后端全量 2400 passed、16 skipped、1 xfailed | 待提交 |
| 2026-08-21 | 复杂 AI 参数推荐联动 | 在同一复杂 Movies 血缘的四个 Compiler candidates 上，用 Workflow 语义推荐三个运行输入、保留 `min_movies=2`、报告一个 unmatched 选择；推荐结果重新编译并完成 dry run、发布、定时/手动执行与独立中间/最终基线核对 | 新用例 1 passed；产品集成 5 passed；参数/route/Compiler/Executor 69 passed、1 skipped；Recipe/Automation 254 passed、2 skipped；后端全量 2401 passed、16 skipped、1 xfailed；该节点当时没有可见模型，未冒充 live provider | 待提交 |
| 2026-08-21 | SiliconFlow 真实模型验收 | 复用根目录 `.env` 与现有全局 `ModelRegistry` 配置 `Qwen/Qwen3.5-27B`，以 `SILICONFLOW_ENABLE_THINKING=false` 显式关闭 thinking，不按模型名猜能力、不增加 UI 或采样设置。真实模型在 3,201 行 Movies 四候选上推荐三个业务输入，推荐结果直接 compile/dry run/publish/入队并由无 LLM Worker 产出精确结果；页面显示服务端管理、掩码凭据和测试通过 | live 外部服务用例 1 passed：`1990/1.0/2` 得到 337 行中间指标、18 行最终结果、10 类、69 部电影、总利润 `21,326,749,404`；默认相关回归 106 passed、1 skipped；Recipe/Automation 254 passed、3 skipped；后端全量 2408 passed、17 skipped、1 xfailed | 待提交 |

M3-B1 全量验证第一次继承 Codex 终端的 `cp936` / `TERM=dumb`，触发 7 个既有插件编码和 spinner 环境相关失败；未修改这些非本 Feature 文件。显式使用 `PYTHONUTF8=1`、`TERM=xterm` 后，相关 8 项及全量 2279 项收集均通过。

## 已确认决策

- Schedule 固定不可变 Published RecipeVersion。
- 正常 Run 不调用 LLM、TrustGraph 或 Workflow Replay。
- 初始并发 1，显式配置上限 2。
- 瞬时错误最多自动重试 2 次。
- `(schedule_id, scheduled_for)` 唯一。
- v1 只承诺同主机持久化 local Workspace。
- 参数推荐先判断 Workflow 中真正有价值的 0～4 个变化，再与 Compiler candidate 对齐；Compiler 只拥有 binding 安全边界，不替代产品语义判断。
- 参数助手不新增持久化模型、匹配状态机或自动改写 transform；无有效推荐时仍可保存固定 Recipe。

## 未决与风险

- Recipe 修复 `3cd7ee12` 已推送到 `origin/feat/recipe-core`；Automation 仍没有 upstream，`origin/feat/automation-workbench` 尚未创建。
- 当前 Worktree 已基于 Recipe Core `3cd7ee12` 重放 Automation 提交；后续 Schedule/Run 工作不得回写 Recipe Core 分支。
- Web、Worker 和 SQLite 直接在本机运行，不提供 Docker 或 Compose 方案。
- SQLite 数据库和 artifact store 必须由 Web/Worker 解析到相同绝对路径。
- 当前已有正式常驻 Worker 入口，但 Web/桌面应用不自动拉起、监督或重启该进程；本机部署仍需单独管理 Worker 终端/进程。
- Worker 已覆盖步骤边界和单个长步骤的续租、取消与 fencing 失败关闭；真实独立 Worker 停止期间持久化的 queued Run 已在进程重启后成功领取，运行中子进程强制终止后的 lease 恢复、无 manifest attempt 回收和第二次尝试也已有自动化验收。仍未提供 Web/桌面对 Worker 进程的自动监督或重启。
- 当前 Runtime 固定并发 1；设计上限 2 尚未暴露，必须先验证同 Workspace 并行写入和 connector/sandbox 线程安全。
- connector classifier / SQLite busy 的有限重试已经闭环并验证不会持久化原始敏感错误；真实外部 connector 仍需使用用户已有端点补验，不建立 Docker 前置条件。
- 当前前端回归仍是 jsdom + mock API；已有浏览器闭环属于一次人工验收，尚无默认执行、可重复的浏览器 E2E。不能用新的后端产品集成测试替代或冒充这项缺口。
- Run 数据和默认报告当前严格只读；一次性 AI 解读只解释限量样本，不等于“继续分析”。真正继续分析尚未实现；以后若增加，必须是用户显式创建新 Data Thread/Workspace 副本的动作，不能改变“查看结果”不重放、不执行的合同。
- 本机现已通过未跟踪 `.env` 配置并选中服务端全局 SiliconFlow `Qwen/Qwen3.5-27B`；参数推荐已完成真实 provider 到真实 Worker 结果的显式 live 验收。默认浏览器 E2E 仍未落地，不能把人工页面检查冒充自动化覆盖。
- 报告 AI 解读的后端/helper 与 jsdom 仍主要使用受控模型响应验证；尚未完成真实 provider 的报告解读产品验收。

## 合并前检查

- [x] Recipe Core 的签名回归已修复并同步，Automation 关闭且无稳定 key 时原有交互分析可用。
- [x] Automation 列表术语为 Recipe/配方，没有 Project id、容器或 repository。
- [x] schema v2 可顺序原地升级到 v5，带存量 Schedule/Run 的 v3/v4 数据保留，Recipe 与 Automation repository 可交替打开同一数据库。
- [x] Schedule/Run API、typed values/policy、不可变 Run snapshot、持久化 manual enqueue/cancel、校验后 manifest/events/result 与最终输出 sample/download、Schedule UI、Runs Inbox、成功结果快照和 Needs Review 回跳已完成，并覆盖 scope、完整性与 Workspace 竞态。
- [x] 一次人工浏览器验收证明页面关闭后 Schedule 仍能创建 Run，重新打开页面后能从 Runs Inbox 读取成功状态和经校验的 manifest/events；默认浏览器自动化仍待建设。
- [x] repository 合同覆盖过期 running Run 的重排队/终结、旧 token fencing 和 cleanup claim 门禁；真实子进程强杀覆盖无 manifest attempt 回收、迟到创建阻断及第二次尝试成功。
- [x] 同一 Schedule/计划时间唯一；重复 tick 和两个 SQLite 连接真实争抢均只入队一次，停机跨多个周期最多创建一个补偿 Run，并把下一次推进到当前时刻之后。
- [x] 默认测试用仓库 3,201 行 Movies 数据走真实 loopback HTTP connector、三步 Recipe 和重建后的 Worker，并对 Drama/Comedy 不同参数输出、binding hash、事件、无 LLM 与 schema drift 作精确断言。
- [x] Schema drift 进入 Needs Review，并保存可校验 attempt artifact。
- [x] Automation flag 关闭时 Worker CLI 在任何存储初始化前退出，Recipe API 和 UI 也不可用；常驻 Scheduler/Worker 已由独立进程实现。
- [x] 正常 Run 路径没有 LLM、TrustGraph 或 Workflow Replay 调用。
- [x] Transform 参数只来自不可变 Artifact 声明和 Compiler 固定 binding；值独立注入，不替换代码；Movies Top 3/7 自动化结果不同且动态代码/SQL/文件/字段/callable 注入测试失败关闭。
- [x] 复杂 Movies 回归覆盖两层 Transform、四个 typed slot、类型内排名、定时/手动多口径、独立中间/最终基线，以及同参数同 binding hash 下源数据刷新改变新结果但不改旧制品。
- [x] “查看结果”只投影不可变 Run 制品，不创建 Workspace 表或 Data Thread，不写会话状态，也不提供重放/编辑控件。
- [x] 报告冗余目标/提示/步骤已移除；显式 AI 解读先校验 Run 制品、限制发送上下文和结构化输出，并保持 Run/Worker 无 LLM、结果不持久化。
- [x] 参数助手已改为 Workflow 语义优先、candidate 默认不选、AI 只返回推荐子集；无匹配/无模型/模型失败仍可保存固定 Recipe，且未新增参数状态机或自动改代码流程。
- [x] SiliconFlow `Qwen/Qwen3.5-27B` 已由现有 `.env` 全局模型配置自动加载，凭据不下发前端；thinking 默认关闭，真实推荐结果已驱动复杂 Movies Recipe 与成功 Automation Run。
- [x] `uv run pytest`、`yarn test`、`yarn build` 通过。
