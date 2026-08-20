# Automation Workbench 分支交接

> 快照日期：2026-08-21。本文用于继续开发 `feat/automation-workbench`，不替代[工程记录](./README.md)、[系统设计](../../02-architecture/system-design.md)和[实施计划](../../03-delivery/implementation-plan.md)。

## 一句话状态

M3-A 至 M3-D 均已完成，M4 又完成运行中 Worker 强杀、过期 attempt 回收和第二次尝试恢复。提交 `1db48fca` 收口验收加固、typed values、参数创作、报告瘦身、显式 AI 解读与 Workflow 语义优先参数推荐。默认测试不只覆盖 `top_n=3/7` 和 Drama/Comedy：3,201 行 Movies 还会走 `load → 两层 transform → chart`，以四个 typed slot 跑三种导演组合分析口径，并验证同 schema 源数据刷新改变新结果但不改旧制品；复杂推荐联动又从四个候选中语义选择三个输入，重新编译后跑通定时/手动真实结果，未推荐门槛保持冻结。保存对话框候选默认不选，AI 只预选推荐子集；成功报告紧凑展示本次元信息、图表/表格和按需明细，正常 Run 仍无 LLM。2026-08-21 又通过现有 `.env`/全局模型链路接入 SiliconFlow `Qwen/Qwen3.5-27B`，默认关闭 thinking，并完成真实模型推荐到复杂 Automation Run 的显式 live 验收；仓库仍没有默认浏览器 E2E，Web/桌面应用也不自动托管 Worker。

## Git 与 Worktree 快照

| 项目 | 当前事实 |
| --- | --- |
| Worktree | `D:\projects\dfm-wt-automation` |
| 分支 | `feat/automation-workbench` |
| M3-A tip | `fd1f347c fix: align automation with recipe core` |
| 开发准备 | `305b188b fix: prepare automation persistence` |
| M3-B1 tip | `9f3056ef feat: establish automation persistence contracts` |
| M3-B2/B3 tip | `e8110e27 feat: add automation scheduling lifecycle` |
| M3-B4 tip | `c1181e30 feat: execute queued automation runs` |
| M3-C runtime tip | `61eba9eb feat: run automation worker service` |
| M3-D API/UI tip | `1f5f181d feat: complete automation workbench APIs` |
| M4 hard-kill tip | `d064dcf0 feat: recover abandoned automation attempts` |
| 参数化 Workbench tip | `1db48fca feat: complete parameterized automation workbench` |
| Recipe 基线 | `3cd7ee12 fix: preserve interactive signing fallback` |
| 实现拓扑 | 参数化 Workbench 交付提交为 `1db48fca`，merge-base 为 `3cd7ee12` |
| 远端 | 本地分支跟踪 `origin/feat/automation-workbench` |
| Recipe 远端 | 本地 `feat/recipe-core` 与 `origin/feat/recipe-core` 均指向 `3cd7ee12` |

M3-A 的 6 个提交按时间从旧到新为：

```text
f4d8bc7b docs: plan lightweight automation workbench
2cd4fb79 feat: add lightweight automation workbench
515ba647 feat: show latest automation run result
f538dfa7 fix: integrate automation into workspace navigation
d82ec07e fix: remove redundant automation app action
fd1f347c fix: align automation with recipe core
```

后续提交为：

```text
305b188b fix: prepare automation persistence
9f3056ef feat: establish automation persistence contracts
448a96bc docs: record automation persistence milestone
e8110e27 feat: add automation scheduling lifecycle
eb0eaeee docs: record automation scheduling milestone
c1181e30 feat: execute queued automation runs
ac66d59e docs: record automation worker milestone
61eba9eb feat: run automation worker service
1f5f181d feat: complete automation workbench APIs
ecb6498a docs: record automation workbench API milestone
d63170b4 docs: record automation product e2e
d064dcf0 feat: recover abandoned automation attempts
1db48fca feat: complete parameterized automation workbench
```

这是独立 Worktree，不要在 Recipe 目录里来回切分支。进入本分支应使用：

```powershell
Set-Location D:\projects\dfm-wt-automation
git status --short --branch
```

## 分支边界

本分支负责：

- 在现有工作区侧栏提供同级 `Automation` 入口。
- 复用 Recipe Core 已有的 Recipe、RecipeVersion、dry run、publish 和 deterministic executor。
- 在同一个 `automation.db` 中增加 Schedule 和持久化 Run 契约。
- 增加 Scheduler、单机 lease Worker、取消、有限重试和崩溃恢复。
- 增加 Schedule 管理和 Runs Inbox，并完成 schema drift → Needs Review 闭环。

本分支不负责：

- 改名、重组或替代原有 Workspace、项目、会话、知识、Workflow Replay。
- 新建第二套 Agent runtime、通用 DAG、节点画布或工作流平台。
- 在正常 Run 中调用 LLM、TrustGraph、Workflow Replay 或重新生成代码。
- 让保存对话框的模型创建参数 slot、改变 binding/type，或把任意字符串注入 Python/SQL。保存对话框的可选模型调用只根据 Workflow 上下文推荐少量现有候选；现有 Analyst 在交互分析中创建 slot，服务端验证后随签名代码进入 Artifact Lineage，二者不要混为一谈。
- 为参数推荐新增数据库表、匹配状态机、自动补 slot 或保存时自动改写 transform；没有有效推荐时直接保存固定 Recipe。
- 新建另一套 Recipe、RecipeVersion、artifact store、SQLite 或前端状态框架。
- 引入 Celery、Redis、Temporal、Kafka、Docker 或容器依赖。

概念边界必须保持为：

```text
Workspace / 原有项目概念
  └─ Recipe
       └─ 不可变 RecipeVersion
            ├─ 手动 Run
            └─ Schedule → 后台 Run
```

`Automation` 是管理和运行能力的入口，不是新的 Project 实体或原有项目概念的替代品。

## 已完成：M3-A

