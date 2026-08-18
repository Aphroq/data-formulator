# 当前状态

更新时间：2026-08-18

## 阶段

需求、上游源码和补充参考材料已核对。项目尚未进入编码阶段；`D:\projects\dfm-main` 已初始化为 Git 仓库，固定基线为 `5477f0e`，并配置 Microsoft 仓库为 `upstream`。

## 本轮确认

- 补充参考材料可作为现状基线，核心判断已纳入 `01-product/current-capabilities.md`。
- 明确区分继续会话、语义重放、数据刷新、Recipe Run 和定时运行。
- 现有前端刷新链可复用底层能力，但不能直接充当后台 RecipeExecutor。
- 不重复实现 Workspace 导入导出、数据导入和已有结果导出。
- Agent 不生成最终机器 Recipe，也不在定时 Run 中自动修复。
- 文档已按产品、架构、交付三层拆分，不再保留重复单体计划。
- `docs/04-features` 已按三个 Feature 拆分子目录，每个目录先用一个 `README.md` 维护范围和工程记录。
- `feat/analysis-integrations` 和 `feat/recipe-core` 已各自准备独立 Worktree。
- Git 提交身份使用仓库本地配置 `aphroq <shi1490672988@qq.com>`。
- `origin` 已配置为 `https://github.com/Aphroq/data-formulator.git`，`upstream` 保持 Microsoft 官方仓库。
- 根目录中文 `AGENTS.md` 已建立，约束后续 Agent 的文档入口、分支边界、架构红线和验证门槛。
- 项目增量文档明确为上游资料的覆盖层；实现前仍需检索根文档、`docs/dev-guides`、`docs/docs-cn` 和相关测试说明。
- 项目开发、测试和运行不使用 Docker；上游已有容器资产保持原样且不进入默认验收路径。
- 同机多 Worktree 固定使用 `main`、`analysis`、`recipe`、`automation` 实例槽位，分别隔离后端/Vite 端口、数据目录、桌面协调端口和外部资源命名空间。
- 当前 Session Cookie 仍可能跨 `localhost` 端口覆盖；实例化 Cookie 名落地前，并行交互测试使用独立浏览器 Profile。

## 下一步

1. 编码开始前增加轻量 `DF_INSTANCE_ID` Cookie 命名和 PowerShell 实例启动入口，不引入常驻进程管理器。
2. 在 Analysis 和 Recipe 两个分支分别落 M0 探针、最小契约和失败测试。
3. Recipe 基础契约提交后创建 `feat/automation-workbench`。

## 阻塞

当前没有已知阻塞。共享准备提交尚未推送到 `origin`。
