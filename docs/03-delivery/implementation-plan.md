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
| `feat/automation-workbench` | SQLite、Schedule、Worker、Runs Inbox、显式的一次性 Run 报告解读 | 运行期 Agent、模型驱动执行和第二套模型 provider 集成 |

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
- M3-B（已完成 repository/tick 切片）：共享 `AutomationDatabase`（当前 schema v5）、固定 Published RecipeVersion 的 Schedule、数值 Cron/timezone/DST、typed parameter policy 与 Run value snapshot、事务型单次 scheduler tick，以及 Run claim/renew/fencing、取消、有限重试、过期 lease 恢复和 attempt cleanup 门禁均已落地。
- M3-C（已完成）：`c1181e30` 实现无 Flask request 的 `worker.run_once()`、白名单有限重试、独立 attempt artifact、步骤边界续租/取消、schema drift → Needs Review、稳定签名与同一绝对数据根检查；`61eba9eb` 增加覆盖长步骤的定时 heartbeat、正式 `data_formulator_worker` console script、可中断常驻 Scheduler/Worker 生命周期、安全启动边界和持久化 Run 跨 runtime 重建验证。当前并发为 1，Web/桌面应用不自动托管该进程。
- M3-D（已完成实现切片）：`1f5f181d` 增加 Workspace-scoped Schedule/Run API、持久化 manual enqueue/cancel、校验后的 events/manifest 查询，以及单一 `/automation` 页面的 Schedule 设置、Runs Inbox 和 schema drift → Needs Review 回跳。2026-08-20 又补齐 load filter/limit 与 transform scalar slot 候选、手动 typed values、Schedule value policy、Run snapshot、成功 Run result、最终输出 sample/download 与复用现有图表/表格组件的只读结果页。Analyst 可在生成 transform 时声明有意义 slot，服务端验证后随签名代码持久化；参数独立注入 Sandbox 而不替换源码。成功报告已压缩冗余文案，并提供独立的“AI 解读”按钮：仅在用户点击后，把校验后的不可变上下文、冻结值和限量结果样本交给当前模型生成短结构化结论；它不进入 Run/Worker，也不持久化。服务端拥有排期、默认值补全与类型校验，公共 API 不暴露 Worker lease/fencing 字段。

M3-D 保存参数助手已经按以下最小方案完成产品收口，没有新增运行或持久化系统：

1. 保存时模型先从 Workflow 上下文判断 0～4 个真正值得变化的选择，再把推荐映射到现有 candidate；不要求覆盖全部候选。
2. candidate 默认不选中；AI 只预选有效推荐，其余候选折叠供手动选择。模型返回未知/重复 id 时做去重和交集，不把非关键建议格式问题升级为整次失败。
3. 未匹配语义只在当前对话框显示一句返回分析的提示；不建立 Parameter Intent 表、匹配状态机、自动补 slot 或保存时改写 transform。没有模型、没有候选或没有有效推荐时仍可保存固定 Recipe。

M3 已使用真实 Web 与独立 `data_formulator_worker` 完成一次页面关闭后定时执行、Worker 重启、取消和 schema drift 的人工产品验收。该次持久制品只有 `load` 步骤，不能冒充三步自动回归；M4 已另用仓库 3,201 行 Movies 数据、正式 sample connector 和重建后的 Worker，默认自动覆盖 `load → transform → chart`、精确输出以及 schema drift。同一 Published RecipeVersion 的 load filter Drama/Comedy 手动 Run 覆盖不同冻结参数、binding hash 和业务结果；新的 transform `top_n=3/7` 场景又直接证明中间处理 slot 会改变最终行数、累计值和制品，而不是重复查看同一结果。重复调度除原幂等/停机补偿合同外，也已有两个独立 SQLite 连接真实写锁竞争回归。

M3 不增加 Automation Project 容器；列表对象始终是 Recipe，Schedule 直接固定 Published RecipeVersion。逻辑队列 Run 与 Executor attempt artifact 使用不同 id，保证崩溃恢复和重试不覆盖不可变制品。