- [工作区导航 rail](../../../src/views/WorkspaceNavigationRail.tsx)从原有侧栏中做了小型复用；Automation 与会话、数据连接器、知识处于同一层。
- 没有新增 `App / Automation` 外层导航；原有 `About / App` 顶部导航保持不变。
- Automation 页头残留的“打开应用”按钮已经删除，返回分析区统一走原有 rail。
- `/automation` 是当前入口；[旧 `/recipes` 路由](../../../src/app/LegacyRecipesRedirect.tsx)保留 query/hash 后重定向。
- [Automation 页面](../../../src/views/Recipes.tsx)按 Recipe identity 聚合版本，版本在详情内切换，不再把每个版本平铺成一条顶级记录。
- `Save as Recipe` 继续从真实 Artifact Lineage 创建 Recipe，并跳转到 `/automation?version=...`。
- 页面复用 Recipe Core API，不复制编译、dry run、发布或 typed binding 逻辑；M3-D 的 Run now 只增加持久化入队，不增加第二套 Executor。
- 当前会话只保留最近一次 dry run 的详细结果；manual Run 已进入持久化 Runs Inbox，不再使用易失 `lastRun` 冒充后台历史。
- 已继承 Recipe Core 的过期响应丢弃、URL 版本同步、不可变版本元数据，以及“动作成功但刷新失败只告警”的行为。
- `AUTOMATION_ENABLED=false` 时入口隐藏，页面和 Recipe API 失败关闭。

关键实现和测试入口：

| 位置 | 用途 |
| --- | --- |
| [`src/app/App.tsx`](../../../src/app/App.tsx) | 路由、顶栏和工作区 rail 装配 |
| [`src/views/WorkspaceNavigationRail.tsx`](../../../src/views/WorkspaceNavigationRail.tsx) | 现有工作区同级入口 |
| [`src/views/Recipes.tsx`](../../../src/views/Recipes.tsx) | 当前 Automation / Recipe 管理页面 |
| [`src/app/recipeApi.ts`](../../../src/app/recipeApi.ts) | 现有 Recipe Core API client |
| [`tests/frontend/unit/app/AutomationNavigation.test.tsx`](../../../tests/frontend/unit/app/AutomationNavigation.test.tsx) | 导航、flag 和旧路由回归 |
| [`tests/frontend/unit/views/Recipes.test.tsx`](../../../tests/frontend/unit/views/Recipes.test.tsx) | 聚合、版本切换、动作结果和竞态回归 |

## 已完成：M3-B1 持久化契约

- [`AutomationDatabase`](../../../py-src/data_formulator/automation/db.py)是 `automation.db` 的唯一连接和 migration owner；`RecipeRepository` 不再维护自己的 schema 分支。
- schema v3 在 `recipes` / `recipe_versions` 上增加 `schedules` / `runs`，保留逻辑 Run 与每次 artifact attempt 的 id 分离。
- 空库、v2 顺序升级到 v5、带存量 Schedule/Run 的 v3/v4 → v5 保留、Recipe/Automation repository 交替重复打开、migration 整体回滚和未知未来版本失败关闭已有回归。
- 所有共享连接统一绝对路径、WAL、foreign keys 和 5000ms `busy_timeout`。
- [`AutomationRepository`](../../../py-src/data_formulator/automation/repository.py)已支持创建固定 Published RecipeVersion 的 Schedule、显式启停和按 `(schedule_id, scheduled_for)` 幂等创建 queued Run。
- Schedule 的 scope/version 由复合外键和 trigger 固定；enabled Schedule 会阻止 RecipeVersion 归档，archived version 不得重新启用。
- M3-B1 当时只规范化五段 Cron 空白并验证 IANA timezone；后续 M3-B2 已补齐求值。UTC 时间固定保存为六位微秒的 `Z` 格式，保证 SQLite 文本比较等价于时间顺序。
- M3-B1 没有注册 route、常驻线程、Cron 依赖、Worker 或 UI；这一边界在 B2/B3 继续保持，直到 B4 才接入不创建线程的单次 Worker。

关键测试：

| 位置 | 覆盖 |
| --- | --- |
| [`test_automation_database.py`](../../../tests/backend/recipes/test_automation_database.py) | schema v2 → v5、带存量业务行的 v3/v4 → v5 保留、重复打开、未来版本、回滚、SQLite pragma |
| [`test_automation_repository.py`](../../../tests/backend/recipes/test_automation_repository.py) | Published/scope、不可变版本、时间输入、唯一入队、归档/重启用保护 |
| [`test_recipe_repository.py`](../../../tests/backend/recipes/test_recipe_repository.py) | Recipe repository 通过共享 owner 初始化和迁移 |

## 已完成：M3-B2/B3 Scheduler 与 Run 生命周期

- [`cron.py`](../../../py-src/data_formulator/automation/cron.py)实现无第三方依赖的数值五段 Cron：列表、升序范围、步长和 DOM/DOW union；IANA timezone 下春季不存在分钟跳过，秋季重复墙上分钟只执行一次，包括在两个 fold 之间重算的重启场景。
- [`AutomationScheduler`](../../../py-src/data_formulator/automation/scheduler.py)只暴露可注入时钟的单次 `tick()`，不创建线程或循环。到期扫描、最多一个停机补偿 Run 入队和 `next_run_at > checked_at` 推进处于同一 `BEGIN IMMEDIATE` 事务，任一 Schedule 失败会整批回滚；两个独立 SQLite 连接持锁争抢同一 Schedule 的回归确认最终只入队一次。
- Schedule repository 已支持 scoped get/list/edit；编辑 Cron/timezone 会重算下一次，重新启用从启用时刻之后排期，不补跑显式停用期间的周期，固定 `version_id` 不可变。
- Run repository 已支持 scoped get、全局队列 claim、lease renew、随机 fencing token、终态完成、运行中取消请求、`available_at` 延迟重试、最多 3 次总尝试及过期 lease 恢复。旧 Worker 的过期/失效 token 不能覆盖新 attempt。
- queued 取消直接终结；running 取消只记录请求。显式恢复在 lease 过期时把已请求取消的 Run 关闭为 `cancelled`，避免崩溃后永久卡住；B4 Worker 已在步骤成功和失败边界续租、读取取消请求并生成 cancelled artifact。
- 逻辑 Run id 与 attempt artifact id 强制不同；终态 artifact reference 必须成套、为安全相对路径且 hash 类型有效。`failed` / `needs_review` 错误必须成对并清洗，`succeeded` / `cancelled` 不保存错误。
- repository 只执行“是否 retryable”的状态决定和次数上限；B4 Worker 已把 connector classifier 的 `retry=true` 和明确 SQLite locked/busy 接到该输入，其他错误不重试。

