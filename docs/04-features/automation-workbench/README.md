# Automation Workbench 工程记录

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 分支 | `feat/automation-workbench` |
| Worktree | `D:\projects\dfm-wt-automation` |
| 本机实例 | `automation`：后端 5570、Vite 5176、数据目录 `D:\projects\dfm-runtime\automation`（Worktree 创建后启用） |
| 基线 | 在 Recipe Core 基础契约提交后从 `feat/recipe-core` 创建 |
| 当前阶段 | M3-A 已完成：Automation 已收敛到现有工作区侧栏；下一步为持久化 Schedule/Run 契约 |

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

## M3-A 规划：Automation 导航与项目管理

### 用户问题与本阶段目标

Recipe Core 已经可以保存、校验、发布和手动运行 Recipe，但入口仍以“Recipes”技术对象为中心。M3-A 建立一个易发现、不过度设计的 Automation 工作台：入口复用 Data Formulator 现有的工作区侧栏，与会话、数据连接器和知识处于同一层级；不再增加一层 `App / Automation` 导航，也不改名或重组原有 Workflow Replay、知识和会话概念。

本阶段的用户路径只有一条：

```text
现有工作区
  → 完成分析并 Save as Recipe
  → 原有侧栏 Automation
  → 选择项目和版本
  → dry run → publish → run now / archive
```

### 参考产品与取舍

