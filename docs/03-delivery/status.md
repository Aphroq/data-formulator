# 当前状态

更新时间：2026-08-19

## 阶段

Recipe Core 已在本地提交 `3cd7ee12` 关闭稳定签名 P0；Automation Workbench 已线性同步该基线，并完成 M3-A 导航、M3-B Schedule/Run repository、单次 Scheduler tick 以及 M3-C `worker.run_once()` 执行闭环。常驻 heartbeat/进程入口、Schedule/Run API 和 Runs Inbox 尚未实现。Analysis Integrations 仍停留在共享准备基线，尚未进入 M1 实现。

| 分支 | 已验证基线 | 状态 |
| --- | --- | --- |
| `feat/analysis-integrations` | `b08069bc` | 仅共享准备文档 |
| `feat/recipe-core` | `3cd7ee12` | 签名 P0 已修复并完整验证；本地领先 `origin/feat/recipe-core` 1 个提交，尚未推送 |
| `feat/automation-workbench` | `c1181e30` | M3-C 单次 Worker 实现 tip；相对 Recipe 基线线性领先 12 个实现/工程记录提交，尚无远端分支 |

## 已确认事实

- Automation 最终只使用工作区 rail 上的单一 `/automation` 入口；`/recipes` 是保留 query/hash 的兼容重定向。
- 页面列表对象是 Recipe，详情内切换不可变 RecipeVersion；`Automation` 不是新的 Project 实体。
- schema v3 由共享 `AutomationDatabase` 唯一拥有；`RecipeRepository` 与 `AutomationRepository` 使用同一绝对 `DATA_FORMULATOR_HOME/automation/automation.db`，不能创建第二个数据库或 migration 分支。
- Schedule 固定 Published RecipeVersion，数值 Cron/timezone/DST、事务型单次 tick、唯一入队、claim/renew/fencing、取消、有限重试和过期 lease 恢复已有合同测试。
- `AutomationWorker.run_once()` 复用 `LocalWorkspaceOpener`、`ExplicitConnectorOpener` 和 `RecipeExecutor`，使用明确 identity/Workspace、固定版本/default binding 和独立 attempt id，不需要 Flask request 或第二套 Executor。
- connector classifier 只有 `retry=true` 的网络/超时和明确 SQLite busy 可重试；schema drift 进入 Needs Review，签名/scope/validation 等失败永不重试。逻辑 Run 只保存安全错误和最终可校验 artifact reference。
- Recipe dry run/manual run 及后台 attempt 都产生可校验不可变制品，但尚无持久化查询 API 或 Runs Inbox；页面的最近运行结果仍是易失状态。
- 签名回归已增加显式删除 `DF_CODE_SIGNING_SECRET` / `FLASK_SECRET_KEY` 的测试：原有交互 Web 使用当前 Flask secret；Recipe 写操作、Service、Compiler 和无请求 Executor 在任何 Workspace/connector 访问前失败关闭。

## 开发前门槛状态

1. [x] `feat/recipe-core` 以 `3cd7ee12` 修复签名回归；三项交付验证通过。
2. [x] Automation 线性同步到新 Recipe HEAD；merge-base 为 `3cd7ee12`。
3. [x] “Automation projects / 自动化项目”源码文案和测试术语已收口为 Recipe/配方；聚焦前端 11 passed。
4. [x] schema v2 → v3、Schedule/Run repository、Scheduler tick 与 Run 生命周期已完成。
5. [x] request-independent `worker.run_once()`、安全错误分类、步骤边界取消和数据根一致性已完成。

## 下一步

下一段可交付实现是 M3-C 常驻运行边界：覆盖长步骤的定时 heartbeat、正式 `data_formulator_worker` 本机入口、Scheduler/Worker 生命周期和进程重启验证；随后再接 Schedule/Run API 与 Runs Inbox。不用临时 Flask 请求或脚本循环冒充正式服务。

## 阻塞

当前没有已知代码阻塞。Recipe 修复提交尚未推送，Automation 分支也尚无远端；本轮继续保留为本地开发状态，不把推送作为 M3-B 编码前置条件。
