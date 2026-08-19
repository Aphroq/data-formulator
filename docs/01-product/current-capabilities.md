# 现有能力与增量判断

## 核对基线

| 组件 | 固定版本 |
| --- | --- |
| Data Formulator | `0.8.0b1` / `5477f0e236426dc8f74a498ec400414fba7fbc0f` |
| TrustGraph 服务源码 | `0bcfe9377c3d55b7199c16335b9e52ed91286233` |
| TrustGraph Python API | `trustgraph-base==2.8.14` |
| LiteLLM | Data Formulator `uv.lock` 中的 `1.91.3` |

TrustGraph 的 `release/v2.8` 是移动分支。开发、测试和问题复现记录完整提交号，不只记录分支名。

## 对补充参考材料的判断

参考材料的核心结论成立，并已纳入项目范围：

- Data Formulator 已有成熟的会话恢复，不需要重新实现“项目保存”。
- Workflow Replay 是 Agent 语义重做，不是确定性复现。
- 已有页面内自动刷新和签名 Python 代码重跑，可以复用底层能力。
- 现有定时刷新不是后台 Scheduler。
- Workspace 导入导出、数据导入和常用结果导出应直接保留。
- 真正的增量是 Artifact Lineage、RecipeVersion、Run、Schedule 和 Worker。

需要修正或收紧的地方：

1. 现有刷新逻辑主要在 React Hook 中，不能直接视为后端 `RecipeExecutor`。
2. 派生刷新只检测非派生源表的 hash，并刷新直接依赖项；它不是任意深度 DAG 调度器。
3. HMAC 签名证明代码未被篡改，不锁定输入、参数、环境和输出，因此不等于可复现。
4. Agent 可以生成解释、Workflow 和人工修复建议；机器 Recipe 必须由确定性 Compiler 从 Artifact Lineage 生成。
5. Agent 不得在定时 Run 中自动修复和继续。异常进入 Needs Review，由用户确认后产生新 RecipeVersion。
6. Workspace ZIP 不含自动化 SQLite 中的 Recipe/Run 元数据，因此不能默认宣称会迁移完整自动化项目。

## 能力矩阵

| 能力 | 当前实现 | 规划判断 |
| --- | --- | --- |
| 会话恢复 | 3 秒 debounce 保存可序列化 Redux 状态；打开 Workspace 时恢复 | 直接复用 |
| Workflow Replay | WorkflowDistillAgent 生成 Markdown；前端一次请求交给 Agent 重做 | 保留为语义重放 |
| 源数据刷新 | URL/可刷新数据库支持手动或定时轮询 | 保留交互体验 |
| 派生表刷新 | SQL View 重采样；签名 Python 代码重跑 | 复用 Sandbox/签名，重建后端编排 |
| Workspace 导入导出 | ZIP 保存清洗后的状态和 Workspace snapshot | 直接复用，暂不承载 Recipe/Run |
| 数据导入 | 上传 CSV/TSV/JSON/Excel；Local Folder 另支持 Parquet/JSONL | 直接复用 |
| 结果导出 | 表格 CSV/TSV；报告 PNG、打印 PDF、HTML/文本复制 | 直接复用 |
| 后台 Cron | 无 | 新增 |
| Recipe 版本 | 无 | 新增 |
| Run 审计 | 无 | 新增 |

## TrustGraph 能力与接入判断

当前分支已经通过官方 `trustgraph-base==2.8.14` 接通知识目录、图实体语义检索、绑定本体、类型化 RDF 三元组、命名来源图和 SPARQL。锁定的 Python 包还直接提供以下现成接口：

| 能力 | 官方 Python API | 产品判断 |
| --- | --- | --- |
| 知识目录 | collection、flow、document、processing、Knowledge Core 列表 | A8 已接入只读 Skill，先让 Agent 知道有哪些知识可用 |
| 图实体语义搜索 | `graph_embeddings_query` / embeddings + graph-embeddings | A8 已接入只读 Skill，先发现实体再展开关系 |
| 结构化行 | `rows_query`、`row_embeddings_query`、`structured_query` | 只接入确定性的 GraphQL rows 读取；`row_embeddings_query` 明确不接入，也不导入 Data Formulator 表或做同步 |
| 文档检索 | `document_embeddings_query` | 在需要原文片段时作为图谱事实的补充，不替代本体/RDF 主路径 |
| 文档与 Context Core | Library processing、Knowledge Core load/unload、bulk import/export | Data Formulator 不接入写操作；继续由 TrustGraph 官方 UI/CLI 管理，Skill 仅查看只读目录 |
| TrustGraph 自带回答 | GraphRAG、DocumentRAG、Agent、text completion | 不接入；避免形成第二个回答 runtime |

TrustGraph `2.8.14` 的独立 MCP Server 已通过真实 `initialize` 和 `tools/list` 探针，声明 31 个工具，能够向任意外部 MCP 客户端公开查询和管理能力。但它不是本项目获得上述能力的必要条件：当前 Python 后端已经安装官方 SDK，SDK 的结构化查询、行/文档语义搜索、Explainability 和 bulk 接口比该版本 MCP 工具面更完整。现阶段采用“官方 Python SDK 为产品主通道、MCP 为可选外部互操作入口”，不同时维护两条内部调用栈。

