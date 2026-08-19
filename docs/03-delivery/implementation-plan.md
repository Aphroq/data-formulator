# 实施计划

## 分支关系

```text
fixed upstream baseline
  └─ project main（共享准备文档）
       ├─ feat/analysis-integrations
       └─ feat/recipe-core
            └─ feat/automation-workbench
```

分析集成和 Recipe Core 从同一个共享文档提交独立开始。Automation 只在 Recipe 基础契约形成提交后，从 `feat/recipe-core` 创建。

## 分支职责

| 分支 | 负责 | 不负责 |
| --- | --- | --- |
| `feat/analysis-integrations` | TrustGraph Skill、citation、Copilot OAuth/capability | Recipe、Scheduler、Worker |
| `feat/recipe-core` | Artifact ledger、Recipe、Compiler、dry run、manual run | Scheduler、Runs Inbox |
| `feat/automation-workbench` | SQLite、Schedule、Worker、Runs Inbox | Agent 和模型集成 |

`app.py`、`src/app/App.tsx`、Redux 类型和导航是冲突热点。各分支优先新增模块，最后用小型集成提交注册路由和入口。

## Feature 工程记录

三个功能分支各自维护一份记录：

| 分支 | 工程记录 |
| --- | --- |
| `feat/analysis-integrations` | `docs/04-features/analysis-integrations/README.md` |
| `feat/recipe-core` | `docs/04-features/recipe-core/README.md` |
| `feat/automation-workbench` | `docs/04-features/automation-workbench/README.md` |

每个 Feature 目录先只放一个 `README.md`，包含范围、实施顺序、工程记录、风险和检查项。以后只有确实产生独立设计或测试说明时，才在对应目录增加文件。记录只包含阶段、实质变更、验证、提交和未决问题，不写逐命令流水账。

## 里程碑

### M0：契约与风险验证

先完成四条可执行探针：

1. TrustGraph：固定快照、真实 flow/collection、bearer workspace、sources、超时和错误格式。
2. Copilot：LiteLLM `1.91.3` 下的 OAuth device、chat、stream、tool calling 和 token refresh。
3. Lineage：真实 database load → transform → chart，后端能完整遍历并稳定编译。
4. Runtime：Worker 无 Flask request 打开相同 Workspace，Web/Worker 共享同一 SQLite 和 artifact store。

探针失败时先修正契约或收缩功能，不继续堆 UI。

M0 不启动 Docker。数据库和 TrustGraph 合同验证使用已有可访问环境或测试替身；缺少真实端点时记录为外部条件，不以搭建容器作为解决方案。

### M1：可信交互分析

- 通用 business context provider 和 Skill。
- identity/workspace/citation 契约及前端持久化显示。
- TrustGraph 配置、超时、来源和故障降级。
- Copilot OAuth endpoint 和能力探测。

### M2：Recipe Core

- Artifact ledger 和 load/transform/chart 三个后端记录点；report 等有后端持久化保存点后再增加只读包装 Artifact。
- canonical hash、Recipe 模型、Compiler 和 repository。
- durable artifact store。
- dry run、publish、manual run。
- Save as Recipe 与 Recipe 生命周期视图；M3 最终把该视图纳入单一 `/automation` 页面。

M2 合并前只做一轮最小收口：

1. Recipe 生命周期 Web 边界与 Worker 使用同一稳定代码签名密钥；原有交互 Web 保留当前 app-secret fallback。父 Artifact 在记录新血缘前复核当前 content/schema。
2. Recipe/Run 路径统一复用 `ConfinedDir`，API 严格拒绝 malformed JSON、非法 artifact id 和越界数值。
3. Recipe 生命周期视图避免跨 Workspace/版本的旧请求覆盖，区分“动作已成功、刷新失败”，并显示本次 Run 的最小摘要。
4. v1 不增加 report 执行步骤、参数编辑器、Schedule、Runs Inbox、队列或新状态库。

### M3：Automation Workbench

Recipe Core 的签名配置回归已由 `3cd7ee12` 关闭并完整验证：未配置稳定 key 且 Automation 关闭时，原有交互 `visualize` 继续可用；Recipe/Worker 需要稳定 key 的边界返回 `SERVICE_UNAVAILABLE` 或拒绝启动。Automation 已线性同步该基线，可以进入 M3 持久化开发。

