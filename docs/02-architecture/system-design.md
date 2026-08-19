# 系统设计

## 设计目标

在不改变 Data Formulator 核心交互模型的前提下，增加可信上下文、确定性 Recipe 和轻量后台运行。

系统只保留一个 `AnalystAgent`。TrustGraph 的只读目录和查询能力作为 Skill 接入；知识摄取、Context Core 管理和完整图谱工作台继续使用 TrustGraph 官方 UI，不在 Data Formulator 建立第二套管理面。GitHub Copilot 是 LiteLLM provider。这些分析集成不进入正常 Recipe Run。

## 核心原则

1. 智能用于探索，确定性用于执行。
2. 无持久化血缘就不允许自动化。
3. Schedule 固定不可变 RecipeVersion，运行计划不静默变化。
4. 参数只绑定到 typed slot，不替换任意 Python/SQL 字符串。
5. 外部集成和持久化能力不足时失败关闭。
6. 第一版只解决同主机可靠运行，不抽象分布式平台。

## 总体结构

```text
Data Thread / AnalystAgent
  ├─ Local Knowledge
  ├─ TrustGraph Skill（目录、语义搜索、RDF、SPARQL、结构化行）
  └─ LiteLLM Models（可选 Copilot OAuth）
             │
             ▼
      Artifact Lineage Ledger
             │
             ▼
 Recipe Compiler → Dry Run → Published RecipeVersion
                                │
                    Manual Run / Schedule
                                │
                                ▼
                  Worker → Run Manifest / Inbox
```

部署单元：

- 以本机进程运行的现有 Data Formulator Web 应用。
- 以本机进程运行的一个新增 `data_formulator_worker` 入口。
- 一个自动化 SQLite 数据库。
- Web 和 Worker 都能访问的持久化 Workspace/Artifact Store。

### 开发与运行环境

- 不使用 Docker、Docker Compose 或容器化服务。
- 不新增镜像、Compose 配置或基于容器的本地依赖。
- 上游已有容器相关文件原样保留，不纳入本项目默认开发和验收路径。
- 数据库和 TrustGraph 验证使用用户已有环境、明确提供的外部端点或测试替身。
- Web、Worker、SQLite 和前端工具链均直接在本机运行。

## 分析集成

### TrustGraph 本体与知识图谱

TrustGraph 作为现有 AnalystAgent 的可选知识 Skill，不作为第二个 Agent，也不通过 Graph RAG 生成答案。第一版固定使用官方 `trustgraph-base==2.8.14` Python API，复用其 `Api`、`Config`、`Flow`、`Collection`、`Library`、`Knowledge`、RDF schema 和 translator，并调用 TrustGraph 已开放的结构化接口：

- workspace-scoped `config` 的 `list/get`，读取服务器绑定的 `ontology` 配置；
- collection、flow、document、processing 和 Knowledge Core 列表，形成可发现的知识目录；
- flow-scoped embeddings 与 `graph-embeddings`，用自然语言发现相关图实体；
- flow-scoped `triples`，按 subject/predicate/object 和命名图查询 RDF 事实；
- 官方 `FlowInstance.sparql_query()`，执行 `SELECT`、`ASK`、`CONSTRUCT`、`DESCRIBE`；
- `rows_query()`，执行只读 GraphQL 结构化查询并返回 JSON；当前阶段不写 Data Formulator 表或 Workspace，不接同步/刷新；
- `urn:graph:source` 中的 W3C PROV-O 抽取溯源仍通过同一图查询面读取。

查询 Skill 不暴露 TrustGraph Agent、GraphRAG、DocumentRAG、text completion、`row_embeddings_query()`、通用配置修改、文档摄取或 Knowledge Core 写操作。文档摄取、Processing、Context Core 装卸和完整知识图谱可视化继续由官方 `trustgraph-ui` 负责。读取目录、本体、事实、GraphQL 结构化行和溯源本身不要求 TrustGraph 生成自然语言答案。

#### TrustGraph SDK 与 MCP 边界

产品内部主通道使用已锁定的官方 Python SDK，而不是再增加一条 MCP 客户端调用栈：

