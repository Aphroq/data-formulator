# 项目文档

本项目新增文档按“产品 → 架构 → 交付”三层组织，Feature 工程记录单独归档。下面只列新增部分；Data Formulator 上游已有的 `docs/dev-guides`、`docs/docs-cn` 等目录保持原样。

编码 Agent 进入仓库后先读根目录 [`AGENTS.md`](../AGENTS.md)，再按本页顺序读取对应文档。

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
    status.md
  04-features/
    analysis-integrations.md
    recipe-core.md
    automation-workbench.md
  ...                     # Data Formulator 上游文档，未重组
```

## 阅读顺序

1. [产品目标与范围](./01-product/product-scope.md)：为什么做、做什么、哪些概念不能混用。
2. [现有能力与增量判断](./01-product/current-capabilities.md)：Data Formulator 已有什么、参考材料哪些可采纳、真正缺什么。
3. [系统设计](./02-architecture/system-design.md)：TrustGraph、Copilot、Artifact Lineage、Recipe 和 Automation 如何落地。
4. [实施计划](./03-delivery/implementation-plan.md)：里程碑、分支、纵向切片和验收。
5. [当前状态](./03-delivery/status.md)：现在做到哪里、下一步是什么。
6. Feature 开发时只维护对应工程记录：
   - [Analysis Integrations](./04-features/analysis-integrations.md)
   - [Recipe Core](./04-features/recipe-core.md)
   - [Automation Workbench](./04-features/automation-workbench.md)

## 事实来源

| 问题 | 事实来源 |
| --- | --- |
| 产品范围与术语 | `01-product/product-scope.md` |
| 上游现状和复用边界 | `01-product/current-capabilities.md` |
| 技术契约和状态机 | `02-architecture/system-design.md` |
| 分支、顺序和验收 | `03-delivery/implementation-plan.md` |
| 当前进度 | `03-delivery/status.md` |
| Feature 内的实现、验证和交接 | `04-features/<feature>.md` |

## 维护规则

1. 新结论修改对应层的正文，不在文件末尾追加“补丁说明”。
2. `status.md` 只记录当前状态，不积累工作日志。
3. 代码实现偏离文档时，先更新相应事实来源，再修改代码。
4. 类型、接口和存储格式最终由代码与测试约束；文档描述意图和边界，不复制实现。
5. 暂不增加 ADR、RFC、周报或独立任务文档。只有出现难以逆转的跨层决策时再增加短记录。
6. 每个 Feature 分支只更新自己的工程记录；表格每个有意义的提交或验证节点增加一行，不记录零散操作。
