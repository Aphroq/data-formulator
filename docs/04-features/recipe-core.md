# Recipe Core 工程记录

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 分支 | `feat/recipe-core` |
| Worktree | `D:\projects\dfm-wt-recipe` |
| 基线 | 共享文档提交，父提交为 Data Formulator `5477f0e` |
| 当前阶段 | Worktree 已准备，尚未开发，等待 M0 血缘与运行时探针 |

## 目标

从真实后端 Artifact Lineage 编译不可变 RecipeVersion，并支持 dry run、发布和手动确定性运行。

## 范围

- ArtifactNode 模型、ledger 和 load/transform/chart/report 记录点。
- canonical JSON、SHA-256、RecipeSpec v1 和稳定 Compiler。
- typed parameter binding 与输入可刷新性。
- durable artifact store。
- request-independent workspace opener。
- Recipe repository、dry run、publish 和 manual run。
- Save as Recipe 与 Recipes 页面。

不包含 Scheduler、lease Worker 和 Runs Inbox。

## 实施顺序

1. M0 load → transform → chart 血缘探针。
2. canonical hash、ArtifactNode 和 ledger repository。
3. 四个成功发布记录点。
4. Compiler、RecipeSpec 和拒绝规则。
5. durable artifact store 与独立 workspace opener。
6. dry run、发布、manual run 和最小 UI。

## 开发记录

| 日期 | 阶段 | 实质变更 | 验证 | 提交 |
| --- | --- | --- | --- | --- |
| 2026-08-18 | 准备 | 核对 DataOperation plan hash、Sandbox、HMAC、Workspace 和前端刷新边界，建立共享文档与独立 Worktree | 固定源码审查、文档检查 | `docs: establish project plan` |

## 已确认决策

- Compiler 只接受持久化 artifact id，不读取聊天文本或 Redux 临时状态。
- Recipe 执行步骤只有 `load`、`transform`、`chart`。
- Workflow Markdown 供人阅读，不反向驱动执行。
- HMAC 验证完整性，SHA-256 负责稳定版本比较。
- 无血缘、输入 unresolved 或 dry run 失败时不得发布。

## 未决与风险

- Chart spec 的后端持久化记录点需通过真实纵向切片确认。
- Azure Blob 首发支持取决于正式 artifact store 接口；不能使用 scratch。
- Worker 所需 workspace opener 应从 Flask 请求依赖中解耦，但本分支只提供基础能力。

## 合并前检查

- [ ] 相同 artifact 集合产生相同 Recipe hash。
- [ ] 缺失或篡改血缘会失败关闭。
- [ ] typed binding 拒绝字符串注入。
- [ ] dry run 成功后才能发布。
- [ ] Published RecipeVersion 不可修改。
- [ ] 正常 manual run 不调用 LLM/TrustGraph。
- [ ] `uv run pytest`、`yarn test`、`yarn build` 通过。