关键测试：

| 位置 | 覆盖 |
| --- | --- |
| [`test_automation_cron.py`](../../../tests/backend/recipes/test_automation_cron.py) | 数值语法、DOM/DOW、timezone、春季缺失分钟和秋季 fold 去重 |
| [`test_automation_scheduler.py`](../../../tests/backend/recipes/test_automation_scheduler.py) | 停机补偿、重复 tick、禁用/未来 Schedule、编辑/重启用、整批事务回滚 |
| [`test_automation_run_lifecycle.py`](../../../tests/backend/recipes/test_automation_run_lifecycle.py) | claim/renew/fencing、重领、取消、延迟与次数上限、恢复、scope、安全错误和 artifact reference |

## 已完成：M3-B4 单次 Worker

- [`AutomationWorker`](../../../py-src/data_formulator/automation/worker.py)在检查 feature flag 与稳定签名后最多 claim 一个 Run；缺少配置时不触碰队列。
- Worker 使用同一解析后的 data home 构造 `AutomationRepository`、`RecipeRepository` 和 `LocalWorkspaceOpener`，并拒绝两个 repository 数据库路径或 Workspace data home 不一致。
- 每次尝试生成与逻辑 Run id 不同的新 artifact run id，显式打开 identity/Workspace，校验固定 RecipeVersion，并只使用 Run 行冻结的 typed values 执行 `RecipeExecutor`；归档前已入队的不可变版本和值仍可完成。
- Recipe artifact 增加 `automation` kind 与 `cancelled` 终态。Executor 在开始、步骤成功和步骤失败边界调用 checkpoint；取消生成无错误的 immutable manifest，lease/fencing 失败则不生成终态 manifest，也不写逻辑 Run 终态。
- connector classifier 的安全 code/message 可传给逻辑 Run，但不改变既有三字段 Recipe artifact error 合同；原始 connector 异常、credential、连接参数和 classifier detail 不持久化。typed business values 只保存在逻辑 Run snapshot，不额外写入 attempt 日志/manifest。只有 classifier `retry=true` 与 SQLite locked/busy 可重试，最多 3 次总尝试，并保留最终失败 attempt artifact。
- success、failed、needs_review 和 cancelled 均映射到独立 Automation Run 状态；schema drift 在第一次尝试进入 Needs Review，不重试。
- B4 原始实现只在步骤边界续租；M3-C 已在 `run_once()` 外围增加每 attempt 定时 heartbeat。one-shot 方法仍不拥有常驻循环、route 或 Flask request。

关键测试：

| 位置 | 覆盖 |
| --- | --- |
| [`test_automation_worker.py`](../../../tests/backend/recipes/test_automation_worker.py) | flag/签名前置、空队列、归档固定版本、无 LLM、成功、Needs Review、connector/SQLite 重试上限、取消、长步骤 heartbeat、lease fencing、跨 runtime 恢复和统一数据根 |
| [`test_recipe_executor.py`](../../../tests/backend/recipes/test_recipe_executor.py) | automation artifact、classifier 安全旁路、成功/失败步骤边界取消和 checkpoint abort 不写终态 manifest |

## 已完成：M3-C 常驻 Worker

- [`AutomationRuntime`](../../../py-src/data_formulator/automation/runtime.py)把 one-shot 原语组合为正式循环：每周期先 Scheduler tick，再最多执行一个 Run；当前并发 1，默认 poll 1 秒。
- Worker claim 后立即同步续租并启动 attempt 专属 heartbeat。默认 30 秒 lease / 10 秒 heartbeat；合同把逻辑时钟推进超过原始 lease，确认长步骤仍由同一 fencing token 持有。
- heartbeat 检测取消后仍续租至步骤边界；后台续租在步骤内丢失 fencing 时，Executor 在边界 abort，不写 manifest，逻辑 Run 也保持未被旧 Worker 终结。若 lease 失败晚于 artifact 原子 finalize，只允许留下未引用 attempt，绝不能让旧 Worker 写逻辑终态。
- [`data_formulator_worker`](../../../py-src/data_formulator/automation/cli.py)已进入 wheel console scripts；默认常驻，`--once` 执行一个周期。入口在存储/connector 初始化前验证 flag、稳定签名和 local Workspace，拒绝 heartbeat ≥ lease，并对配置及意外异常输出固定安全文本。
- 常驻进程安装 SIGINT/SIGTERM handler，通过 interruptible event 等待，在当前同步周期后停止；明确 SQLite locked/busy 只延迟到下一周期，其他异常退出。
- 测试已用第二套 repository/runtime 从同一 data home 执行第一套 runtime 持久化的 queued Run。该路径没有 Flask request、第二套 Executor、Docker 或中间件。

关键测试：

| 位置 | 覆盖 |
| --- | --- |
| [`test_automation_runtime.py`](../../../tests/backend/recipes/test_automation_runtime.py) | tick/claim 顺序、可中断等待、优雅停止、SQLite busy 白名单、启动前失败关闭和共享绝对数据根 |
| [`test_automation_cli.py`](../../../tests/backend/recipes/test_automation_cli.py) | wheel entry、参数、one-shot、signal 安装/恢复、安全错误和 heartbeat/lease 配置 |

## 已完成：M3-D Schedule/Run API 与工作台

