# 当前状态

更新时间：2026-08-21

## 阶段

Recipe Core 的稳定签名 P0 已由 `3cd7ee12` 关闭并推送。Automation Workbench 已完成 M3-A 至 M3-D，以及 M4 的运行中 Worker 强杀、过期 attempt 回收和第二次尝试恢复；当前提交 tip 为 `d064dcf0`。当前工作树又完成可重复验收加固、typed values、参数创作体验和成功 Run 的只读分析报告。仓库 3,201 行 Movies 除了 load filter Drama/Comedy 与 transform `top_n=3/7`，现在还覆盖四参数、两层 Transform 的导演组合分析，以及同 schema 源数据刷新；中间表、最终表、步骤事件、冻结值、binding hash 和旧制品不可变性都有精确断言，运行路径仍完全无 LLM。报告主界面已移除重复文本，参数保存助手已改为 Workflow 语义优先，并已用服务端全局配置的 SiliconFlow `Qwen/Qwen3.5-27B` 完成一次真实推荐到 Automation Run 的闭环。

| 分支 | 已验证基线 | 状态 |
| --- | --- | --- |
| `feat/analysis-integrations` | `5d012eb1` | 已有独立实现提交；本轮未审计该分支在途工作 |
| `feat/recipe-core` | `3cd7ee12` | 签名 P0 已修复、完整验证并与 `origin/feat/recipe-core` 一致 |
| `feat/automation-workbench` | `d064dcf0` | M4 强杀恢复 tip；当前有未提交的真实数据/竞争/migration、typed values、Run 结果和文档加固，仍无远端分支 |

## 已确认事实