- Python SDK 已覆盖目录、语义搜索、RDF、SPARQL、GraphQL rows、Library、Knowledge Core、Explainability 和 bulk 接口；本项目只接入既定只读子集；
- `graph_embeddings_query(text, ...)` 在语义上属于“生成 embedding → 查询 graph embeddings”的组合，`2.8.14` 高层同步实现存在返回形状错误时，只允许用同一官方 `FlowInstance.request()` 拆成这两个官方服务调用，不另写向量算法；
- 独立 `trustgraph-mcp` 服务适合让其他 MCP 客户端连接 TrustGraph，或未来作为部署兼容模式；它不为当前 Python 后端增加独有的产品知识能力；
- MCP 的 31 个原始工具包含 prompt、token cost、flow 运维和另一套 Agent 等非分析工具，不能直接全部注入 `AnalystAgent`。

真实 `2.8.14` 探针已完成 MCP `initialize` 与 `tools/list`。当前官方生成部署的 MCP 默认 Gateway 地址为 `api-gateway:8888`，而实际 Gateway 监听 `8088`；覆盖 `--websocket-url` 后认证链路成立。MCP 端到端工具调用在该外部实验环境中仍受消息总线恢复状态影响，因此不作为当前产品主通道的完成证据。

#### TrustGraph 官方 UI 边界

官方 `trustgraph-ui` 是 React 19 + Vite 的独立应用，并提供已发布到 npm 的 `@trustgraph/trustkit` 组件/设计系统、TypeScript client、React provider 和 state hooks。`trustkit@2.0.3` 要求 React 19，与 Data Formulator 的 React 18 基线不一致。第一版不复制组件源码、不升级整个 Data Formulator React 栈，也不把浏览器改为直连 TrustGraph WebSocket；需要管理或完整可视化时直接打开独立官方 UI，Data Formulator 不增加 TrustGraph 前端入口。

TrustGraph 目标配置继续复用已经实现的目标映射，至少包含：

- API base URL、flow id、collection 和允许的 ontology id；
- credential reference；
- Data Formulator workspace 到允许目标的显式映射；
- 分离的 connect/read timeout；
- 最大 SPARQL 长度、最大结果数和最大响应大小。

真实 TrustGraph workspace 由 bearer token 授权，并由服务端目标映射固定；模型和前端不得指定 base URL、flow、collection、workspace、ontology id 或凭据。SPARQL 在本地用 `rdflib` 确认是查询语句并拒绝 `SERVICE`，再交给 TrustGraph 的只读 query endpoint；三元组查询只接受类型化 RDF term 和有界 limit。

官方 2.8.14 高层 `triples_query()` 不暴露命名图 `g`，因此只有 knowledge/provenance 三元组查询通过官方 `FlowInstance.request()` 补入 `g`；SPARQL 直接使用官方 `FlowInstance.sparql_query()`。真实 `2.8.14` 部署验证 SDK 使用的 `service/sparql` 可用，而在线 REST 路径 `service/sparql-query` 返回 404，以锁定包和真实部署合同为准。官方 `Api.request()` 不提供 Session 注入和禁止重定向选项，项目以受限子类保留其对象模型和请求合同，同时补充 allowlist、TLS、禁止重定向、分离 connect/read timeout 和稳定错误分类。

结果以结构化知识目录、本体、实体匹配、RDF term、triple/quad、SPARQL binding 或 GraphQL rows 进入模型，不把图压平成上游生成的自然语言答案。GraphQL rows 当前只作为查询证据，不进入 Data Formulator 表、Workspace、同步或刷新链路。URI 和溯源项继续使用已经存在的供应商无关引用通道。既有凭据解析、结果边界和引用处理作为基础设施保留，但不再作为后续 TrustGraph 功能切片或验收的主目标。

### 通用引用通道

不在 AnalystAgent 中硬编码 TrustGraph：

- `SkillContext` 增加明确的 identity/workspace 信息。
- `ToolResult` 增加结构化 `context_items` 或 `citations`。
- Agent 把清洗后的引用作为 `context_info` 事件发送。
- 前端把引用持久化到对应 Data Thread 消息或产物，而不是只显示在瞬时 thinking step。

### GitHub Copilot

继续使用现有 LiteLLM Client：