- M3-A（已完成）：在现有工作区 rail 增加单一 `Automation` 入口，按 Recipe identity 聚合版本并复用 Recipe Core 生命周期 UI；`/recipes` 只保留兼容重定向。
- M3-B（已完成 repository/tick 切片）：共享 `AutomationDatabase` 和 schema v3、固定 Published RecipeVersion 的 Schedule、数值 Cron/timezone/DST、事务型单次 scheduler tick，以及 Run claim/renew/fencing、取消、有限重试和过期 lease 恢复均已落地。
- M3-C（单次执行切片已完成）：`c1181e30` 已实现无 Flask request 的 `worker.run_once()`，把 connector classifier / SQLite busy 接到有限重试，增加独立 attempt artifact、步骤边界续租/取消、schema drift → Needs Review、稳定签名与同一绝对数据根检查。下一切片补覆盖长步骤的定时 heartbeat、常驻 Scheduler/Worker 生命周期和 `data_formulator_worker` 入口。
- M3-D：在单一 `/automation` 页面增加 Schedule 设置和 Runs Inbox，并把后台 Run 的 events/manifest、schema drift → Needs Review 闭环接入 UI。

M3 不增加 Automation Project 容器；列表对象始终是 Recipe，Schedule 直接固定 Published RecipeVersion。逻辑队列 Run 与 Executor attempt artifact 使用不同 id，保证崩溃恢复和重试不覆盖不可变制品。

### M4：稳定化

- 权限、日志清洗和 migration 测试。
- 长时间运行、崩溃恢复、重复调度和重启测试。
- 中英文 UI、升级说明和发布检查。

## 第一条纵向切片

只使用一个数据库连接器、一个 TrustGraph collection 和一个支持工具调用的模型：

1. 查询业务上下文并显示来源。
2. 加载一张数据库表。
3. 生成一个 transform 和一个 chart。
4. 从 chart artifact 编译并 dry run Recipe。
5. 发布 RecipeVersion，创建每日 Schedule。
6. 成功运行一次。
7. 修改源 schema，再运行并进入 Needs Review。

通过后再扩展更多连接器、图表和调度能力。

## Git 初始化与 worktree

当前 `D:\projects\dfm-main` 已包含准备文档，因此原地初始化，不再向该目录执行 `git clone`：

```powershell
Set-Location D:\projects\dfm-main

git init
git remote add origin <你的-fork-url>
git remote add upstream https://github.com/microsoft/data-formulator.git
git fetch upstream main --tags
git checkout -B main 5477f0e236426dc8f74a498ec400414fba7fbc0f

git add docs
git commit -m "docs: establish project plan"

git worktree add -b feat/analysis-integrations D:\projects\dfm-wt-analysis main
git worktree add -b feat/recipe-core D:\projects\dfm-wt-recipe main
```

如果 fork 尚不存在，先省略 `origin`；不要把 Microsoft 上游配置成 `origin`。本地初始化、提交和 Worktree 不依赖 fork，获得 fork URL 后再执行 `git remote add origin <fork-url>`。

Recipe 基础契约提交后：

```powershell
git worktree add -b feat/automation-workbench D:\projects\dfm-wt-automation feat/recipe-core
```

让 `git worktree add` 创建目标目录，不预先放置文件。

多个 Worktree 在同一电脑并行运行时，必须按[本机多 Worktree 开发约定](./local-multi-worktree.md)使用固定实例槽位，隔离端口、`DATA_FORMULATOR_HOME`、浏览器状态和进程所有权。

## 测试门槛

基础命令：

```text
uv run pytest
yarn test
yarn build
```

测试过程中不启动 Docker，也不新增容器 fixture。上游明确依赖 `tests/database-dockers/` 的测试不作为本项目默认验收前置，需在工程记录中注明未执行原因。

必须覆盖：

- TrustGraph 合同、认证隔离、sources 规范化、超时和提示注入防护。
- Copilot OAuth 生命周期和工具调用能力探测。
- Artifact 记录、缺失血缘拒绝和稳定拓扑编译。
- 父表内容/schema 被改写时不得继续记录 transform/chart，Web 签名必须能被无请求 Executor 验证。
- typed parameter binding 的非法输入和注入尝试。
- Recipe hash、代码篡改、dry run 和发布状态机。
- malformed JSON、非法 artifact id、极端数值、路径与 symlink 越界拒绝。
- Workspace/版本快速切换、动作成功后刷新失败和即时 Run 摘要的前端回归。
- SQLite migration、唯一入队、lease、重试、取消和恢复。
- schema v2 → v3 原地升级、重复初始化和未知未来 migration 失败关闭。
- 未配置稳定签名 key 且 Automation 关闭时原有交互分析可用；Recipe/Worker 边界缺 key 时安全失败。
- Worker 与 Web 的 Workspace/数据库路径一致性。
- Feature flag 关闭时的 API 和 UI 行为。

## 每阶段完成条件

- M0：四条探针都有可重复测试和明确结论。
- M1：上下文来源可追踪，Copilot 不影响其他模型。
- M2：真实 artifact 能稳定编译、dry run、发布和手动运行；Web/Worker 签名一致，父 Artifact 篡改和路径越界失败关闭，现有页面不会把成功动作误报为失败。
- M3：页面关闭后 Schedule 仍能创建并执行 Run。
- M4：所有基础命令通过，重启和 schema drift 场景通过。