- Automation 最终只使用工作区 rail 上的单一 `/automation` 入口；`/recipes` 是保留 query/hash 的兼容重定向。
- 页面列表对象是 Recipe，详情内切换不可变 RecipeVersion；`Automation` 不是新的 Project 实体。
- schema v5 由共享 `AutomationDatabase` 唯一拥有；`RecipeRepository` 与 `AutomationRepository` 使用同一绝对 `DATA_FORMULATOR_HOME/automation/automation.db`，不能创建第二个数据库或 migration 分支。
- Schedule 固定 Published RecipeVersion，并保存按 spec 校验的 typed value policy；Scheduler 入队时解析并冻结 Run 值。数值 Cron/timezone/DST、事务型单次 tick、唯一入队、claim/renew/fencing、取消、有限重试和过期 lease 恢复已有合同测试；唯一入队现已增加两个独立 SQLite 连接持锁竞争的真实回归。
- `AutomationWorker.run_once()` 复用 `LocalWorkspaceOpener`、`ExplicitConnectorOpener` 和 `RecipeExecutor`，使用明确 identity/Workspace、固定版本、Run value snapshot 和独立 attempt id，不需要 Flask request 或第二套 Executor。
- `data_formulator_worker` 是正式 console script；`AutomationRuntime` 常驻执行 Scheduler tick → 至多一个 Run，长步骤 heartbeat 维持 fenced lease，SIGINT/SIGTERM 在当前周期后停止。Web/桌面应用不自动拉起或监督该进程。
- connector classifier 只有 `retry=true` 的网络/超时和明确 SQLite busy 可重试；schema drift 进入 Needs Review，签名/scope/validation 等失败永不重试。逻辑 Run 只保存安全错误和最终可校验 artifact reference。
- Automation API 已提供 scoped Schedule list/create/update/enable/disable、typed value policy、持久化 manual enqueue、Run list/get/cancel、manifest/events/result、最终输出表 sample/download 和显式一次性 analysis；服务端拥有排期、类型校验和默认值补全，Run 公共响应返回本次冻结值但不暴露 lease owner/token/expiry，结果与 analysis 上下文都先通过 scope、路径、manifest 和文件 hash 校验，中间表不可查询。
- `/automation` 页面已有手动值、定时值、持久化运行记录、过滤/取消、Needs Review 回到固定 RecipeVersion，以及成功 Run 的紧凑只读报告：状态、时间、触发方式和冻结参数合并展示，全部最终输出连续呈现，图表优先、支撑数据按需展开并可完整 CSV 下载。显式“AI 解读”只返回摘要、1～3 条证据发现和可选注意事项，结果不持久化。Recipe dry run 的本次结果仍是易失 UI 状态；后台 Run 始终从持久制品恢复。
- Workflow Replay 与 Automation Run 不共用语义：Replay 调用 Agent 做可变的语义重做；Run 执行固定 Published RecipeVersion，正常路径无 LLM。“查看结果”和一次性 AI 解读都不会复制到 Workspace、创建 Data Thread、写会话状态或重新执行。
- 参数的执行边界仍由 Compiler candidate 决定。候选来自持久化 load filter/limit，或 Analyst transform 中已通过服务端校验、与签名代码共同持久化的 scalar slot；`ask` 无默认值，`keep` 沿用当前 typed 默认值。最终 compile 和正常 Run 不接受候选外的 binding。
- 参数推荐已经复用原 Workflow 的语义判断：模型从完整分析上下文中只找 0～4 个真正值得变化的选择，再映射到 Compiler candidate。候选默认不选，模型不再逐项覆盖；未知/重复建议只做去重与 candidate 交集，未匹配选择只显示一句返回分析的提示，不新增 Parameter Intent 表、匹配状态机或自动改代码流程。
- 签名回归已增加显式删除 `DF_CODE_SIGNING_SECRET` / `FLASK_SECRET_KEY` 的测试：原有交互 Web 使用当前 Flask secret；Recipe 写操作、Service、Compiler 和无请求 Executor 在任何 Workspace/connector 访问前失败关闭。
- 默认后端测试现在用 `public/df_movies.json` 的 3,201 行、16 列数据，经 loopback HTTP 和正式 sample connector 完成 `load → transform → chart`、dry run、publish、Schedule、进程边界重建、Drama/Comedy typed values 和 schema drift；输出值、binding hash、步骤事件、HTTP 重取和无 LLM 均有精确断言。
- Transform `top_n` 产品数据场景在同一 Published RecipeVersion 上运行 3/7，分别保存 3/7 行；前三行一致，累计电影数、binding hash 和制品不同。参数作为独立 Sandbox `params` 注入，签名源码不变，Worker 内 LLM 被强制抛错仍成功。
- 复杂 Movies 产品场景以 `start_year/min_movies/min_roi/top_directors` 四个 typed slot 驱动两层 Transform：先清洗并聚合导演组合的成本、票房、利润、评分与 ROI，再按类型做 ROI 过滤和 Top-N 排名。一项定时 Run 和两项手动 Run 分别得到 22/56/18 行，并逐表匹配独立 Pandas 基线；随后同参数同 binding hash 重新抓取 schema-compatible 更新，只有新 Run 利润增加 `123,456,789`，旧制品不变。
- 复杂参数推荐联动复用同一真实血缘：Workflow 语义把 `min_movies=2` 定义为固定质量门槛，受控模型边界只推荐 `start_year/min_roi/top_directors` 三个已知 candidate，并把无 slot 的“最低 IMDb 评分”保留为 unmatched。推荐结果重新编译、dry run、发布后完成定时/手动 Run，得到 22/18 行并逐表匹配独立中间/最终基线；未推荐候选没有变成第四个输入，执行期无 LLM。
- 本机未跟踪 `.env` 已通过现有 `ModelRegistry` 注册服务端全局 SiliconFlow `Qwen/Qwen3.5-27B`，前端只见掩码凭据并显示“由服务端管理/测试通过”。`SILICONFLOW_ENABLE_THINKING=false` 是唯一 provider 特有配置，Client 不按模型名猜能力，也不增加温度或预算设置。显式 live 测试在 3,201 行、16 列 Movies 的四候选真实血缘上推荐 `start_year/min_roi/top_directors`、冻结 `min_movies`，随后完成 compile、四步 dry run、publish、Worker Run 和独立 Pandas 结果核对：输入 `1990/1.0/2` 得到 337 行中间指标、18 行最终结果、10 个类型、69 部电影、总利润 `21,326,749,404`；执行期把任何 LLM 调用强制设为失败仍成功。
- 2026-08-19 的浏览器闭环仍只是一份人工验收记录，且当时的持久制品只有 `load`。仓库当前没有默认执行的浏览器 E2E，不能把后端产品集成测试冒充为浏览器覆盖。
- 2026-08-20 又用浏览器人工复核 3,201 行 Movies 三步 Run：原固定结果为 12 个类型、2,926 部有类型电影；typed values 版本的 Drama 为 789 部/`40,476,168,953`，Comedy 为 675 部/`50,384,049,282`。页面能查看本次参数、结果表格、搜索和 CSV 下载；它补足产品结果证据，但仍不是默认浏览器 E2E。
- 当前复杂数据/参数/Transform/报告节点验证：相关模型/安全/推荐/产品集成 106 passed、1 skipped；Recipe/Automation 254 passed、3 skipped；后端全量 2408 passed、17 skipped、1 xfailed。新增 skip 是默认关闭的真实外部服务测试，已在显式加载本机凭据后单独得到 1 passed；前端最近一次全量仍为 53 files / 424 tests，bundled Node 24.19.0 生产构建通过。真实模型的参数推荐后端产品闭环和模型选择界面已人工验收；默认浏览器 E2E、报告 AI 解读 live 验收与真实外部 connector 仍待完成。