真实探针还发现当前官方生成的 `2.8.14` Compose 中，MCP 默认反向连接 `api-gateway:8888`，而同一部署的 Gateway 实际监听 `8088`；显式覆盖 `--websocket-url ws://api-gateway:8088/api/v1/socket` 后可完成 Gateway 认证。该部署差异应在以后启用 MCP 兼容入口时单独修正，不阻塞 Python SDK 功能切片。

TrustGraph 已提供独立的官方 [`trustgraph-ui`](https://github.com/trustgraph-ai/trustgraph-ui)。其 monorepo 包含 [`@trustgraph/trustkit`](https://www.npmjs.com/package/@trustgraph/trustkit) 组件/设计系统，以及 `@trustgraph/client`、`@trustgraph/react-provider` 和 `@trustgraph/react-state`。npm 实时注册表显示这些包已于 2026-08-18 发布 `2.0.3`；其中 `trustkit` 要求 React 19，而 Data Formulator 仍使用 React 18。管理和完整可视化直接使用独立官方 UI，本项目不复制组件、不升级 React，也不增加 TrustGraph 前端入口。

## 会话恢复不是执行

`useAutoSave.tsx` 使用 3000 ms debounce，把去除敏感和瞬时字段后的状态保存到当前 Workspace 的 `session_state.json`。打开 Workspace 时，前端恢复输入表、派生表、图表、报告、线程和其他可持久状态，再从 Workspace 读取表数据。

这支持“继续工作”和“迁移已有结果”，但没有重新执行步骤、验证输入或生成 Run 记录。

源码：

- [自动保存](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/app/useAutoSave.tsx)
- [Workspace 状态恢复](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/app/dfSlice.tsx)

## Workflow Replay 是语义重放

`WorkflowDistillAgent` 从分析上下文提炼 Goal、Parameters、Abstract workflow、Concrete workflow 和 Notes。Replay 时，`SimpleChartRecBox.tsx` 把整份 Workflow 作为一次提示直接交给 Data Agent，源码明确描述为“one request, let the agent reproduce”。

因此它适合把分析思路应用到相似或不同数据，但允许字段映射、代码和图表发生变化，不能用于审计或后台确定性运行。

源码：

- [Workflow 提炼](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/agents/agent_workflow_distill.py)
- [Replay 入口](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/SimpleChartRecBox.tsx)

## 页面刷新链不是 Scheduler

`useDataRefresh.tsx` 使用递归 `setTimeout`：

```text
页面保持运行
  → 到达刷新间隔
  → 获取 URL/数据库新数据
  → 比较内容 hash
  → 更新源表
  → 重跑直接依赖的派生表
```

SQL View 通过 DuckDB 重新采样；Python 派生表把已保存代码和服务器 HMAC 签名提交到后端，经现有 Sandbox 重跑。这个机制有实际复用价值，但仍缺少后台进程、持久化调度、步骤状态、超时、重试、版本和输出验收。

页面关闭、浏览器限制计时器或服务重启后，都没有可恢复的任务。

源码：

- [自动刷新与派生刷新](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/app/useDataRefresh.tsx)
- [签名代码重跑接口](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/routes/agents.py)

## 导入导出边界

普通上传支持 CSV、TSV、JSON、`.xlsx` 和 `.xls`。Local Folder connector 另支持 Parquet、JSONL 及上述格式。现有 Workspace ZIP 包含 `state.json` 和 `workspace/` snapshot，其中可有 `workspace_meta.json`、`workspace.yaml`、`session_state.json` 和数据文件；导出前会清除模型、身份、连接参数等敏感字段。

现有产品导出包括：

- 表格 CSV，后端也支持 TSV delimiter。
- 报告 PNG。
- 通过浏览器打印流程生成 PDF。
- 报告 HTML + 纯文本复制。

当前没有 Recipe、Run 审计包、定时投递，以及 Excel/Parquet/JSON 表格导出入口。第一版不把这些相邻需求并入核心闭环。

源码：

- [上传入口](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/UnifiedDataUploadDialog.tsx)
- [Workspace 导入导出路由](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/routes/sessions.py)
- [ZIP 实现](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/datalake/workspace.py)
- [表格导出](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/routes/tables.py)
- [报告导出](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/ReportView.tsx)

## 对实现范围的直接影响

- 不重做会话、Workflow Replay、数据导入和现有导出。
- Recipe Core 复用 DataOperation plan、Sandbox、代码签名和 Workspace 表能力，但不依赖前端 Hook 作为执行器。
- 后端新建权威 Artifact ledger，才能把现有交互结果编译成固定 Recipe。
- Automation 只增加持久化 Schedule、Run、Worker 和恢复机制。
- Workflow Replay 与 Recipe 在 UI 和术语上明确分开。
