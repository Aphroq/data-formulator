# 当前状态

更新时间：2026-08-19

## 阶段

Recipe Core 已在本地提交 `3cd7ee12` 关闭稳定签名 P0；Automation Workbench 已线性同步该基线，完成 M3-A 导航、Recipe 生命周期界面和 Recipe/配方术语收口。Schedule、持久化 Run、Scheduler 与 Worker 尚未开始。Analysis Integrations 仍停留在共享准备基线，尚未进入 M1 实现。

| 分支 | 已验证基线 | 状态 |
| --- | --- | --- |
| `feat/analysis-integrations` | `b08069bc` | 仅共享准备文档 |
| `feat/recipe-core` | `3cd7ee12` | 签名 P0 已修复并完整验证；本地领先 `origin/feat/recipe-core` 1 个提交，尚未推送 |
| `feat/automation-workbench` | `fd1f347c` | M3-A tip；相对新 Recipe 基线线性领先 6 个提交，尚无远端分支 |

## 已确认事实

- Automation 最终只使用工作区 rail 上的单一 `/automation` 入口；`/recipes` 是保留 query/hash 的兼容重定向。
- 页面列表对象是 Recipe，详情内切换不可变 RecipeVersion；`Automation` 不是新的 Project 实体。
- Recipe Core 已在 `DATA_FORMULATOR_HOME/automation/automation.db` 建立 schema v1/v2 和 `recipes` / `recipe_versions`。M3 不能创建第二个数据库。
- 当前 `RecipeRepository` 会拒绝未知的更高 migration。新增 schema v3 前必须先抽出 Recipe、Schedule、Run 共用的连接与 migration owner。
- 当前同步 dry run/manual run 已产生可校验的不可变制品，但没有持久化队列状态或 Runs Inbox 索引；页面的最近运行结果仍是易失状态。
- Worker 可复用 `LocalWorkspaceOpener`、`ExplicitConnectorOpener` 和 `RecipeExecutor.execute(..., run_id=...)`，不需要 Flask request 或第二套 Executor。
- 签名回归已增加显式删除 `DF_CODE_SIGNING_SECRET` / `FLASK_SECRET_KEY` 的测试：原有交互 Web 使用当前 Flask secret；Recipe 写操作、Service、Compiler 和无请求 Executor 在任何 Workspace/connector 访问前失败关闭。

## 开发前门槛状态

1. [x] `feat/recipe-core` 以 `3cd7ee12` 修复签名回归；三项交付验证通过。
2. [x] Automation 线性同步到新 Recipe HEAD；merge-base 为 `3cd7ee12`。
3. [x] “Automation projects / 自动化项目”源码文案和测试术语已收口为 Recipe/配方；聚焦前端 11 passed。
4. [ ] 从 schema v2 → v3 的失败测试开始 M3-B，再实现共享 DB migration、Schedule/Run repository 和唯一入队。

## 下一步

第一段可交付实现是 M3-B1：共享 `automation.db` 连接/migration owner、v2 → v3 原地升级、Schedule 固定 Published RecipeVersion、scope 校验和 `(schedule_id, scheduled_for)` 唯一入队。该节点不启动常驻 Worker，不接 UI，也不新增依赖。

## 阻塞

当前没有已知代码阻塞。Recipe 修复提交尚未推送，Automation 分支也尚无远端；本轮继续保留为本地开发状态，不把推送作为 M3-B 编码前置条件。
