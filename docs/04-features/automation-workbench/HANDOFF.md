# Automation Workbench 分支交接

> 快照日期：2026-08-19。本文用于继续开发 `feat/automation-workbench`，不替代[工程记录](./README.md)、[系统设计](../../02-architecture/system-design.md)和[实施计划](../../03-delivery/implementation-plan.md)。

## 一句话状态

M3-A 的导航和 Recipe 管理界面已经完成，并已线性同步到关闭签名 P0 的 Recipe Core `3cd7ee12`；Recipe/配方术语也已收口。Scheduler、持久化 Run、Worker 和 Runs Inbox 尚未开始，下一步直接从 M3-B1 的 schema v2 → v3 失败测试与共享 migration owner 开始。产品、架构和交付文档已统一到单一 `/automation` 入口及 `Workspace → Recipe → RecipeVersion → Run/Schedule` 模型。

## Git 与 Worktree 快照

| 项目 | 当前事实 |
| --- | --- |
| Worktree | `D:\projects\dfm-wt-automation` |
| 分支 | `feat/automation-workbench` |
| M3-A tip | `fd1f347c fix: align automation with recipe core` |
| Recipe 基线 | `3cd7ee12 fix: preserve interactive signing fallback` |
| 拓扑 | Automation 相对 Recipe 基线线性领先 6 个提交，merge-base 为 `3cd7ee12` |
| 远端 | 当前分支没有 upstream，`origin/feat/automation-workbench` 尚未创建 |
| Recipe 远端 | 本地 `feat/recipe-core` 领先 `origin/feat/recipe-core` 1 个提交；`3cd7ee12` 尚未推送 |

Automation 的 6 个提交按时间从旧到新为：