- [`AutomationService`](../../../py-src/data_formulator/automation/service.py)把 Automation queue catalog 与不可变 RecipeVersion/artifact store 接在一起，并要求 Automation/Recipe repository 使用同一个绝对数据库。Schedule 创建和 manual enqueue 在持久化前验证稳定签名、Published 状态、typed values/policy 与默认值完整性。
- [`automation` route](../../../py-src/data_formulator/routes/automation.py)在 `/api/automation` 提供 Schedule list/create/update/enable/disable、Run manual enqueue/list/get/cancel、manifest/events/result、成功 Run 最终输出表的 sample/download，以及显式一次性 report analysis。feature flag 在存储初始化前失败关闭，所有读写都使用当前 identity + durable local Workspace。
- Schedule 的首个 `next_run_at`、manual Run 的 `scheduled_for`/`available_at` 和逻辑 Run id 均由服务端产生；客户端只能提交版本、RecipeSpec 已声明的 manual values 与 Schedule policy，额外执行字段、未知 slot、类型错误、malformed JSON 和越界数字会被拒绝。
- Run 公共响应包含本次非敏感冻结值，但不包含 lease owner、fencing token 或 lease expiry。artifact/result 查询从逻辑 Run 构造 scoped attempt reference，并通过 `RecipeRunArtifactStore.load()` 校验相对路径、manifest/descriptor/文件 hash；sample/download 只接受成功 Run 在 Recipe 中声明的最终输出表，活动 Run、中间表、缺失或损坏制品失败关闭。
- [`automationApi.ts`](../../../src/app/automationApi.ts)只暴露上述最小管理面与只读结果查询，manual enqueue 发送 `version_id + parameters`，Schedule 创建发送 typed `parameter_policy` 但不发送 `next_run_at`。
- [`AutomationOperations.tsx`](../../../src/views/AutomationOperations.tsx)增加每日时间 → Cron、原始 Cron、IANA timezone、固定版本 Schedule 编辑/启停，以及持久化 Runs Inbox 的状态过滤、取消、Needs Review 回跳；成功 Run 打开 [`AutomationRunResultView.tsx`](../../../src/views/AutomationRunResultView.tsx)，失败/Needs Review 打开步骤证据与技术信息。
- 成功 Run 的结果已收口为紧凑只读分析报告：服务端从固定且经校验的 RecipeVersion 投影稳定上下文，前端把状态/时间/触发方式/冻结参数合并展示，移除重复目标说明、只读提示和可见分析步骤，再连续呈现全部最终输出，图表优先、支撑数据按需展开。默认报告不读取当前 Recipe 列表、聊天或 Redux，也不调用模型。
- [`report_analysis.py`](../../../py-src/data_formulator/automation/report_analysis.py)与 `POST /runs/<id>/analysis` 提供用户显式触发的一次性 AI 解读：先经 `load_run_result()` 验证不可变制品，再把最多 60,000 字节的目标/参数/步骤、冻结值和限量输出样本交给当前模型，严格返回摘要、1～3 条带证据发现和可选注意事项。它不属于 Run/Scheduler/Worker，不重跑、不改参数、不持久化、不创建聊天或 Data Thread；结构无效只让解读失败，Run 保持成功。
- [`Recipes.tsx`](../../../src/views/Recipes.tsx)的 Run now 已从同步 Recipe manual run 改为持久化 enqueue；dry run 仍使用当前结果面板，后台 Run 统一在 Inbox 中恢复和查看。Workspace/版本切换时旧请求不会覆盖新作用域。
- [`SaveAsRecipeDialog.tsx`](../../../src/views/SaveAsRecipeDialog.tsx)保留 Compiler 候选的直接选择，并增加可选“AI 帮我整理”：复用当前 selected model、目标分析的 `buildLeafEvents`/session Workflow context，只建议 selection、名称、说明和 `ask|keep`。建议失败不阻断保存；`ask` 编译为无 default，`keep` 沿用当前 typed default。
- [`parameter_suggestions.py`](../../../py-src/data_formulator/recipes/parameter_suggestions.py)不是 Agent runtime；它复用现有 LiteLLM Client、`workflow_distill` reasoning profile 和 Workflow 上下文摘要。Recipe route 服务端重新取得 durable candidates，要求模型输出与 candidate id 精确一致，未知/缺失/重复候选失败关闭。Compiler 最终仍拥有 parameter id、type 和 binding。
- [`transform_parameters.py`](../../../py-src/data_formulator/recipes/transform_parameters.py)拥有 transform slot 声明、默认值、受控 AST 用法和运行值校验。`visualize` 只把通过验证的 slot 与签名代码写入 Artifact；Compiler 发现后建立固定 `transform_parameter + slot_name` binding，Executor 通过 Sandbox 独立 `params` 对象注入，不做源码字符串替换。交互刷新携带同一声明/default，不另建执行器。

上面两条是当前代码事实，不是最终产品合同。下一次实现必须做最小收口：

1. Prompt 先从 Workflow 上下文判断 0～4 个真正有意义的运行选择，再引用 candidate id；响应只返回推荐子集，不再逐候选覆盖。
2. 服务端重新取得 candidates，对建议 id 去重并取交集；未知、重复或遗漏不再让整次建议失败，最终 compile 仍严格拒绝候选外 binding。
3. 保存对话框候选默认不选中，AI 只预选有效推荐，其余候选折叠；未匹配语义只显示一句返回分析提示，无模型/无推荐/失败仍可保存固定 Recipe。
4. 不新增 Parameter Intent 持久化、匹配状态机、自动修复或 transform 重写。

结果边界必须保持：Workflow Replay 交给 Agent 做语义重做；Automation Run 执行固定 Published RecipeVersion，正常路径无 LLM。“查看结果”只读取这一次 Run 的不可变制品；“AI 解读”只是另一个显式的一次性后处理动作。两者都不创建 Workspace 表、Data Thread 或 Redux 会话，也不重新执行。未来“继续分析”只能作为用户显式创建副本的独立动作。

关键测试：

