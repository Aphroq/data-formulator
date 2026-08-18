# Automation Workbench 工程记录

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 分支 | `feat/automation-workbench` |
| Worktree | `D:\projects\dfm-wt-automation` |
| 基线 | 在 Recipe Core 基础契约提交后从 `feat/recipe-core` 创建 |
| 当前阶段 | 尚未创建 Worktree，等待 Recipe Core 基础契约 |

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

## 实施顺序

1. SQLite migration、事务和唯一约束。
2. Schedule 扫描与 queued Run。
3. lease Worker、request-independent workspace 和 Executor 调用。
4. events/manifest、取消、重试和恢复。
5. Schedule UI、Runs Inbox 和 Needs Review。

## 开发记录

| 日期 | 阶段 | 实质变更 | 验证 | 提交 |
| --- | --- | --- | --- | --- |
| 2026-08-18 | 准备 | 确定 SQLite、单 Worker、lease、状态机和 Recipe Core 依赖边界 | 设计审查 | 待提交 |
| 2026-08-18 | 准备 | 增加仓库级 Agent 指南并记录分支创建前置条件 | 文档链接与范围核对 | `docs: add repository agent guide` |

## 已确认决策

- Schedule 固定不可变 Published RecipeVersion。
- 正常 Run 不调用 LLM、TrustGraph 或 Workflow Replay。
- 初始并发 1，显式配置上限 2。
- 瞬时错误最多自动重试 2 次。
- `(schedule_id, scheduled_for)` 唯一。
- v1 只承诺同主机持久化 local Workspace。

## 未决与风险

- Worktree 只能在 Recipe Core 基础契约提交后创建。
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
