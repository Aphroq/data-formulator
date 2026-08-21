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

锁定的 `trustgraph-base==2.8.14` 已提供原生 `FlowInstance.agent()`、Agent 工具组、`knowledge-query`、`structured-query`、GraphRAG 和 Explainability。此前把目录、实体、rows、本体、triples、SPARQL 六个底层操作直接暴露给 Data Formulator 外层模型，等于在客户端重复实现 TrustGraph 已有的搜索编排；真实验证虽证明传输和各接口可用，但不是合适的产品工具面。

当前产品判断改为：

| 能力 | 产品判断 |
| --- | --- |
| TrustGraph 原生 Agent | 作为外部只读业务上下文检索提供者；知识 Profile 绑定 workspace、Flow、只读工具组和 trace collection，实际检索 collection 由工具组中的查询工具配置，Data Formulator 只调用一次高层查询 |
| `knowledge-query` | 第一版生产工具组的必需能力；由 TrustGraph Agent 按需多轮使用，不直接注册到 Data Formulator |
| `structured-query` | A12 已证明配置和传输可用；现有只读工具组继续保留该能力，不因 A13 尚无依赖场景而移除。Data Formulator 不把它设为第一版必需能力，后续用确实需要受治理结构化记录的场景补充真实验收 |
| Explainability | 已使用锁定 SDK 的 `agent_explain` 实时 provenance，把事件类型归一化成查询轮次/阶段并保留真实 Agent 检索轨迹标识。轨迹不是文档来源，隐藏 thought、observation 正文、参数和原始 triples 不进入前端；只有官方响应明确给出的文档来源才进入 citation |
| 目录、本体、RDF、SPARQL、GraphQL、向量接口 | 保留为 TrustGraph 自身 UI/CLI 或部署诊断能力，不作为 `AnalystAgent` 的六个产品工具 |
| 文档摄取与 Context Core | 继续由 TrustGraph 官方 UI/CLI 管理，Data Formulator 不接入写操作 |

TrustGraph 的 `ontology` 配置是给摄取流程使用的规则：它告诉系统允许抽取哪些类型、属性和关系。原生 Agent 的知识工具搜索的是各自绑定 collection 中已经导入的知识，不会直接把配置项当作业务答案。因此，若希望 Agent 回答某个业务类型的定义、允许关系或 property domain/range，部署方还需要把这些定义、关系及其来源实际装载到相应的可查询 collection，并建立可检索的图实体上下文。此工作属于 TrustGraph 知识准备，不把 ontology/SPARQL 重新暴露成 Data Formulator 工具。

### Collection 事实与 A16 实现结论

锁定的 TrustGraph 版本中，workspace 是授权和所有权边界；collection 是 workspace 内的扁平知识分区，没有父子层级，也不是原始文档目录。GraphRAG、Document RAG、结构化查询和行向量查询每次都接收一个 collection，并没有“自动搜索当前 workspace 下全部 collection”的统一检索参数。Agent 可以跨 collection 工作，但方式是同一个 Agent group 中配置多个分别绑定 collection 的查询工具，由 Agent 根据工具描述选择并按需多轮调用。

`agent_explain(..., collection=...)` 中的 collection 用于 Agent session provenance trace；实际检索范围来自工具组内各查询工具自己的 collection 配置。A16 已把 Data Formulator 目标字段硬切为必填 `trace_collection`，旧 `collection` 字段直接按未知配置失败，不保留开发期兼容别名。该字段只传给 Agent session trace，不充当 retrieval collection 或 collection 清单。

A16 的最小设计是：