- `auth_mode` 增加 `oauth_device`。
- 模型注册表允许没有 API key 的 OAuth endpoint。
- Client 正确解析 provider/model 前缀。
- 可用性检查从文本 ping 升级为能力探测，至少记录 chat、streaming 和 tools。
- OAuth token 进入安全存储和 provider 刷新流程，不进入前端状态、日志或 Recipe。

M0 在当前锁定的 LiteLLM `1.91.3` 上验证真实登录、普通对话、工具调用、流式返回和 token 刷新。失败时保持 feature flag 关闭，不先升级依赖掩盖问题。

## Artifact Lineage

### 权威 ArtifactNode

后端在产物成功写入后记录不可变节点：

- `artifact_id`、`artifact_type`、`identity_id`、`workspace_id`。
- `parent_ids`。
- `content_hash`、`schema_fingerprint`。
- DataOperation id/plan hash、代码 hash、chart spec hash 等执行引用。
- 创建时间、来源会话和输入可刷新性。

记录点：

- `load`：DataOperation 成功发布表后，引用完整选定 plan，不使用前端摘要。
- `transform`：Sandbox 成功且输出表写入后，记录代码、输出变量、父表和 hash。
- `chart`：图表成功生成时，记录规范化 chart spec、table artifact 和 hash。
- `report`：报告保存时记录 chart artifact；报告可以是输出包装，但不是执行步骤。

现有 HMAC `codeSignature` 用于验证代码未被篡改。Recipe 另外保存稳定 SHA-256，用于版本和可重复性比较。

### 为什么不能直接使用前端刷新链

现有 `useDataRefresh` 和 `useDerivedTableRefresh` 提供了可复用行为，但其触发、依赖发现和状态主要位于浏览器。Worker 不应伪造 Redux 状态或 React 生命周期。

后端 Recipe 层可以复用：

- DataOperationExecutor。
- Workspace 表读写和 DuckDB。
- Sandbox。
- 代码 HMAC 验证。
- 既有表 metadata/content hash。

必须新建：

- 权威 Artifact ledger。
- 稳定依赖遍历。
- request-independent workspace opener。
- 分步骤 Executor 和 Run 事件。

## Recipe Core

### Compiler

Compiler 只接受一个或多个目标 artifact id：

1. 从 ledger 向上遍历全部祖先。
2. 验证节点存在、hash 一致、输入模式可解析。
3. 稳定拓扑排序，生成 `load`、`transform`、`chart`。
4. 对代码、chart spec 和整个 Recipe 使用统一 canonical JSON + SHA-256。
5. 生成机器执行的 Recipe JSON 和供人阅读的 Workflow Markdown。

相同 artifact 集合必须生成字节级稳定的规范和 hash。Workflow Markdown 不反向参与执行。

### RecipeSpec v1

最小内容：

- `schema_version`、`recipe_id`、`version_id`、名称和说明。
- 创建者、workspace、目标 artifact。
- 有序 steps 和显式 dependencies。
- typed parameters 与 bindings。
- 输入模式和 credential reference。
- 每一步的输入输出、执行内容、hash 和期望 schema。
- 最终输出、compiler version 和 recipe hash。

输入模式：

| 模式 | 行为 |
| --- | --- |
| `refreshable` | 使用保存的连接器操作和 credential reference 重新加载 |
| `pinned_snapshot` | 使用固定 content hash 的 Workspace 快照 |
| `external_path` | 仅桌面模式允许，发布时验证路径策略 |
| `unresolved` | 允许保存草稿，禁止通过 dry run、发布和调度 |

参数只能绑定到预定义的连接器字段、过滤值和日期范围等 typed slot。

### 生命周期

```text
draft → validated → published → archived
```

- 编译结果初始为 `draft`。
- dry run 成功且 manifest/hash/schema 校验通过后为 `validated`。
- 只有 validated 版本可发布。
- Published RecipeVersion 不可修改；变更产生新版本。
- Schedule 固定一个 published version。

### 确定性 Executor

- `load` 复用 DataOperationExecutor 或固定快照。
- `transform` 验证代码 hash/HMAC 后使用现有 Sandbox。
- `chart` 使用已保存规范生成确定性结果。
- 每步写 `events.jsonl`，最终原子写 `manifest.json`。

正常 Run 禁止调用 LLM、TrustGraph、Workflow Replay、重新生成代码或自动改变步骤。Schema 漂移、输入不可解析或关键输出不匹配时进入 `needs_review`。