| 位置 | 覆盖 |
| --- | --- |
| [`test_automation_routes.py`](../../../tests/backend/recipes/test_automation_routes.py) | scoped CRUD/enqueue/cancel、严格请求、签名/typed values、flag/local Workspace、lease 字段隐藏、artifact/result/sample/download/analysis 校验、中间表与篡改拒绝、非法模型输出不改变 Run |
| [`test_automation_report_analysis.py`](../../../tests/backend/recipes/test_automation_report_analysis.py) | Comedy 真实业务数值、目标/参数/步骤/输出样本 grounding、60 KiB 上下文上限和非法结构失败关闭 |
| [`test_automation_product_integration.py`](../../../tests/backend/recipes/test_automation_product_integration.py) | 3,201 行 Movies、正式 loopback HTTP sample connector、三步与两层 Transform 编译/dry run/publish/Schedule/重建 Worker、Drama/Comedy/Top N/四参数多口径、AI 从四候选选三并重新编译执行、固定未推荐默认值、unmatched 提示、独立中间/最终基线、同 schema 刷新、不可变旧制品、无 LLM 与 schema drift；另有默认跳过、显式凭据开启的 SiliconFlow 真实推荐到 Worker 结果测试 |
| [`automationApi.test.ts`](../../../tests/frontend/unit/app/automationApi.test.ts) | API 路径、最小 payload、服务端时间所有权与结果 sample/download |
| [`AutomationOperations.test.tsx`](../../../tests/frontend/unit/views/AutomationOperations.test.tsx) | 每日 Cron、Schedule 编辑/停用、Run 过滤/取消、成功结果、Needs Review 审计与 Workspace 竞态 |
| [`AutomationRunResultView.test.tsx`](../../../tests/frontend/unit/views/AutomationRunResultView.test.tsx) | 紧凑报告、全部最终输出、图表数据折叠/展开、冗余文本移除、AI 禁用/成功/失败/竞态与无 Tabs 回归 |
| [`test_parameter_suggestions.py`](../../../tests/backend/recipes/test_parameter_suggestions.py) | Workflow 优先 Prompt、推荐子集、candidate 交集、未知/重复忽略、元数据回退、未匹配提示、空推荐和零候选仍调用模型 |
| [`test_compiler.py`](../../../tests/backend/recipes/test_compiler.py)、[`test_recipe_routes.py`](../../../tests/backend/recipes/test_recipe_routes.py) | 用户确认配置、description、`ask|keep`、推荐结果合同、零候选未匹配提示与 candidate 绑定真相源 |
| [`test_transform_parameters.py`](../../../tests/backend/recipes/test_transform_parameters.py)、[`test_visualize_artifact_flow.py`](../../../tests/backend/agents/test_visualize_artifact_flow.py) | Analyst slot → Sandbox default → Artifact → Compiler；阈值/Top N/窗口/类别/日期允许，动态代码/SQL/文件/字段/callable 拒绝 |
| [`test_refresh_derived_data_parameters.py`](../../../tests/backend/routes/test_refresh_derived_data_parameters.py) | 交互刷新独立注入默认值且保持签名源码，动态字段选择失败关闭 |
| [`SaveAsRecipeDialog.test.tsx`](../../../tests/frontend/unit/views/SaveAsRecipeDialog.test.tsx)、[`recipeApi.test.ts`](../../../tests/frontend/unit/app/recipeApi.test.ts) | 候选默认不选、推荐子集置顶、其他候选折叠、未匹配提示、零候选分析、AI 失败固定 Recipe 回退和最小 API payload |

## 尚未实现

- Web/桌面应用自动拉起或监督 Worker、并发 2、长期运行验收。
- 默认执行的浏览器 E2E，以及使用用户已有真实外部 connector 端点的验收。2026-08-20 已人工复核 3,201 行 Movies 三步定时 Run 的结果图表、表格、搜索和下载，但仍不能把人工浏览器证据或后端 loopback 集成写成自动化浏览器覆盖。
- 带真实已配置模型的默认浏览器 E2E，以及报告 AI 解读 live 验收。参数建议已经完成真实 provider 后端产品闭环和人工模型选择/连通检查，但这不等于自动化 UI 覆盖。

当前 [RecipeRunArtifactStore](../../../py-src/data_formulator/recipes/run_store.py)保存 dry run、Recipe Core 兼容 manual run 和 automation attempt 的不可变终态制品；Automation 队列状态继续只在 `runs` 表中，页面通过 scoped Runs API 查询，不复制到 Redux 或会话状态。Recipe Core 的同步 manual API 暂时保留兼容，但 `/automation` 的 Run now 已使用持久化队列。

## M3-B 前置问题处理结果

### 已处理 P0：Recipe 基线的稳定签名配置回归

原基线存在一个会影响原有交互分析路径的问题：

- [`app.py`](../../../py-src/data_formulator/app.py)在未配置 `FLASK_SECRET_KEY` 时仍生成进程内随机 Flask secret。
- 原 [`code_signing.py`](../../../py-src/data_formulator/security/code_signing.py)在非显式 dev 模式且环境中没有 `DF_CODE_SIGNING_SECRET` / `FLASK_SECRET_KEY` 时直接抛出 `CodeSigningConfigurationError`。
- 原有 [`analyst/skills/core/skill.py`](../../../py-src/data_formulator/analyst/skills/core/skill.py)无论 Automation flag 是否开启，都会对成功的 transform 调用 `sign_result()`。
- Recipe route 的预期错误映射没有处理 `CodeSigningConfigurationError`。
- 测试全局注入 `DF_CODE_SIGNING_SECRET`，因此全量测试通过不能证明“未配置稳定密钥”的标准非 dev 启动安全。

该问题已在 Recipe 提交 `3cd7ee12` 修复：