```text
f4d8bc7b docs: plan lightweight automation workbench
2cd4fb79 feat: add lightweight automation workbench
515ba647 feat: show latest automation run result
f538dfa7 fix: integrate automation into workspace navigation
d82ec07e fix: remove redundant automation app action
fd1f347c fix: align automation with recipe core
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
- 页面复用 Recipe Core API，不复制编译、dry run、发布、手动运行或 typed binding 逻辑。
- 当前会话会显示最近一次 dry run / manual run 的详细结果；该结果是易失 UI 状态，不冒充持久化运行历史。
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

## 尚未实现

- Recipe、Schedule、Run 共用的 SQLite 连接与 migration owner；当前 Recipe repository 会拒绝高于 v2 的独立 migration。
- Schedule / Run 的 SQLite 表和 repository API。
- 到期扫描、`(schedule_id, scheduled_for)` 唯一入队。
- `queued → running → succeeded / failed / needs_review / cancelled` 生命周期。
- lease 领取、续租、过期恢复、步骤边界取消和最多 2 次瞬时错误重试。
- `data_formulator_worker` 本机入口及 Web/Worker 路径一致性检查。
- 持久化 Run 查询、events/manifest API 和 Runs Inbox。
- Schedule 创建、启停、固定 Published RecipeVersion 的 UI。
- 页面关闭后运行、服务重启恢复、重复调度和 schema drift 端到端验证。

当前 [RecipeRunArtifactStore](../../../py-src/data_formulator/recipes/run_store.py)只保存 dry run / manual run 的不可变制品；它没有队列状态，也没有持久化 Inbox 索引。当前页面的 `lastRun` 也只是内存状态。两者都不能当作 M3 已完成。

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

后续 Schedule UI 继续使用这一术语，不得重新引入 Project 包装。

### 已处理：跨层设计文档的双入口描述

[系统设计](../../02-architecture/system-design.md)和[实施计划](../../03-delivery/implementation-plan.md)已经同步为单一 `/automation` 入口，`/recipes` 只做兼容重定向。

后续实现继续遵守该方向：不要重新增加独立 Recipes 导航，也不要再增加 `应用 → 自动化` 包装层。

### P2：Automation 分支尚未发布到远端

本分支目前没有 upstream；Recipe 修复提交也仍是本地状态。完成当前实现和最终验证后再决定是否首次推送；命令为：

```powershell
git push -u origin feat/automation-workbench
```

## 推荐继续顺序

1. 写 M3-B 的失败测试：现有 schema v2 原地升级、Schedule 固定 published version、scope 校验、唯一入队和非法状态转换。
2. 先抽取已有 `DATA_FORMULATOR_HOME/automation/automation.db` 的小型共享 DB helper，再增加 schema v3。当前 `RecipeRepository` 会把任何高于 v2 的 migration 视为未知版本，所以不能让 Automation repository 独立升级同一个库。
3. 增加 Schedule repository 和 queued Run repository，再实现单次 scheduler tick；先不做常驻进程和 UI。
4. 增加 request-independent Worker 的单次 claim/execute/finish 闭环，再补 lease、续租、恢复、取消和有限重试。
5. 最后接 Schedule UI 与 Runs Inbox，并做页面关闭、进程重启、重复 tick、schema drift 的真实闭环验证。

实现 M3 时注意：

- Recipe Core 的 `RecipeRepository` 已创建共享 SQLite、WAL、foreign keys、`busy_timeout` 和顺序 migration，当前 schema version 为 2。
- `RecipeRunStatus` 目前只有最终制品状态，不含 `queued/running/cancelled`；不要直接拿它冒充队列状态机。
- 逻辑队列 `run_id` 与每次 Executor 尝试的 artifact run id 分开；崩溃恢复或重试不得覆盖、复用已有不完整/不可变运行目录。
- Schedule 只接受 Published RecipeVersion，并固定 version id；新版本发布不得静默迁移已有 Schedule。
- enabled Schedule 引用的 RecipeVersion 不得归档；先显式停用，且 archived version 的 Schedule 不得重新启用。
- v1 持久化规范化五段 Cron + IANA timezone，“每日”只是受控 UI 简化；所有 `next_run_at` / `scheduled_for` 以 UTC 保存。
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

当前还没有 Worker 入口，不要用临时脚本或 Flask 请求循环伪造后台 Worker。

## 最近一次验证

M3-A tip `fd1f347c` 的历史验证为：

- Automation 页面聚焦测试：7 passed。
- 前端全量：49 files / 405 tests passed。
- 后端全量：2239 passed、16 skipped、1 xfailed。
- `yarn build` 通过。
- 相关 ESLint 通过。

2026-08-19 的新基线验证为：Recipe 聚焦后端 67 passed、1 skipped，全量后端 2251 passed、16 skipped、1 xfailed，前端 399 passed，生产构建通过；Automation 术语收口聚焦前端 11 passed。缺失稳定 key 的 P0 场景已进入专项回归。

Windows 后端全量测试建议设置 UTF-8 和终端类型：

```powershell
$env:PYTHONUTF8 = "1"
$env:TERM = "xterm"
uv run pytest
```

代码分支交付前仍需完整执行：

```text
uv run pytest
yarn test
yarn build
```

文档中记录的是最近一次已完成验证，不代表启动中的本机服务；M3-B 代码加入后仍需重新执行三项完整验证。

## 接手检查清单

- [x] 当前目录是 `D:\projects\dfm-wt-automation`，分支是 `feat/automation-workbench`。
- [x] 原有未提交文档通过可恢复 stash 跨 rebase 保存并完整恢复，没有覆盖其他 Worktree 改动。
- [x] Recipe P0 已在本地 Recipe 分支提交并完成三项验证；远端推送尚未执行。
- [x] Automation 已 rebase 到新的 Recipe HEAD，merge-base 为 `3cd7ee12`。
- [x] “自动化项目”术语已经收口为 Recipe/配方，未新增 Project 数据模型。
- [ ] 新 migration 能从现有 schema v2 原地升级，也能重复初始化。
- [ ] Schedule 固定 Published RecipeVersion，重复 tick 不会重复入队。
- [ ] Worker、Web 和 SQLite 解析到同一绝对数据根目录。
- [ ] Automation flag 关闭时 Scheduler、Worker、API 和 UI 都不可用。
- [ ] 正常 Run 路径没有 LLM、TrustGraph 或 Workflow Replay 调用。
- [ ] `uv run pytest`、`yarn test`、`yarn build` 全部通过。