## 开发前门槛状态

1. [x] `feat/recipe-core` 以 `3cd7ee12` 修复签名回归；三项交付验证通过。
2. [x] Automation 线性同步到新 Recipe HEAD；merge-base 为 `3cd7ee12`。
3. [x] “Automation projects / 自动化项目”源码文案和测试术语已收口为 Recipe/配方；聚焦前端 11 passed。
4. [x] schema v2 → v3、Schedule/Run repository、Scheduler tick 与 Run 生命周期已完成。
5. [x] request-independent `worker.run_once()`、安全错误分类、步骤边界取消和数据根一致性已完成。
6. [x] 长步骤 heartbeat、正式 Worker CLI、常驻生命周期和 repository/runtime 重建恢复合同已完成。
7. [x] Schedule/Run API、持久化 manual enqueue/cancel、校验后 artifact/result 查询、Schedule UI 和 Runs Inbox 已完成。
8. [x] 运行中 Worker 强杀、过期 attempt 定点回收、迟到创建 tombstone 和第二次尝试恢复已完成。
9. [x] 3,201 行 Movies 三步/typed values 集成、双 SQLite 连接竞争和带存量 Run 的 v3/v4 → v5 migration 回归已加入默认测试。
10. [x] 成功 Run 的只读图表/表格结果、最终输出查询/下载和三步浏览器人工复核已完成；与 Workflow Replay 的边界已写入产品、架构和 Feature 事实文档。
11. [x] Save as Recipe 参数候选、手动/定时 typed values、Run snapshot、可读值展示和 Drama/Comedy 结果差异闭环已完成。
12. [x] 可选 authoring-time AI 参数推荐、Workflow 上下文复用及 `ask/keep` 编译语义已有实现；正常 Run/Worker 仍禁止 LLM。
13. [x] Analyst transform scalar slot、服务端受控 AST/type 验证、Artifact/Compiler/binder/Executor/Sandbox/交互刷新链路和 Movies Top 3/7 真实结果差异已完成。
14. [x] 成功 Run 的最终分析报告已完成：上下文取自固定 RecipeVersion，连续显示全部最终输出；主报告移除重复目标、提示和处理步骤，没有新增 Replay、报告编辑器或第二套持久化模型。
15. [x] 显式一次性“AI 解读”已完成：先校验不可变 Run 制品，再对限量结果样本生成短结构化结论；正常 Run/Worker 无 LLM，解读不重跑、不持久化、不创建会话。
16. [x] 参数语义优先收口已完成：候选默认不选、AI 只返回推荐子集、简单交集与未匹配提示、无推荐仍可保存固定 Recipe，并有真实 Workflow 上下文与 Movies 数据回归。
17. [x] 复杂 Movies 产品回归已完成：四参数、两层 Transform、定时/手动三种口径、独立中间/最终基线，以及同 schema 源数据刷新与旧制品不可变性。
18. [x] 复杂 AI 参数推荐联动已完成：四候选语义选三、未推荐门槛冻结、unmatched 提示、重新编译及真实定时/手动数据结果闭环。
19. [x] SiliconFlow `Qwen/Qwen3.5-27B` 已通过现有 `.env` 全局模型链路加载，默认关闭 thinking，并完成真实模型推荐 → Recipe → Automation Worker → 精确数据结果的显式 live 测试。

## 下一步

下一步建立默认可运行的浏览器 E2E，把已完成的真实参数推荐闭环固化为 UI 自动化，并补报告 AI 解读 live 验收；同时使用用户已有的真实外部 connector 端点补验。之后再决定 Worker 进程监督和长期运行方案。

## 阻塞

当前没有已知代码阻塞。Recipe 修复已推送；Automation 分支仍无远端。浏览器自动化需要选择并落地测试运行时，真实外部 connector 验收需要用户已有端点，这两项是明确未完成条件，不用 skip-only 或 loopback 测试冒充完成。