- 原有交互 Web 在无稳定环境 key 时使用当前 Flask `app.secret_key`，保持 Automation 关闭时的 visualize 行为。
- Recipe compile、dry run、publish、manual run、Service、Compiler 和无请求 Executor 只接受稳定环境 key，并在访问 Workspace、Artifact Lineage 或 connector 前失败关闭。
- Recipe API 把配置错误映射为不泄露内部细节的 `SERVICE_UNAVAILABLE`；只读 list/get 不被错误扩大为全局禁用。
- 显式 dev fallback 同样不能通过 Recipe 稳定模式。
- 聚焦后端 67 passed、1 skipped；全量后端 2251 passed、16 skipped、1 xfailed；前端 399 passed，生产构建通过。

### 已处理 P1：“自动化项目”概念

当前源码文案和测试名称已从 `Automation projects / 自动化项目 / 项目` 收口为 `Recipes / 配方`。历史工程记录保留当时用词以解释提交背景，但当前模型和 UI 都不再把 Recipe identity 描述成 Project。

最小收口方案：

- 页面标题保留 `Automation`。
- 左侧列表直接叫 `Recipes / 配方`，列表项就是 Recipe，详情内是 RecipeVersion。
- 后续 Schedule 直接绑定 Published RecipeVersion，不增加 Project 容器、project id 或 project repository。
- `src/i18n/locales/{zh,en}/recipes.json`、`src/views/Recipes.tsx` 和对应前端测试已同步，聚焦前端 11 passed。
- 不改原有 Workspace、项目、会话和 Workflow Replay 的名称或行为。

当前 Schedule UI 已使用这一术语，后续稳定化不得重新引入 Project 包装。

### 已处理：跨层设计文档的双入口描述

[系统设计](../../02-architecture/system-design.md)和[实施计划](../../03-delivery/implementation-plan.md)已经同步为单一 `/automation` 入口，`/recipes` 只做兼容重定向。

后续实现继续遵守该方向：不要重新增加独立 Recipes 导航，也不要再增加 `应用 → 自动化` 包装层。

### 已处理：Automation 分支首次发布

参数化 Workbench 交付提交为 `1db48fca`；本地分支跟踪 `origin/feat/automation-workbench`。后续只使用普通 fast-forward push，不覆盖远端历史。

## 推荐继续顺序

1. 选择并落地默认可运行的浏览器 E2E，把已通过的真实参数推荐闭环固化到 UI，并补报告 AI 解读 live 验收。
2. 使用用户已有真实外部 connector 端点补验；之后再决定 Web/桌面 Worker 监督、长期运行和并发 2。
3. 如果要把 transform slot/spec/compiler/Recipe route/helper/Sandbox 契约回迁 Recipe Core，另开经过评审的独立提交，不从 Automation 分支改写或覆盖 Recipe Core 历史。

实现 M3 时注意：

- `AutomationDatabase` 是唯一共享 SQLite owner，当前 schema version 为 5；不要把 migration 逻辑重新放回 Recipe 或另一个 repository。
- `RecipeRunStatus` 只含 `succeeded/failed/needs_review/cancelled` 最终制品状态，不含 `queued/running`；不要直接拿它冒充 Automation 队列状态机。
- 逻辑队列 `run_id` 与每次 Executor 尝试的 artifact run id 分开；崩溃恢复或重试不得覆盖、复用已有不完整/不可变运行目录。
- Schedule 只接受 Published RecipeVersion，并固定 version id；新版本发布不得静默迁移已有 Schedule。
- enabled Schedule 引用的 RecipeVersion 不得归档；先显式停用，且 archived version 的 Schedule 不得重新启用。
- v1 使用数值五段 Cron + IANA timezone，“每日”只是受控 UI 简化；所有 `next_run_at` / `scheduled_for` 以 UTC 保存。不要改变已锁定的 DST 语义：春季缺失分钟跳过、秋季重复墙上分钟一次。
- Web 与 Worker 必须用显式 identity/workspace 打开器和同一绝对数据根目录，不能伪造 Flask request。
- 先做单 Worker、并发 1；只有显式配置时允许到 2。
- 自动重试只认可现有 connector classifier 的 `retry=true` 和明确列出的 SQLite busy，最多 2 次；schema/signature/scope/validation 错误不重试。
- 不为未来分布式需求提前引入 ORM、消息中间件、依赖注入框架或通用 DAG 抽象。

## 本机启动

固定实例资源：

| 资源 | 值 |
| --- | --- |
| 后端 | `127.0.0.1:5570` |
| Vite | `127.0.0.1:5176` |
| 数据目录 | `D:\projects\dfm-runtime\automation` |
| 桌面协调端口 | `49734` |

启动前确认 5570 和 5176 没有被未知进程占用。Automation 实例必须使用独立浏览器 Profile，因为 Cookie 不按端口隔离。

未跟踪的 `.env` 应提供私有且稳定的 `FLASK_SECRET_KEY`；不要把密钥提交到 Git。

后端终端：

```powershell
Set-Location D:\projects\dfm-wt-automation
$env:DATA_FORMULATOR_HOME = "D:\projects\dfm-runtime\automation"
$env:DF_DESKTOP_COORDINATION_PORT = "49734"
$env:AUTOMATION_ENABLED = "true"
uv run data_formulator --dev --host 127.0.0.1 --port 5570 --sandbox local
```

前端终端：

```powershell
Set-Location D:\projects\dfm-wt-automation
$env:PATH = "C:\Users\lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;$env:PATH"
$env:API_PORT = "5570"
yarn run start --host 127.0.0.1 --port 5176 --strictPort
```

Worker 终端：

```powershell
Set-Location D:\projects\dfm-wt-automation
$env:DATA_FORMULATOR_HOME = "D:\projects\dfm-runtime\automation"
$env:AUTOMATION_ENABLED = "true"
$env:WORKSPACE_BACKEND = "local"
uv run data_formulator_worker --worker-id "automation-worker-1"
```

Worker 与 Web 从当前 Worktree 未跟踪的 `.env` 读取同一个稳定签名密钥。它不监听端口；用 `Ctrl+C` 优雅停止。单周期诊断可加 `--once`，但不能用外部脚本循环 `--once` 冒充正式常驻生命周期。

## 最近一次验证

复杂真实数据处理节点：

