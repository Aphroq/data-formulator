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

### M1：可信交互分析

- 通用 business context provider 和 Skill。
- identity/workspace/citation 契约及前端持久化显示。
- TrustGraph 配置、超时、来源和故障降级。
- Copilot OAuth endpoint 和能力探测。

### M2：Recipe Core

- Artifact ledger 和四个记录点。
- canonical hash、Recipe 模型、Compiler 和 repository。
- durable artifact store。
- dry run、publish、manual run。
- Save as Recipe 与 Recipes 页面。

### M3：Automation Workbench

- SQLite migration、Schedule/Run repository。
- Scheduler、lease Worker、取消和有限重试。
- Schedule 设置和 Runs Inbox。
- schema drift → Needs Review 闭环。

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

## 测试门槛

基础命令：

```text
uv run pytest
yarn test
yarn build
```

必须覆盖：

- TrustGraph 合同、认证隔离、sources 规范化、超时和提示注入防护。
- Copilot OAuth 生命周期和工具调用能力探测。
- Artifact 记录、缺失血缘拒绝和稳定拓扑编译。
- typed parameter binding 的非法输入和注入尝试。
- Recipe hash、代码篡改、dry run 和发布状态机。
- SQLite migration、唯一入队、lease、重试、取消和恢复。
- Worker 与 Web 的 Workspace/数据库路径一致性。
- Feature flag 关闭时的 API 和 UI 行为。

## 每阶段完成条件

- M0：四条探针都有可重复测试和明确结论。
- M1：上下文来源可追踪，Copilot 不影响其他模型。
- M2：真实 artifact 能稳定编译、dry run、发布和手动运行。
- M3：页面关闭后 Schedule 仍能创建并执行 Run。
- M4：所有基础命令通过，重启和 schema drift 场景通过。