- 先按授权和所有权划分 workspace/Profile；当前一次 Agent 调用不跨 workspace。随后在同一 workspace 内按长期治理边界划分 collection，而不是按某次问题划分：发布生命周期不同，或不应共享图关系和检索排名的知识分开；需要在同一图中建立关系并统一检索的同一知识域可以放在一起。Knowledge Core 仍用于复用来源抽取结果，`load_kg_core(id, flow, collection)` 只把同一知识域需要的 Core 装入其版本化 collection，不负责猜测未来问题或合并所有领域。
- Data Formulator 每个请求只解析一个知识 Profile。管理员可提供服务器默认 Profile，当前 identity 可为某个 Data Formulator workspace 保存精确覆盖；Profile 保存 TrustGraph workspace、Flow、只读 Agent group、trace collection 和凭据引用。workspace/bearer 才是授权边界，group 只是本轮 Agent 可见工具的产品路由清单，不新增 IAM。问题到来后由 TrustGraph Agent 选择工具并按需多轮调用，Data Formulator 不保存 retrieval collection 数组、不动态扫描知识，也不实现 fan-out/结果合并。
- 锁定版本的内置知识查询工具把 collection 固定在工具配置中，Agent 不会自动枚举 workspace 下的全部 collection。因此工具组是知识域清单，但不是问题清单；同一治理域只有一个 collection 时可以只配置一个稳定领域工具，存在多个知识域时则使用描述清楚的不同工具名。领域工具名、描述和 group 标签保持稳定，发布新版本时只切换它绑定的 collection；旧版、测试和归档 collection 不同时暴露给 Agent。`structured_query` 保留，行级语义匹配仍不接入。
- 固定任务帧已改为依据本轮实际可见工具的名称和描述选择最小充分集合，不再点名任何内部 action；进度依据官方 provenance 类型和阶段归一化成通用查询轮次，也不再维护工具名 allowlist。

这一步没有增加前端 collection 选择器、TrustGraph 管理 API、第二套路由器或新的 Agent runtime。真实 A16 验收在同一只读 group 中配置了业务术语和制造业本体两个稳定领域工具：单域问题分别只调用对应工具，跨域问题调用两者，`structured_query` 保持可见但未被这些问题误用。另把业务术语工具从 `dfm-business-glossary-v3` 临时切到由同一 Knowledge Core 发布的 `v4`，Data Formulator 的 Profile、请求和工具名均不变，验证后已切回 `v3`。这些仍是验收知识，不冒充企业生产知识。

A13 已完成主路径产品化：目标解析支持 `default` 后备并在请求时核对目标/凭据就绪；当前 Workspace 菜单显示“已配置/未配置”的本地配置状态，该状态不冒充网络健康检查；tool-only Skill 在 registry 中明确列出工具而不是显示“无 action”；完整 `/analyst-streaming` 路径覆盖自动查询、明确规则/机械任务跳过和服务不可用时不编造；前端显示一次业务知识核对进度；`source` 与 `trace` 分开展示；会话续接保留有界最终答案而不是只留下通用成功摘要；Copilot 模型对话框复用已有 capability 结果，并提供显式复测。

这些改动没有引入 TrustGraph 管理 UI、动态目标注册中心、服务端恢复数据库、新的 Agent runtime 或额外查询层。A17 在同一个状态入口增加了当前 Workspace 的轻量连接表单：非 secret Profile 保存在 identity 目录，reader key 进入既有 vault；官方 `flow().list()` 仅在用户显式测试时访问网络，普通状态判断仍只读取本地配置和凭据引用。真正调用失败仍由现有稳定错误合同处理。

A18 为 Copilot 增加了顶部独立连接状态和管理入口，直接复用已有 device-flow 面板，因此连接、等待授权、断开和 identity-scoped vault 生命周期仍只有一套实现。模型对话框继续负责模型选择和显式 capability 复测。两个连接入口改为右侧操作区中的独立图标，避免绝对居中的 Workspace 标题与模型按钮发生点击区域重叠；对应 feature flag 关闭时 Copilot 入口和认证路由仍同时不存在。

A14 的真实 `agent_explain` 探针进一步确认：同一个普通业务问题由 TrustGraph 自动完成两轮检索，每轮实际经过 `grounding → exploration → focus → synthesis → observation`，最终进入 `Conclusion`；本次共收到 17 个 provenance 事件，同时伴随 185 个 `AgentThought` 分片和 243 个 `AgentAnswer` 分片。产品只需要前者的事件类型和轮次，不应把 token 级 thought/answer、observation 正文或参数转发成 UI 步骤。A16 真实事件还表明工具调用可同时声明 `Analysis`、`ToolUse`、`Reflection` 和 `Thought`，锁定 SDK 会把它解析成 `Reflection`；适配器因此只用官方 `rdf:type = tg:Analysis` 精确判断查询开始，不读取 action、thought、参数或原始 triples，也会忽略与查询无关的 `PatternDecision`。产品统一显示“第 N 次业务知识检索”。