- 两层 Transform、四参数、三种业务口径及同 schema 源数据刷新案例通过；复杂 AI 推荐联动又验证四候选选三、固定 `min_movies=2`、一个 unmatched 选择及推荐后的 22/18 行真实定时/手动结果。
- 产品集成：5 passed；参数/route/Compiler/Executor：69 passed、1 skipped；Recipe/Automation：254 passed、2 skipped。
- 当前后端全量：2408 passed、17 skipped、1 xfailed；没有启动 Docker。SiliconFlow 相关默认回归 106 passed、1 skipped，Recipe/Automation 254 passed、3 skipped；新增 skip 是显式凭据开启的外部服务用例，已单独得到 1 passed。
- SiliconFlow `Qwen/Qwen3.5-27B` 通过根目录未跟踪 `.env` 和现有全局 `ModelRegistry` 自动加载，API key 仅留服务端；页面显示“由服务端管理”、掩码凭据和“测试通过”。`SILICONFLOW_ENABLE_THINKING=false` 作为服务端 provider 配置传给 Client，不按模型名推断能力；其余生成参数沿用 provider 默认值。
- live 用例使用 3,201 行、16 列 Movies 真实血缘，模型推荐 `start_year/min_roi/top_directors` 并冻结 `min_movies`；推荐结果完成 compile、`load → transform → transform → chart` dry run、publish 和 Worker Run。输入 `1990/1.0/2` 产出 337 行中间指标、18 行最终结果、10 个类型、69 部电影、总利润 `21,326,749,404`，并逐表匹配独立 Pandas 基线；执行阶段禁止 LLM 仍成功。

参数语义优先收口节点：

- 参数/helper/route/Movies 聚焦后端：28 passed；包含真实 Workflow 上下文、Lineage candidate、推荐 `top_n` 后重新编译，以及 3,201 行 Movies 的 Worker `top_n=3/7` 不同结果。
- Recipe/Automation 后端目录：252 passed、2 skipped；没有启动 Docker。
- 后端全量：2399 passed、16 skipped、1 xfailed；使用项目约定的 UTF-8/xterm 环境。
- 参数 API/保存对话框聚焦前端：7 passed；前端全量 53 files / 424 tests passed。
- bundled Node 24.19.0 的 `yarn build`、Python compileall 与 `git diff --check` 通过；真实 `/automation` 页面复核无新增控制台错误，只有既有 Redux selector 性能警告。
- 当前浏览器会话仍没有带 current Recipe Artifact 的可保存图表；全局真实模型已选中并通过连接测试，但保存弹窗端到端 UI 仍未自动化，不能冒充默认浏览器 E2E。

此前未提交的 M4 验收加固、Run 结果、typed values、参数创作、transform slot、报告瘦身与显式 AI 解读节点：

- Transform slot/Artifact/Compiler/刷新/真实 Worker 结果聚焦：54 passed；3,201 行 Movies `top_n=3/7` 产品数据用例包含在内。
- 后端全量：2398 passed、16 skipped、1 xfailed（2415 collected）；使用项目约定的 UTF-8/xterm 测试环境，没有启动 Docker。
- 报告 AI/route 聚焦后端 22 passed；报告/API/运行记录聚焦前端 13 passed。
- 前端全量：53 files / 423 tests passed；默认 Node 20.15.1 因现有 jsdom 依赖的 CJS/ESM 冲突无法启动 Vitest，改用工作区 bundled Node 24.19.0 后全部通过。
- bundled Node 24.19.0 的 `yarn build` 通过；Vite 变换 2709 modules。构建保留既有 eval、混合动态/静态 import 和大 chunk 警告，无新增失败。
- `python -m compileall` 与 `git diff --check` 通过；独立 `tsc --noEmit` 仍命中既有 [`dfSlice.tsx`](../../../src/app/dfSlice.tsx) `parentTurn` TS7022，正式 Vite build 不受影响，本节点没有修改该文件。
- 浏览器人工复核：3,201 行 Movies 的 scheduled Run 成功；既有验收显示 12 个类型、2,926 部有类型电影、Drama 789 部和全球票房 `40,476,168,953`。本轮又打开真实 Comedy Run，确认冻结参数、675 部电影、全球票房 `50,384,049,282`、图表、按需数据、紧凑信息层级和技术信息分层；同一 688×911 视口完成优化前后组合对照，控制台无错误。
- 本机已选中服务端全局真实模型，“AI 帮我整理”的后端产品闭环已完成 live 验收；保存弹窗默认浏览器 E2E 与报告“AI 解读”真实 provider 验收仍明确待补。

M4 `d064dcf0` 的历史交付验证为：

- Automation/Executor 聚焦：97 passed、1 skipped。
- 后端全量：2354 passed、16 skipped、1 xfailed。
- 前端全量：51 files / 412 tests passed；bundled Node 24.19.0 生产构建通过。
- 真实 hard-kill 子进程验收确认无 manifest attempt 回收和第二次尝试成功。

M3-D `1f5f181d` 的交付验证为：

- Recipe/Automation 后端目录：208 passed、2 skipped。
- 后端全量：2351 passed、16 skipped、1 xfailed（2368 collected）。
- 前端全量：51 files / 412 tests passed。
- Automation API/UI 相关 ESLint 通过，`yarn build` 通过。
- Automation/route 模块 compileall 和 `uv build --wheel` 通过；wheel 明确包含 `automation/service.py`、`routes/automation.py`、既有 `automation/cli.py`，且保留 `data_formulator_worker` entry point。

M3-C `61eba9eb` 的交付验证为：

- Worker/Runtime/CLI 聚焦：31 passed。
- Recipe/Automation 后端目录：190 passed、2 skipped。
- 后端全量：2333 passed、16 skipped、1 xfailed。
- 前端全量：49 files / 405 tests passed。
- `yarn build`、模块 compileall 和 `uv build --wheel` 通过；wheel 明确包含 `automation/cli.py`、`runtime.py`、`worker.py` 和 `data_formulator_worker` entry point。
- CLI `--help` 可用；flag 关闭的真实 `--once` 探针以退出码 2 拒绝且不创建数据目录。

