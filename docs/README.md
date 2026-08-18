# 项目文档

本项目新增文档按“产品 → 架构 → 交付”三层组织，Feature 工程记录单独归档。下面只列新增部分；Data Formulator 上游已有的 `docs/dev-guides`、`docs/docs-cn` 等目录保持原样。

编码 Agent 进入仓库后先读根目录 [`AGENTS.md`](../AGENTS.md)，再按本页顺序读取对应文档。

本页是项目增量文档索引，不替代 Data Formulator 原有指导资料。

```text
docs/
  README.md
  01-product/
    product-scope.md
    current-capabilities.md
  02-architecture/
    system-design.md
  03-delivery/
    implementation-plan.md
    local-multi-worktree.md
    status.md
  04-features/
    analysis-integrations/
      README.md
    recipe-core/
      README.md
    automation-workbench/
      README.md
  ...                     # Data Formulator 上游文档，未重组
```

## 阅读顺序

1. [产品目标与范围](./01-product/product-scope.md)：为什么做、做什么、哪些概念不能混用。
2. [现有能力与增量判断](./01-product/current-capabilities.md)：Data Formulator 已有什么、参考材料哪些可采纳、真正缺什么。
3. [系统设计](./02-architecture/system-design.md)：TrustGraph、Copilot、Artifact Lineage、Recipe 和 Automation 如何落地。
4. [实施计划](./03-delivery/implementation-plan.md)：里程碑、分支、纵向切片和验收。
5. [本机多 Worktree 开发约定](./03-delivery/local-multi-worktree.md)：固定端口、数据目录、浏览器状态和进程隔离。
6. [当前状态](./03-delivery/status.md)：现在做到哪里、下一步是什么。
7. Feature 开发时只维护对应工程记录：
   - [Analysis Integrations](./04-features/analysis-integrations/README.md)
   - [Recipe Core](./04-features/recipe-core/README.md)
   - [Automation Workbench](./04-features/automation-workbench/README.md)

## 上游文档入口

修改具体模块前，除项目文档外还要检索对应上游资料：

| 类型 | 入口 |
| --- | --- |
| 项目介绍和开发规范 | [根 README](../README.md)、[CONTRIBUTING](../CONTRIBUTING.md)、[SECURITY](../SECURITY.md) |
| 后端、模型、Workspace、连接器等开发指南 | [`docs/dev-guides`](./dev-guides/) |
| 中文产品、配置和扩展说明 | [`docs/docs-cn`](./docs-cn/) |
| 测试总览 | [测试 README](../tests/README.md)、[后端测试](../tests/backend/README.md)、[前端测试](../tests/frontend/README.md) |

使用 `rg` 按当前模块和概念检索，不要求一次性通读全部上游文档。

## 事实来源

| 问题 | 事实来源 |
| --- | --- |
| 产品范围与术语 | `01-product/product-scope.md` |
| 上游现状和复用边界 | `01-product/current-capabilities.md` |
| 技术契约和状态机 | `02-architecture/system-design.md` |
| 分支、顺序和验收 | `03-delivery/implementation-plan.md` |
| 同机多分支运行资源分配 | `03-delivery/local-multi-worktree.md` |
| 当前进度 | `03-delivery/status.md` |
| Feature 内的实现、验证和交接 | `04-features/<feature>/README.md` |

## 维护规则

1. 新结论修改对应层的正文，不在文件末尾追加“补丁说明”。
2. `status.md` 只记录当前状态，不积累工作日志。
3. 代码实现偏离文档时，先更新相应事实来源，再修改代码。
4. 类型、接口和存储格式最终由代码与测试约束；文档描述意图和边界，不复制实现。
5. 暂不增加 ADR、RFC、周报或独立任务文档。只有出现难以逆转的跨层决策时再增加短记录。
6. 每个 Feature 分支只更新自己的工程记录；表格每个有意义的提交或验证节点增加一行，不记录零散操作。
