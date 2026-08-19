# Automation Workbench 工程记录

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 分支 | `feat/automation-workbench` |
| Worktree | `D:\projects\dfm-wt-automation` |
| 本机实例 | `automation`：后端 5570、Vite 5176、数据目录 `D:\projects\dfm-runtime\automation` |
| 基线 | Recipe Core `3cd7ee12`；6 个 M3-A 提交已线性重放，M3-A tip 为 `fd1f347c` |
| 当前阶段 | M3-C 常驻执行边界已完成；下一步接 Schedule/Run API 与 Runs Inbox |
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

不包含 Agent、TrustGraph、Copilot 或新的 Recipe 编译逻辑。

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
| [n8n Executions](https://docs.n8n.io/workflows/executions/all-executions/) | 执行记录既有全局入口，也能回到具体工作流上下文 | 本阶段只展示当前操作返回的最近运行结果；等持久化 Run 契约落地后再增加 Runs Inbox，避免用同步手动运行伪装后台执行历史 |

### 信息架构

- 工作区左栏：沿用现有添加数据、会话、数据连接器、知识这一层，只新增 `Automation`；原有 `About / App` 顶部导航保持不变。
- Automation 页面继续显示同一条工作区左栏；从会话、连接器或知识入口返回 App 时，打开对应的原有面板。
- Automation 页头不再提供重复的“打开应用”按钮；返回分析区统一使用同一条工作区侧栏。
- `/automation`：Recipe 列表 + 当前 Recipe 详情，保留 `/recipes` 重定向以兼容已有链接。
- Recipe 列表：每个 Recipe 只显示一次，展示名称、最新版本状态、版本数和更新时间。
- Recipe 详情：说明、版本选择、状态、hash、参数、输入、步骤、与当前状态匹配的主操作，以及当前会话最近一次运行结果。
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
- 试运行或手动运行完成后，当前页展示状态、Run ID、步骤耗时、输出位置、最终产物标记和安全错误信息；切换版本时清除旧结果。
- `Save as Recipe` 打开 `/automation?version=...`，旧 `/recipes?version=...` 无损重定向。
- 页面在常用桌面宽度可用；窄屏导航不遮挡内容并保持键盘/读屏可达。
- 不新增调度、Worker、LLM 调用或复杂编排依赖。

### M3-A 实施结果

- Automation 复用原有工作区图标侧栏，与会话、数据连接器和知识处于同一层；没有新增 `App / Automation` 外层左栏。
- 原有 `About / App` 顶部导航及会话、知识、Workflow Replay 的概念和行为保持不变。
- `/automation` 按 Recipe identity 聚合列表，Recipe 内可切换不可变 RecipeVersion；现有 dry run、publish、run now、archive 和 typed parameter binding 原样复用。
- `Save as Recipe` 改为进入 `/automation?version=...`；旧 `/recipes` 路径保留 query/hash 后重定向。
- `AUTOMATION_ENABLED=false` 时导航入口隐藏且直接访问失败关闭；无活动 Workspace 时不展示跨 Workspace 数据。
- 试运行和手动运行返回后展示轻量结果面板；它不冒充持久化运行历史，刷新页面后不承诺恢复。
- 已继承 Recipe Core M2-D 的过期请求丢弃、URL 版本同步、immutable 版本元数据和“动作结果先落地、后续刷新失败只告警”语义；Automation 继续只展示一套较详细的当前运行结果面板。
- 未加入节点画布、Scheduler、Worker、Runs Inbox、新数据库表或新的状态管理依赖。

## 开发前源码审计（2026-08-19）

| 优先级 | 已核对事实 | 处理结论 |
| --- | --- | --- |
| P0 | `app.py` 未配置 `FLASK_SECRET_KEY` 时仍使用进程内随机 secret；always-on CoreSkill 需要维持原有交互行为 | 已在 Recipe Core `3cd7ee12` 恢复 app-secret fallback；Recipe 写操作、Service、Compiler 和无请求 Executor 只接受稳定 key，API 安全映射为 `SERVICE_UNAVAILABLE` |
| P0 | `tests/conftest.py` 为所有测试默认注入 `DF_CODE_SIGNING_SECRET` | 已增加显式删除两种稳定 key 的交互、API、Service、Compiler 和 Executor 回归 |
| P1 | `recipes.json`、`Recipes.tsx` 测试标题和列表标签曾出现 `Projects / 自动化项目` | 已收口为 `Recipes / 配方`，数据模型仍只有 Recipe/RecipeVersion |
| P1 | 当前实现只有 `/automation`，`/recipes` 已重定向；旧系统设计仍写两个最终页面 | 已同步产品和系统设计为单一入口，不恢复独立 Recipes 导航 |
| P1 | 原 `RecipeRepository.SCHEMA_VERSION == 2`，初始化会拒绝任何未知更高 migration | 已抽取唯一 `AutomationDatabase` owner 并升级到 schema v3；Recipe/Automation repository 可交替打开同一库 |

Recipe 修复验证：聚焦后端 67 passed、1 skipped；全量后端 2251 passed、16 skipped、1 xfailed；Recipe 前端 399 passed，生产构建通过。Automation 术语收口聚焦前端 11 passed。

## M3-B 实施契约：Schedule 与持久化 Run

### 单一数据库与 schema v3

- `DATA_FORMULATOR_HOME/automation/automation.db` 仍是唯一目录数据库。
- `AutomationDatabase` 已统一绝对路径、WAL、foreign keys、`busy_timeout`、显式事务和 v1 → v2 → v3 顺序 migration；`RecipeRepository` 与 `AutomationRepository` 共同使用。
- v3 已在现有 `recipes` / `recipe_versions` 上增加 `schedules` / `runs`；合同测试覆盖空库初始化、v2 原地升级、重复初始化、事务回滚和未知未来版本失败关闭。
- 所有查询和写入都带 `identity_id + workspace_id`；Schedule 外键固定同 scope 的 RecipeVersion，创建时必须验证其状态为 `published`。

### Schedule 契约

- v1 持久化规范化五段 Cron 和 IANA timezone；每日调度由 UI 转换为受控 Cron，不另建执行语义。
- v1 Cron 求值只接受数值、列表、升序范围和步长，day-of-month/day-of-week 使用 union 语义；春季不存在的墙上分钟跳过，秋季重复墙上分钟只执行一次。
- `version_id` 创建后不可修改。切换新版本需要创建新 Schedule，现有 Schedule 不随 Recipe 发布静默迁移。
- enabled Schedule 引用的 RecipeVersion 不得归档；用户必须先显式停用。引用 archived version 的 Schedule 保留审计关系，但不得重新启用。
- `next_run_at` 以 UTC 保存；单次 scheduler tick 在一个事务中入队当前到期 Run 并推进下一次时间。
- 服务停机跨过多个周期时，一个 Schedule 最多创建一个补偿 Run，再把下一次推进到当前时刻之后，避免无界积压。
- 显式停用期间不形成补偿任务；重新启用时按启用时刻重新计算严格晚于当前时间的下一次。
- v1 不删除 Schedule，只允许更新名称、表达式、timezone 和 enable/disable，以保留 Run 外键与审计上下文。

### Run、lease 与制品契约

```text
queued → running → succeeded | failed | needs_review | cancelled
   └──────────────→ cancelled
running ── retryable failure / expired lease, attempts < 3 ──→ queued
```

- `(schedule_id, scheduled_for)` 唯一；并发或重复 tick 只能得到一个逻辑 Run。
- 队列状态使用新的 Automation Run enum；Recipe Core 的 artifact status 只扩展必要终态，不能承载 queued/running。
- 逻辑 `run_id` 对外稳定；每次 Executor 尝试使用新的 artifact run id。Run row 只保存可校验的最终 artifact reference、binding hash、尝试次数和安全错误，不保存参数值、凭据、连接参数或绝对路径。
- claim 写入 lease owner + 随机 fencing token；renew/finish/fail 都校验 owner、token 和未过期时间。过期 Worker 即使晚到，也不能覆盖新尝试结果。
- queued 取消直接终结；running 取消只写请求，由 Worker 在步骤边界确认并产出 cancelled manifest。
- repository 强制最多 3 次总尝试（初次 + 2 次重试）和 `available_at` 延迟领取，但只接受调用方给出的显式 retryable 决定；Worker 已只把现有 connector classifier 的 `retry=true` 与明确识别的 SQLite locked/busy 接入该决定。schema drift、签名、scope、参数、代码和输出校验永不重试。
- `succeeded` / `needs_review` 必须保存完整且安全的相对 artifact reference；逻辑 Run id 不得复用为 attempt artifact id。`failed` / `needs_review` 必须保存成对的安全错误 code/message，`succeeded` / `cancelled` 不得夹带错误。
- Scheduled Run 使用固定 Recipe/default binding；M3 不新增 Schedule 参数编辑器。现有同步 manual run 在 Runs API 切换到持久化 enqueue 前保持兼容，不冒充后台历史。

### M3-B 实施切片

1. [x] **B1 迁移所有权**：唯一 DB helper、v1 → v2 → v3、重复初始化、失败回滚、未来版本拒绝；未注册 route。
2. [x] **B2 Schedule repository**：列表/编辑、数值 Cron、timezone/DST、停机补偿、重复 tick 幂等，以及同事务入队并推进 `next_run_at` 已完成。
3. [x] **B3 Run repository**：合法状态转换、claim/fencing/renew、取消、延迟/有限重试和过期 lease 恢复已完成，全部使用注入时钟且无真实 sleep。
4. [x] **B4 单次 tick/execute**：`scheduler.tick()` 与 `worker.run_once()` 均已完成；Worker 复用显式 Workspace/connector opener 和 `RecipeExecutor`，完成 claim → execute → finish/retry、独立 attempt artifact、安全错误分类、步骤边界续租/取消和 Needs Review。
5. [x] **C1 常驻执行边界**：长步骤 heartbeat、正式 `data_formulator_worker`、可中断 Scheduler/Worker 循环、安全启动/退出和跨 runtime 持久化 Run 恢复已完成；API 和 UI 后接。

当前实现没有引入 Cron 第三方依赖、Flask 后台线程、API、UI 或并发 2。Cron/timezone/DST、停机补偿、事务回滚、lease/fencing、步骤边界取消、长步骤续租、分类重试和恢复均有合同测试；one-shot 原语仍可独立测试，正式常驻生命周期只由独立 `data_formulator_worker` 进程负责。

### M3-C 常驻 Worker 契约

- 每个 claim 后先同步续租并确认 fencing，再启动该 attempt 专属的 daemon heartbeat；默认 lease 30 秒、heartbeat 10 秒。步骤仍同步执行，但 heartbeat 定时使用独立 SQLite 连接续租，因此单个 load/transform/chart 超过原始 lease 也不会被错误重领。
- heartbeat 观察到取消后继续续租，直到 Executor 到达步骤边界并写 cancelled artifact；heartbeat 失去 token、续租异常或无法停止时统一转成 `AutomationWorkerLeaseLostError`，旧 Worker 不提交逻辑 Run 终态。步骤内失败已有“不写 manifest”合同；若失败晚于 Executor 原子 finalize，可能留下未被 Run row 引用的 attempt artifact，不能将其误接为成功结果。
- `AutomationRuntime` 每个周期执行 `scheduler.tick()`，再最多调用一次 `worker.run_once()`；默认每秒轮询，等待可由 stop event 中断。循环只对白名单 SQLite locked/busy 继续下一周期，其他异常安全退出。
- wheel 新增 `data_formulator_worker = data_formulator.automation.cli:main`。入口加载与 Web 相同的 `.env` 位置，并在创建数据库、Workspace opener 或 connector registry 前验证 `AUTOMATION_ENABLED=true`、稳定签名和 local Workspace；配置与意外错误都不回显原始异常。
- `--once` 只执行一个 Scheduler/Worker 周期；默认模式安装 SIGINT/SIGTERM handler，在当前同步周期结束后退出。Worker 不监听端口，也不伪造 Flask request。
- 跨 runtime 合同先由一个 Runtime tick 把 due Schedule 写成 queued Run，再重新构造全部 repository、Scheduler 和 Worker，第二个 Runtime 能从同一 data home 执行该 Run。Web/桌面应用当前不会自动拉起或监督 Worker。

## M3 后续实施顺序

1. [x] Recipe Core 修复稳定签名配置回归，Automation rebase 到新基线并完成三项基础验证。
2. [x] 本分支完成“自动化项目 → Recipe/配方”术语收口及聚焦前端测试。
3. [x] 完成 M3-B Schedule/Run repository 和单次 `scheduler.tick()`。
4. [x] 实现 `worker.run_once()`，接入白名单错误分类、步骤边界续租/取消、固定版本/default binding 和 Web/Worker 数据根一致性。
5. [x] 增加覆盖长步骤的 lease heartbeat、正式 `data_formulator_worker` 入口和 Scheduler/Worker 本机进程生命周期。
6. 增加 Schedule/Run API、Runs Inbox 和 Needs Review 处置，再做页面关闭、独立进程和 UI 端到端验证。

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

M3-B1 全量验证第一次继承 Codex 终端的 `cp936` / `TERM=dumb`，触发 7 个既有插件编码和 spinner 环境相关失败；未修改这些非本 Feature 文件。显式使用 `PYTHONUTF8=1`、`TERM=xterm` 后，相关 8 项及全量 2279 项收集均通过。

## 已确认决策

- Schedule 固定不可变 Published RecipeVersion。
- 正常 Run 不调用 LLM、TrustGraph 或 Workflow Replay。
- 初始并发 1，显式配置上限 2。
- 瞬时错误最多自动重试 2 次。
- `(schedule_id, scheduled_for)` 唯一。
- v1 只承诺同主机持久化 local Workspace。

## 未决与风险

- Recipe 修复 `3cd7ee12` 尚未推送，Automation 也尚无远端分支；当前本地拓扑已验证，不影响继续 M3-B。
- 当前 Worktree 已基于 Recipe Core `3cd7ee12` 重放 Automation 提交；后续 Schedule/Run 工作不得回写 Recipe Core 分支。
- Web、Worker 和 SQLite 直接在本机运行，不提供 Docker 或 Compose 方案。
- SQLite 数据库和 artifact store 必须由 Web/Worker 解析到相同绝对路径。
- 当前已有正式常驻 Worker 入口，但 Web/桌面应用不自动拉起、监督或重启该进程；本机部署仍需单独管理 Worker 终端/进程。
- Worker 已覆盖步骤边界和单个长步骤的续租、取消与 fencing 失败关闭；queued Run 跨 runtime 重建已有合同，真实进程强制崩溃后的无 manifest attempt artifact 回收仍待稳定化阶段处理。
- 当前 Runtime 固定并发 1；设计上限 2 尚未暴露，必须先验证同 Workspace 并行写入和 connector/sandbox 线程安全。
- connector classifier / SQLite busy 的有限重试已经闭环并验证不会持久化原始敏感错误；真实外部 connector 仍需使用用户已有端点补验，不建立 Docker 前置条件。

## 合并前检查

- [x] Recipe Core 的签名回归已修复并同步，Automation 关闭且无稳定 key 时原有交互分析可用。
- [x] Automation 列表术语为 Recipe/配方，没有 Project id、容器或 repository。
- [x] schema v2 可原地升级到 v3，Recipe 与 Automation repository 可交替打开同一数据库。
- [ ] 页面关闭后 Schedule 仍能创建 Run。
- [x] repository 合同覆盖过期 running Run 的重排队/终结及旧 token fencing；持久化 queued Run 已覆盖跨 Runtime 重建执行，强杀真实进程的端到端验证仍待稳定化阶段。
- [x] 同一 Schedule/计划时间唯一；重复 tick 幂等，停机跨多个周期最多创建一个补偿 Run，并把下一次推进到当前时刻之后。
- [x] Schema drift 进入 Needs Review，并保存可校验 attempt artifact。
- [x] Automation flag 关闭时 Worker CLI 在任何存储初始化前退出，Recipe API 和 UI 也不可用；常驻 Scheduler/Worker 已由独立进程实现。
- [x] 正常 Run 路径没有 LLM、TrustGraph 或 Workflow Replay 调用。
- [x] `uv run pytest`、`yarn test`、`yarn build` 通过。