M3-B4 `c1181e30` 的历史交付验证为：

- Worker/Executor 聚焦：21 passed、1 skipped。
- 后端全量：2312 passed、16 skipped、1 xfailed（2329 collected）。
- 前端全量：49 files / 405 tests passed。
- `yarn build` 与 `uv build --wheel` 通过；wheel 明确包含 `automation/worker.py`。
- 前端首次调用到系统 Node 20 时，Vitest 49 个 fork 在 jsdom 的 ESM/CJS 加载阶段统一失败、没有执行测试；切换项目固定 bundled Node 24 后 405 项全部通过，未修改依赖或源码。

M3-B2/B3 `e8110e27` 的历史验证为：

- Cron/Scheduler/Run 生命周期及共享 repository：58 passed。
- Recipe/Automation 后端目录：155 passed、2 skipped。
- 后端全量：2298 passed、16 skipped、1 xfailed（2315 collected）。
- 前端全量：49 files / 405 tests passed。
- `yarn build` 与 `uv build --wheel` 通过；wheel 明确包含 `automation/cron.py`、`scheduler.py` 及扩展后的 repository/models。

M3-B1 `9f3056ef` 的历史验证为：

- 共享迁移/Automation/Recipe repository 聚焦：22 passed。
- Recipe/Automation 后端目录：119 passed、2 skipped。
- 后端全量：2262 passed、16 skipped、1 xfailed。
- 前端全量：49 files / 405 tests passed。
- `yarn build` 与 `uv build --wheel` 通过，新 `data_formulator.automation` 包已进入 wheel。

当前 Codex 终端继承 `cp936` 和 `TERM=dumb`。第一次直接执行全量测试时，7 个既有插件编码/spinner 用例因这两个环境值失败；没有修改这些非本 Feature 源码。显式设置 `PYTHONUTF8=1`、`TERM=xterm` 后，8 个相关用例和 2279 项全量收集均通过。

M3-A tip `fd1f347c` 的历史验证为：

- Automation 页面聚焦测试：7 passed。
- 前端全量：49 files / 405 tests passed。
- 后端全量：2239 passed、16 skipped、1 xfailed。
- `yarn build` 通过。
- 相关 ESLint 通过。

2026-08-19 的 Recipe 基线验证为：Recipe 聚焦后端 67 passed、1 skipped，全量后端 2251 passed、16 skipped、1 xfailed，前端 399 passed，生产构建通过；Automation 术语收口聚焦前端 11 passed。缺失稳定 key 的 P0 场景已经进入专项回归并通过。

Windows 后端全量测试建议设置 UTF-8 和终端类型：

```powershell
$env:PYTHONUTF8 = "1"
$env:TERM = "xterm"
uv run pytest
```

当前节点已经完整执行以下命令；后续包含代码的提交交付前仍需重跑：

```text
uv run pytest
yarn test
yarn build
```

文档中记录的是最近一次已完成验证，不代表启动中的本机服务。

## 接手检查清单

- [x] 当前目录是 `D:\projects\dfm-wt-automation`，分支是 `feat/automation-workbench`。
- [x] 原有未提交文档通过可恢复 stash 跨 rebase 保存并完整恢复，没有覆盖其他 Worktree 改动。
- [x] Recipe P0 已提交、完成三项验证并推送到 `origin/feat/recipe-core`。
- [x] Automation 已 rebase 到新的 Recipe HEAD，merge-base 为 `3cd7ee12`。
- [x] “自动化项目”术语已经收口为 Recipe/配方，未新增 Project 数据模型。
- [x] migration 能从现有 schema v2 顺序升级到 v4，也能保留 v3 中已有 Schedule/Run、重复初始化并在失败时整体回滚。
- [x] Schedule 固定 Published RecipeVersion；相同 Schedule/计划时间唯一，重复 tick 和两个独立 SQLite 连接真实争抢均只入队一次，停机周期合并为一个补偿 Run。
- [x] Run repository 和 Worker 覆盖 claim/renew/fencing、取消、有限/延迟重试、过期 lease 恢复和长步骤 heartbeat；queued Run 已覆盖跨 Runtime 重建执行。
- [x] Schedule/Run API、持久化 manual enqueue/cancel、校验后 manifest/events/result、最终输出 sample/download、Schedule UI、Runs Inbox、成功结果快照和 Needs Review 回跳已完成；公共响应不暴露 Worker lease/fencing 字段。
- [x] Runtime factory 从同一绝对 data home 构造 Workspace 与 SQLite，并拒绝 repository 路径分歧；真实 Web/Worker 双进程已做过一次人工产品验收，默认浏览器 E2E 仍待实现。
- [x] 默认后端集成使用 3,201 行 Movies、正式 loopback HTTP sample connector 和重建后的 Worker 验证三步 Recipe、精确业务输出、无 LLM 与 schema drift；它不冒充浏览器或真实外部端点验收。
- [x] Automation flag 关闭时 Worker CLI 在存储初始化前失败关闭，Recipe API 和 UI 都不可用。
- [x] 正常 Run 路径没有 LLM、TrustGraph 或 Workflow Replay 调用。
- [x] 成功 Run 的“查看结果”只读取不可变制品，不复制 Workspace、不创建 Data Thread、不写会话状态，也不重新执行 Recipe。
- [x] 成功 Run 的结果是固定 RecipeVersion 上下文与终态输出的紧凑只读报告，连续展示全部最终输出，不用重复目标、提示和步骤挤占主阅读流。
- [x] 显式 AI 解读先验证不可变 Run 制品，只发送限量上下文与结果样本，严格解析短结构化响应；正常 Run/Worker 无 LLM，解读不重跑、不持久化、不创建会话。
- [x] 参数助手已按 Workflow 语义优先收口：候选默认不选、AI 只返回推荐子集、简单交集和一句未匹配提示；没有推荐仍可保存固定 Recipe。
- [x] `uv run pytest`、`yarn test`、`yarn build` 全部通过。