### M4：稳定化

- Save as Recipe 参数体验已收口：Workflow 语义优先、Compiler 只做 binding gate、候选默认不选、无推荐仍可保存固定 Recipe；没有增加参数状态机或自动改代码流程。
- 权限、日志清洗和 migration 测试；schema v5 顺序原地升级、带存量 Schedule/Run 的 v3/v4 → v5 保留及未来版本拒绝已有合同覆盖。
- 长时间运行、崩溃恢复、重复调度和重启测试；运行中 Worker 子进程强制终止后的 lease 恢复、无 manifest attempt 清理和重新执行已经覆盖。
- 3,201 行 Movies 三步自动化集成已经覆盖；真实外部 connector、默认浏览器 E2E、带已配置真实模型的报告解读/参数建议验收、长期运行和进程监督仍是明确的发布稳定化缺口。
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
- typed parameter candidate/binding 的非法输入和注入尝试；transform slot 的声明/默认值/字面量引用、受控调用位置、动态字段/文件/SQL/callable 拒绝，以及 Schedule policy 与 Run snapshot 的类型、时区、偏移、大小和不可变性。
- Recipe hash、代码篡改、dry run 和发布状态机。
- malformed JSON、非法 artifact id、极端数值、路径与 symlink 越界拒绝。
- Workspace/版本快速切换、动作成功后刷新失败和即时 Run 摘要的前端回归。
- Schedule/Run API 的 scope、严格请求字段、稳定签名、typed values/default 补全、公共字段最小化和 artifact 完整性校验；Runs Inbox 的 Workspace 竞态、取消、冻结值显示和 Needs Review 回跳。
- 成功 Run 的 result/sample/download 只接受经完整性校验的 Recipe 最终输出；分析报告上下文只来自固定 RecipeVersion，连续呈现全部最终输出并复用原图表/表格组件，不创建 Workspace 表/Data Thread、不调用 Agent/Replay，也不重新执行 Recipe 或生成结论。
- SQLite migration、两个独立连接竞争下的唯一入队、lease、重试、取消和恢复。
- schema v2 → v5 顺序原地升级、带 Schedule/Run 数据的 v3/v4 → v5 保留、重复初始化和未知未来 migration 失败关闭。
- 仓库真实样例经正式 connector 的 `load → transform → chart`、进程边界重建、load filter 与 transform Top N 不同 typed values 的精确业务输出、禁止 LLM 和 schema drift 失败关闭。
- 参数推荐只返回 Workflow 语义上有价值的 candidate 子集，服务端对模型 id 做去重和 durable candidate 交集；候选默认不选中，未匹配提示不持久化。最终 compile 仍严格拒绝未知 binding；`ask`/`keep` 编译语义、无模型/无推荐时保存固定 Recipe、手动选择以及建议失败不阻断保存均有合同测试。
- 未配置稳定签名 key 且 Automation 关闭时原有交互分析可用；Recipe/Worker 边界缺 key 时安全失败。
- Worker 与 Web 的 Workspace/数据库路径一致性。
- Feature flag 关闭时的 API 和 UI 行为。

## 每阶段完成条件

- M0：四条探针都有可重复测试和明确结论。
- M1：上下文来源可追踪，Copilot 不影响其他模型。
- M2：真实 artifact 能稳定编译、dry run、发布和手动运行；Web/Worker 签名一致，父 Artifact 篡改和路径越界失败关闭，现有页面不会把成功动作误报为失败。
- M3：Schedule/Run API 与 Runs Inbox 已落地，且页面关闭后 Schedule 仍能由独立 Worker 创建并执行 Run。
- M4：所有基础命令通过，真实数据三步执行、重启、SQLite 竞争、存量迁移和 schema drift 场景通过；人工浏览器证据与默认浏览器自动化分开记录。