A15 已把固定版本的 [IOF 制造业本体](../04-features/analysis-integrations/trustgraph-manufacturing-knowledge.md) 导入 A11/A15 共用的验证 collection：三个官方 RDF 文档共 4,835 条原始 triples，装载后包含 218 个可检索实体上下文。真实中文数据清洗请求自动加载 Skill，并由同一个 TrustGraph Agent 完成两轮检索，正确区分 Production Order、Production Plan 和 Manufacturing Operation。该结果把验收从领域中立合成知识推进到公开制造业知识，但共用 collection 仍含先前合成 fixture，不是干净的生产候选 collection，也不等于企业自己的生产知识已经治理完成。

锁定版本的直接 GraphRAG 响应能返回 IOF 来源，`AgentAnswer` 却不透传内部 GraphRAG 的 source 列表；`agent_explain` 也只提供阶段事件和最终答案。因此当前产品 Agent 路径只显示真实 session trace，不增加第二条低层查询来猜 citation。英文 IOF 索引对直接中文向量检索也不稳定，固定任务帧只做通用处理：首轮缺证且请求语言与索引术语可能不一致时，允许用保持原含义的常用语或英文等价词补查一次，并以请求语言回答；没有写死制造业术语。

`agent_explain` 使用 `/api/v1/socket` WebSocket。当前本机 `https://localhost:9443` 验证代理已透传 Upgrade，官方 SDK 通过同一 allowlisted `api_base` 完成认证、真实一轮/两轮查询和最终答案聚合；没有增加第二个 `socket_base`。本机运行时使用“公共 CA bundle + 本地 TrustGraph CA”的组合证书链，避免为了信任本地 WSS 而破坏 SiliconFlow 等公共 HTTPS 模型端点。

TrustGraph `2.8.14` 的独立 MCP Server 已通过真实 `initialize` 和 `tools/list` 探针，声明 31 个工具，但它不是本项目内部通道。产品继续使用官方 Python SDK 调用原生 Agent；MCP 只作为可选外部互操作入口，不增加第二条内部调用栈。

当前 `2.8.14` flow 镜像的出站 `mcp-tool` 实现仍按旧签名向 `streamable_http_client()` 传 `headers=`，而镜像内 MCP 客户端要求预构造 `http_client=`；真实调用会在查询前抛出参数错误。因此不把 MCP `triples_query`/`sparql_query` 注册到生产 Agent 工具组，也不在本分支修改 TrustGraph 源码或运行时依赖；临时探针配置已删除。

真实探针还发现当前官方生成的 `2.8.14` Compose 中，MCP 默认反向连接 `api-gateway:8888`，而同一部署的 Gateway 实际监听 `8088`；显式覆盖 `--websocket-url ws://api-gateway:8088/api/v1/socket` 后可完成 Gateway 认证。该部署差异应在以后启用 MCP 兼容入口时单独修正，不阻塞 Python SDK 功能切片。

TrustGraph 已提供独立的官方 [`trustgraph-ui`](https://github.com/trustgraph-ai/trustgraph-ui)。其 monorepo 包含 [`@trustgraph/trustkit`](https://www.npmjs.com/package/@trustgraph/trustkit) 组件/设计系统，以及 `@trustgraph/client`、`@trustgraph/react-provider` 和 `@trustgraph/react-state`。npm 实时注册表显示这些库已于 2026-08-18 发布 `2.0.3`；其中 `trustkit` 要求 React 19，而 Data Formulator 仍使用 React 18，完整的 `AgentWithTimelineView` 还会拥有自己的 Agent/session/state 查询链。

同仓库的 `@trustgraph/portal` 不是第四个可嵌入库，而是 `private: true` 的完整 React 19/Vite Workbench 应用：它自行持有登录/API key、WebSocket provider、workspace 同步、QueryClient、路由、主题、状态栏和插件壳。当前 `/agent`、`/explain` 页面只从页面内发起新查询，没有按既有 query/session/explain id 打开的稳定深链。Portal 的同源服务会把 `/api/v1/socket` Upgrade 转发到 Gateway，这支持 A14 对“同一个 `api_base` 同时提供 HTTPS 与 WSS”的判断，但不构成嵌入合同。管理和完整可视化继续独立打开 Portal；本项目只借鉴 `ExplainTimeline` 的紧凑阶段展示和事件分类，不安装 Portal/TrustKit、不复制组件源码、不升级 React、不使用 iframe，也不增加第二条前端查询运行时。

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