| 参考 | 可复用模式 | 本项目取舍 |
| --- | --- | --- |
| [Open WebUI Workspace](https://docs.openwebui.com/features/workspace/) | 用稳定入口承载可复用资产；列表默认按最近更新组织 | 在现有工作区侧栏增加一个 Automation 入口和最近更新项目列表，不复制另一套全局导航 |
| [Langflow Projects](https://docs.langflow.org/1.8.0/concepts-flows) | 以 Project 作为相关 Flow 的管理容器 | 将一个 Recipe identity 展示为一个 Automation project，版本留在项目内部，不把每个版本平铺成项目 |
| [n8n Executions](https://docs.n8n.io/workflows/executions/all-executions/) | 执行记录既有全局入口，也能回到具体项目上下文 | 本阶段只展示当前操作返回的最近运行结果；等持久化 Run 契约落地后再增加 Runs Inbox，避免用同步手动运行伪装后台执行历史 |

### 信息架构

- 工作区左栏：沿用现有添加数据、会话、数据连接器、知识这一层，只新增 `Automation`；原有 `About / App` 顶部导航保持不变。
- Automation 页面继续显示同一条工作区左栏；从会话、连接器或知识入口返回 App 时，打开对应的原有面板。
- Automation 页头不再提供重复的“打开应用”按钮；返回分析区统一使用同一条工作区侧栏。
- `/automation`：项目列表 + 当前项目详情，保留 `/recipes` 重定向以兼容已有链接。
- 项目列表：每个 Recipe 只显示一次，展示名称、最新版本状态、版本数和更新时间。
- 项目详情：项目说明、版本选择、状态、hash、参数、输入、步骤、与当前状态匹配的主操作，以及当前会话最近一次运行结果。
- 创建入口：仍由分析产物的 `Save as Recipe` 触发；Automation 空状态和页头只引导返回 App，不新增无血缘的“空白自动化”。

### 范围与非范围

本阶段包含：

- 复用现有图标侧栏的尺寸、交互和 Tooltip，并为 Automation 保留可访问名称和选中态。
- 将现有 Recipes 页面升级为轻量 Automation 项目管理页。
- 项目级列表、版本切换、现有 dry run / publish / manual run / archive 操作。
- 中英文文案、旧 URL 兼容、聚焦前端测试和构建验证。

本阶段不包含：

- 节点画布、任意 DAG 编辑、模板市场或文件夹层级。
- Schedule 表单、Scheduler、Worker、Runs Inbox 或伪造的运行统计。
- 新建空白 Recipe、修改 Published RecipeVersion，或从聊天/Redux 推断 Recipe。
- 新数据库表或新的状态管理框架。

### 复用方案

- UI 继续使用仓库现有 React Router、MUI、Redux selector 和 i18next，不引入新的导航或组件库。
- 数据继续使用 `recipeApi.ts` 和 Recipe Core API；一个 Recipe 即一个 Automation project。
- 当前 Workspace 和 identity 授权仍由后端上下文决定，前端不缓存另一份项目所有权状态。
- 状态和版本排序直接采用 repository 已有的 `updated_at DESC`、`created_at DESC` 契约。

### 实施顺序

1. 先写导航/项目分组的失败测试，锁定 feature flag、项目只出现一次、版本切换和旧路由兼容。
2. 从现有 `DataSourceSidebar` 抽出小型、可复用的工作区 rail；App 页面继续使用原有面板逻辑，Automation 页面只复用同一层入口。
3. 增加 `/automation`，把 `/recipes` 变成保留 query string 的兼容重定向；更新 Save as Recipe 跳转。
4. 将 Recipes 视图重命名为 Automation Workbench，项目列表不再平铺版本，并加入项目内版本选择。
5. 完成中英文文案、聚焦测试、全量前端测试、生产构建和工程记录。

### 验收标准

- `AUTOMATION_ENABLED=false` 时原有工作区侧栏不显示 Automation，直接访问页面仍失败关闭。
- 启用后，Automation 与会话、数据连接器、知识处于同一条 rail；当前入口有明确选中态，不出现第二条 `App / Automation` 左栏。
- 原有会话、知识、Workflow Replay、About 和 App 的名称、含义与入口行为不因本阶段改变。
- 一个含多个 RecipeVersion 的 Recipe 在项目列表中只出现一次，且可在详情内切换版本。
- 各版本只能执行其状态允许的操作，现有参数 typed binding 保持不变。
- 试运行或手动运行完成后，当前页展示状态、Run ID、步骤耗时、输出位置、最终产物标记和安全错误信息；切换版本时清除旧结果。
- `Save as Recipe` 打开 `/automation?version=...`，旧 `/recipes?version=...` 无损重定向。
- 页面在常用桌面宽度可用；窄屏导航不遮挡内容并保持键盘/读屏可达。
- 不新增调度、Worker、LLM 调用或复杂编排依赖。

### M3-A 实施结果

- Automation 复用原有工作区图标侧栏，与会话、数据连接器和知识处于同一层；没有新增 `App / Automation` 外层左栏。
- 原有 `About / App` 顶部导航及会话、知识、Workflow Replay 的概念和行为保持不变。
- `/automation` 按 Recipe identity 聚合项目，项目内可切换不可变 RecipeVersion；现有 dry run、publish、run now、archive 和 typed parameter binding 原样复用。
- `Save as Recipe` 改为进入 `/automation?version=...`；旧 `/recipes` 路径保留 query/hash 后重定向。
- `AUTOMATION_ENABLED=false` 时导航入口隐藏且直接访问失败关闭；无活动 Workspace 时不展示跨 Workspace 数据。
- 试运行和手动运行返回后展示轻量结果面板；它不冒充持久化运行历史，刷新页面后不承诺恢复。
- 未加入节点画布、Scheduler、Worker、Runs Inbox、新数据库表或新的状态管理依赖。

## 实施顺序

1. SQLite migration、事务和唯一约束。
2. Schedule 扫描与 queued Run。
3. lease Worker、request-independent workspace 和 Executor 调用。
4. events/manifest、取消、重试和恢复。
5. Schedule UI、Runs Inbox 和 Needs Review。

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

## 已确认决策

- Schedule 固定不可变 Published RecipeVersion。
- 正常 Run 不调用 LLM、TrustGraph 或 Workflow Replay。
- 初始并发 1，显式配置上限 2。
- 瞬时错误最多自动重试 2 次。
- `(schedule_id, scheduled_for)` 唯一。
- v1 只承诺同主机持久化 local Workspace。

## 未决与风险

- 当前 Worktree 基于 Recipe Core 基础契约提交 `9d20f70f` 创建；后续 Schedule/Run 工作不得回写 Recipe Core 分支。
- Web、Worker 和 SQLite 直接在本机运行，不提供 Docker 或 Compose 方案。
- SQLite 数据库和 artifact store 必须由 Web/Worker 解析到相同绝对路径。
- 进程崩溃、过期 lease 和运行中取消需要专门的恢复测试。

## 合并前检查

- [ ] 页面关闭后 Schedule 仍能创建 Run。
- [ ] 重启后 queued/running Run 可恢复。
- [ ] 同一计划时间不会重复入队。
- [ ] Schema drift 进入 Needs Review。
- [ ] Automation flag 关闭时 Worker、API、UI 均不可用。
- [ ] 正常 Run 路径没有 LLM/TrustGraph 调用。
- [ ] `uv run pytest`、`yarn test`、`yarn build` 通过。