Agent 可以在用户打开 Needs Review 后解释异常或提出修复建议；用户确认并重新分析后，Compiler 产生新 RecipeVersion。

## Automation

### 数据模型

SQLite 第一版只保留四张主表：

- `recipes`
- `recipe_versions`
- `schedules`
- `runs`

数据库固定在 `DATA_FORMULATOR_HOME/automation/automation.db`。Web 和 Worker 解析到同一绝对路径，启用 WAL、`busy_timeout`、foreign keys、显式事务和顺序 migration。

`runs` 对 `(schedule_id, scheduled_for)` 建唯一约束，防止重复入队。

### Scheduler 与 Worker

- Scheduler 扫描到期 Schedule，事务性创建 queued Run。
- Worker 通过 lease 领取 Run 并定期续租；过期 lease 可恢复。
- 初始并发 1，允许显式配置到 2。
- 只对明确瞬时错误自动重试，最多 2 次。
- queued/running 可取消，运行中按步骤边界响应。
- Worker 使用 request-independent opener 打开明确 identity/workspace，不伪造 Flask 请求。

Run 状态：

```text
queued | running | succeeded | failed | needs_review | cancelled
```

## 持久化边界

Recipe spec、代码、Workflow Markdown、Run events 和 manifest 必须进入 durable artifact store，不能写入 `confined_scratch`。

第一版默认只启用同主机持久化 local Workspace：

- Ephemeral Workspace 拒绝发布和调度。
- SQLite 不放在单个 Workspace 内。
- 不声称支持网络共享盘 SQLite。
- 现有 Workspace ZIP 继续负责交互分析现场，不默认携带自动化数据库。

若首发必须支持 Azure Blob，应先给 Workspace 增加正式的通用 artifact read/write 接口和 Azure 实现，不能调用私有方法或把本地 scratch 当作持久化。

## API 与 UI

最小 API：

- Recipe：compile、get/list、dry-run、publish、archive。
- Schedule：create/update、enable/disable、list。
- Run：manual enqueue、list/get、cancel、manifest/events。

三个新增 UI 入口：

1. Data Thread 中统一的 Artifact action：`Save as Recipe`。
2. Recipes 页面：版本、输入、步骤、dry run、发布和 Schedule 设置。
3. Runs Inbox：状态、Needs Review、错误、日志和输出链接。

现有 Workflow Replay 保持原入口和名称。Save as Recipe 与 Replay 不共用一个动作。

TrustGraph 不新增自制工作台页面或导航入口。SPARQL、GraphQL、Ontology、图谱浏览、摄取和 Context Core 管理均在独立官方 `trustgraph-ui` 中完成。

当前代码没有独立通用 Sidebar；路由和导航修改落在真实的 `src/app/App.tsx` 等现有入口。

## Feature flags 与安全

独立且默认关闭：

- `TRUSTGRAPH_ENABLED=false`
- `GITHUB_COPILOT_ENABLED=false`
- `AUTOMATION_ENABLED=false`

Automation 关闭时不启动 Scheduler/Worker，API 和 UI 都不可用。

安全要求：

- Secret 只保存引用或进入现有 credential vault。
- TrustGraph base URL 使用 allowlist/SSRF 防护和 TLS 校验；所有 Analyst Skill 操作保持只读。
- 日志清洗 token、连接串和敏感参数。
- Recipe 代码同时验证签名和内容 hash。
- Worker 每个 Run 使用隔离目录和明确 workspace。
- 外部上下文没有指令优先级。

## 建议模块边界

```text
py-src/data_formulator/
  analyst/skills/business-context/
    SKILL.md
    tools.json
    skill.py
  knowledge/business_context.py
  recipes/
    models.py
    lineage.py
    compiler.py
    repository.py
    artifact_store.py
    executor.py
  automation/
    db.py
    scheduler.py
    worker.py
  routes/
    recipes.py
    schedules.py
    runs.py

src/
  api/recipes.ts
  components/ArtifactActionsMenu.tsx
  views/Recipes.tsx
  views/RunsInbox.tsx
```

这是职责边界，不要求预先创建全部空文件。每个文件应随契约或测试一起出现。
