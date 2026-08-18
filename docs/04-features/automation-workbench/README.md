# Automation Workbench 工程记录

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 分支 | `feat/automation-workbench` |
| Worktree | `D:\projects\dfm-wt-automation` |
| 本机实例 | `automation`：后端 5570、Vite 5176、数据目录 `D:\projects\dfm-runtime\automation`（Worktree 创建后启用） |
| 基线 | 在 Recipe Core 基础契约提交后从 `feat/recipe-core` 创建 |
| 当前阶段 | M3-A 已完成：轻量 Automation 导航与项目管理；下一步为持久化 Schedule/Run 契约 |

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

Recipe Core 已经可以保存、校验、发布和手动运行 Recipe，但入口仍以“Recipes”技术对象为中心，且只存在于顶部导航。M3-A 先建立一个易发现、不过度设计的 Automation 工作台：用户从全局左侧导航进入，以“自动化项目”为单位查看 Recipe 及其不可变版本，并继续使用现有确定性操作。

本阶段的用户路径只有一条：

```text
左侧 App
  → 完成分析并 Save as Recipe
  → 左侧 Automation
  → 选择项目和版本
  → dry run → publish → run now / archive
```

### 参考产品与取舍

| 参考 | 可复用模式 | 本项目取舍 |
| --- | --- | --- |
| [Open WebUI Workspace](https://docs.openwebui.com/features/workspace/) | 用稳定的一级入口承载可复用资产；列表默认按最近更新组织 | 采用稳定的 `Automation` 一级入口和最近更新项目列表，不复制 Models/Knowledge/Tools 等多层标签 |
| [Langflow Projects](https://docs.langflow.org/1.8.0/concepts-flows) | 以 Project 作为相关 Flow 的管理容器 | 将一个 Recipe identity 展示为一个 Automation project，版本留在项目内部，不把每个版本平铺成项目 |
| [n8n Executions](https://docs.n8n.io/workflows/executions/all-executions/) | 执行记录既有全局入口，也能回到具体项目上下文 | 本阶段只预留 Runs 信息层级；等持久化 Run 契约落地后再增加 Runs Inbox，避免用同步手动运行伪装后台执行历史 |

### 信息架构

- 全局左栏：`App`、`Automation`；`About` 作为低频辅助入口放在底部。
- `/automation`：项目列表 + 当前项目详情，保留 `/recipes` 重定向以兼容已有链接。
- 项目列表：每个 Recipe 只显示一次，展示名称、最新版本状态、版本数和更新时间。
- 项目详情：项目说明、版本选择、状态、hash、参数、输入、步骤和与当前状态匹配的主操作。
- 创建入口：仍由分析产物的 `Save as Recipe` 触发；Automation 空状态和页头只引导返回 App，不新增无血缘的“空白自动化”。

### 范围与非范围

本阶段包含：

- 桌面端稳定左侧导航；窄屏折叠为图标但保留可访问名称和 Tooltip。
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
2. 抽出小型全局左栏并把 AppShell 内容区改成“导航 + 页面”结构。
3. 增加 `/automation`，把 `/recipes` 变成保留 query string 的兼容重定向；更新 Save as Recipe 跳转。
4. 将 Recipes 视图重命名为 Automation Workbench，项目列表不再平铺版本，并加入项目内版本选择。
5. 完成中英文文案、聚焦测试、全量前端测试、生产构建和工程记录。

### 验收标准

- `AUTOMATION_ENABLED=false` 时左栏不显示 Automation，直接访问页面仍失败关闭。
- 启用后，从任意 App 页面一键进入 Automation；当前入口有明确选中态。
- 一个含多个 RecipeVersion 的 Recipe 在项目列表中只出现一次，且可在详情内切换版本。
- 各版本只能执行其状态允许的操作，现有参数 typed binding 保持不变。
- `Save as Recipe` 打开 `/automation?version=...`，旧 `/recipes?version=...` 无损重定向。
- 页面在常用桌面宽度可用；窄屏导航不遮挡内容并保持键盘/读屏可达。
- 不新增调度、Worker、LLM 调用或复杂编排依赖。

### M3-A 实施结果

- 全局左栏已落地 `App`、`Automation`、`About`，窄屏收起文字并保留 Tooltip、可访问名称和选中态。
- `/automation` 按 Recipe identity 聚合项目，项目内可切换不可变 RecipeVersion；现有 dry run、publish、run now、archive 和 typed parameter binding 原样复用。
- `Save as Recipe` 改为进入 `/automation?version=...`；旧 `/recipes` 路径保留 query/hash 后重定向。
- `AUTOMATION_ENABLED=false` 时导航入口隐藏且直接访问失败关闭；无活动 Workspace 时不展示跨 Workspace 数据。
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
