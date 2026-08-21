# Analysis Integrations 实施方案

## 1. 文档状态

| 项目 | 内容 |
| --- | --- |
| 适用分支 | `feat/analysis-integrations` |
| 固定上游基线 | Data Formulator `0.8.0b1` / `5477f0e236426dc8f74a498ec400414fba7fbc0f` |
| 当前目标 | 在同一个 `AnalystAgent` 与 Data Formulator 工作区中增加一个 TrustGraph 原生 Agent 驱动的业务上下文查询能力和可选 GitHub Copilot 模型 |
| 当前实施节点 | A13 主路径、A14 `agent_explain` 实时查询步骤、A15 IOF 制造业知识验收和 A16 Collection/Profile 收敛均已完成 |
| 外部验证节点 | reader bearer、保留 `structured-query` 的专用只读工具组、分域版本化 collection、Qwen Flow、non-thinking 部署和 9443 HTTPS/WSS 入口均已生效；A16 已完成单域、跨域和稳定工具版本切换/回滚验收 |
| 最后更新 | 2026-08-21 |

本文把项目级架构约束细化为 Analysis Integrations 分支可执行的代码、测试和验收计划。项目事实来源仍以当前检出源码和测试为准；实现决定变化后，应同时更新本文和同目录工程记录。

## 2. 目标与非目标

### 2.1 交付目标

1. 建立供应商无关的业务上下文结果、稳定错误和结构化引用契约。
2. 将 Data Formulator 后端已经授权的 identity 和 workspace 明确传入 Skill，不从模型参数或前端 payload 推断。
3. 通过一个 `query_business_context(question, context?)` 把业务语义缺口交给 TrustGraph 原生 Agent；用户和外层模型不需要掌握图谱查询术语。
4. TrustGraph Agent 使用服务器知识 Profile 绑定的只读工具组，自行按需一轮或多轮调用 collection-bound 查询工具；group 列出该 workspace 内本轮可见的长期知识域，Agent 在问题到来后选择一个或多个工具，不预先为未知问题拼装跨域总集合。现有只读组继续保留 `structured_query`，Data Formulator 不把它设为第一版依赖，后续以真实受治理结构化记录场景单独验收。
5. 查询只发送聚焦问题与最小相关上下文；只消费最终答案和真实 provenance trace，不消费隐藏思考链，也不从任意 URI 猜来源。
6. 将引用从 Skill 结果送入 Agent 流，并持久化到 Data Thread 的对应消息或产物。
7. 在现有 LiteLLM Client 路径中接入 GitHub Copilot device flow，不引入 Copilot SDK 或第二套 Agent runtime。
8. 对 Copilot 模型逐个探测 chat、streaming 和 tools 能力，只注册符合当前 `AnalystAgent` Chat Completions 契约的模型。
9. 复用官方 `trustgraph-ui` 承担管理和完整图谱可视化，不在 Data Formulator 复制工作台。
10. 保证 `TRUSTGRAPH_ENABLED=false` 和 `GITHUB_COPILOT_ENABLED=false` 时没有残留 Skill、API、模型或 UI 行为。
11. 在长耗时或多轮 TrustGraph 查询中，通过现有 Data Thread 运行步骤实时显示真实查询轮次和有限阶段；成功 trace 保留查询轮数，但不展示隐藏思考、observation 正文、工具参数或原始 provenance。

### 2.2 明确不做

- 不实现 Recipe、Schedule、Run、Worker 或后台 Executor。
- 不把 `row_embeddings_query()` 或其他 TrustGraph 底层查询直接暴露给 Data Formulator 外层模型。
- 不在 Data Formulator 暴露文档摄取、processing、Knowledge/Context Core load/unload/bulk 或其他 TrustGraph 写操作。
- 不安装、复制、vendoring 或重写 TrustGraph 官方工作台/TrustKit 组件；需要管理和完整可视化时使用独立官方 `trustgraph-ui`，实时步骤只借鉴 ExplainTimeline 的交互模式。
- 不让浏览器直连 TrustGraph WebSocket，不增加第二个前端 Agent/session/state 运行时，也不为当前本机代理问题新增 `socket_base`、SSE 或另一条流式路由。
- 不增加 TrustGraph 目标选择器、动态租户注册中心、摄取管理页、服务端暂停恢复数据库或新的健康检查服务。
- 不让 Data Formulator 动态枚举 TrustGraph workspace、接受 retrieval collection 数组、并发 fan-out 或自行合并跨 collection 排名；collection 路由由 TrustGraph Agent group 的工具配置负责。
- 不在正常 Recipe Run 中调用 LLM、TrustGraph 或 Workflow Replay。
- 不把 GitHub access token、Copilot 短期 token 或 TrustGraph bearer token写入前端状态、日志、Recipe、普通配置文件或测试夹具。
- 产品实现和默认开发/回归不使用 Docker、Docker Compose、LiteLLM Proxy、Copilot SDK 或额外消息基础设施；用户明确授权的仓库外 WSL2 验收环境不进入产品依赖。
- 第一版不注册 LiteLLM 标记为 Responses-only 的 Copilot 模型。

### 2.3 功能优先调整（2026-08-19）

后续实施以用户能直接使用的知识能力为里程碑，不再为凭据隔离、输出大小限制或引用清洗单独开新切片。A0-A7 已形成的相关基础设施保持现状并作为回归边界；A8/A9/A11 的六个底层接口与真实数据验证保留为历史技术证据，不再定义产品工具面。2026-08-20 的 A12 决定以本节、项目系统设计和 A12 切片为当前事实；后文 A0-A11 中描述的六工具结构只用于解释历史实现与验证，不再约束最终实现。A13 不重写 A12，而是在相同单工具合同上完成最小产品化收口。A14 也不扩大查询面，只把同一次高层调用从终态 REST 响应切换为官方 explain iterator，并沿用已有流和 UI 展示真实进度。

TrustGraph 内部接入继续复用官方 Python SDK。A13 当前实现调用原生 `service/agent` 终态响应；A14 改为同一 SDK 的 `agent_explain` WebSocket iterator，以取得真实 provenance 和最终答案。官方 MCP server 适合给外部 MCP 客户端提供兼容能力；本项目不增加 MCP transport、会话和工具参数转换层，也不在 Data Formulator 重写 TrustGraph 的 Agent loop。

## 3. 已核对的现状与约束

### 3.1 当前代码事实

- `AnalystAgent` 已从后端路由接收 identity/workspace，并通过与自由 payload 分离的 `SkillAuthorization` 注入所有 Skill 调用。
- `ToolResult` 已兼容增加供应商无关的 `context_items`、`public_summary` 和稳定 `error_code`；外部正文只进入当前内存中的模型观察，流、恢复轨迹和 Reasoning log 使用清洗后的摘要。
- Skill registry 已支持通用 `enabled_if` 前置门；`TRUSTGRAPH_ENABLED=false` 时不会导入或注册 TrustGraph Skill。
- 前端已把结构化引用按生成时点绑定到 `InteractionEntry`，并把整轮引用绑定到最终 `TextTurn`；既有 Redux、Session 恢复和 ZIP 导入导出链路原样持久化可选字段。
- Copilot device flow 已由独立、默认不注册的 Data Formulator endpoint 驱动；pending device code 只在有上限的服务端内存中，长期 GitHub access token 进入 identity-scoped credential vault。
- LiteLLM Copilot 内置 Authenticator 不直接用于模型请求；A5 用版本/源码指纹保护的方法适配和 `ContextVar` 将当前 identity 的 token 限制在单次调用及惰性 stream `next()` 中，调用上下文外失败关闭且不创建共享 token 文件。
- 模型注册表已把 Copilot 从通用 `*_ENABLED` secret provider 中分离：flag 打开且 `GITHUB_COPILOT_MODELS` 明确列出候选时才进入服务端探测；候选不会在当前 identity 三项能力全部通过前出现在公开模型列表。

### 3.2 固定外部合同

TrustGraph M0-A 固定使用 Windows 可直接安装的官方 `trustgraph-base==2.8.14`，并复用其 `Api`、`ConfigKey`、`FlowInstance`、RDF schema 和 translator：

- 本体配置：`POST /api/v1/config`，使用官方 `Api.config().get([ConfigKey(type="ontology", key=...)])`。
- 三元组：`POST /api/v1/flow/{flow}/service/triples`，支持 S/P/O、collection、limit 和命名图 `g`；来源图固定为 `urn:graph:source`。
- SPARQL：官方 `FlowInstance.sparql_query()` 调用 `POST /api/v1/flow/{flow}/service/sparql`；只允许 `SELECT`、`ASK`、`CONSTRUCT`、`DESCRIBE`，拒绝更新和 `SERVICE`。
- bearer token 是授权边界；请求中的 TrustGraph `workspace` 只用于路由，不能直接使用模型或前端提交的 Data Formulator workspace id。
- RDF 响应保留 IRI、blank node、literal datatype/language、RDF-star quoted triple 和 graph，而不是压平成自然语言文本。
- 知识目录：`Api.flow().list()`、`Api.collection().list_collections()`、`Api.library().get_documents()/get_processings()`、`Api.knowledge().list_kg_cores()`。
- 图实体语义检索：先用 `FlowInstance.embeddings([text])` 取得向量，再请求同一 Flow 的 `service/graph-embeddings`；结果保留 RDF term 和 score。
- 结构化查询：只复用 `rows_query()` 执行显式 GraphQL；返回 `data/errors/extensions`，不调用 `structured_query()`/`nlp_query()`，不写 Data Formulator 表或 Workspace。
- UI：管理、摄取、Context Core 和完整知识图谱可视化使用独立官方 `trustgraph-ui`；Data Formulator 只保留查询 Skill，不增加 TrustGraph 前端入口。

合同证据以官方 [Python packages](https://docs.trustgraph.ai/reference/python-packages.html)、[Python API](https://docs.trustgraph.ai/reference/apis/python)、[REST API](https://docs.trustgraph.ai/reference/apis/rest)、[Ontology configuration](https://docs.trustgraph.ai/reference/configuration/ontologies)、[triples CLI](https://docs.trustgraph.ai/reference/cli/tg-query-graph) 和 [SPARQL CLI](https://docs.trustgraph.ai/reference/cli/tg-invoke-sparql-query.html) 为起点，并用真实 `2.8.14` 部署校正漂移。高层 triples 方法不暴露命名图参数，所以只有该操作使用官方 `FlowInstance.request()`；SPARQL 直接使用高层 `sparql_query()`。同步 `graph_embeddings_query()` 在 `2.8.14` 中把已经返回 list 的 `embeddings()` 结果再次当 mapping 读取，因此 A8 只用同一官方 SDK 把它拆成 embeddings 与 graph-embeddings 两个服务调用，不自制向量算法。真实部署证明 SDK 的 `service/sparql` 可用，在线 REST 的 `service/sparql-query` 在该版本返回 404；不另写 RDF 编解码器或猜测双路径 fallback。

官方 TrustGraph MCP server `2.8.14` 的真实 `initialize`/`tools/list` 探针返回 31 个工具，覆盖查询、Library、Knowledge Core 和 flow 等能力，但内部产品仍走 SDK。生成部署中 MCP 默认 API Gateway 为 `ws://api-gateway:8888/api/v1/socket`，实际 Gateway 监听 8088；外部启用 MCP 时必须显式覆盖并独立验收，不能把这个部署差异带入产品客户端。

LiteLLM 固定在仓库锁定范围内实际解析到的 `1.91.3`：

- `github_copilot/*` 提供 Chat Completions、streaming 和 tool 变换路径。
- 内置 Authenticator 会使用进程用户目录中的共享文件，并可能在普通模型调用中同步启动 device flow；这不满足 Data Formulator 多 identity 隔离。
- Copilot 有两层 token 生命周期：GitHub OAuth access token 与由其换取的短期 Copilot token，必须分别处理和测试。

Copilot 适配以 LiteLLM `1.91.3` 的 [Authenticator](https://github.com/BerriAI/litellm/blob/v1.91.3/litellm/llms/github_copilot/authenticator.py) 和 [chat transformation](https://github.com/BerriAI/litellm/blob/v1.91.3/litellm/llms/github_copilot/chat/transformation.py) 为版本锁定证据；升级前重新审计这些扩展点。

## 4. 目标架构与信任边界

```text
已认证 HTTP 请求
  │
  ├─ identity_id ───────────────┐
  ├─ X-Workspace-Id ────────┐   │
  │                         ▼   ▼
  │                    AnalystAgent
  │                         │
  │                 SkillContext(auth)
  │                         │
  │              ┌──────────┴──────────┐
  │              │                     │
  │       Local Knowledge       TrustGraph Skill
  │                                    │
  │                         TrustGraphProvider
  │                                    │
  │          服务端 workspace 精确 Profile → default 后备
  │                                    │
  │                         官方 Python SDK
  │                                    │
  │                  agent_explain WebSocket
  │                                    │
  │                  TrustGraph 原生 Agent
  │                                    │
  │       只读工具组 → collection-bound knowledge tools
  │                                    │
  │        provenance 事件 + 最终答案 token
  │                                    │
  │      有限阶段归一化 + 最终答案/trace 聚合
  │                                    │
  └──────────────────────────── Agent event router
                                       │
                         现有 NDJSON → 运行步骤/持久化引用
```

信任边界规则：

1. identity 和 Data Formulator workspace id 只能来自后端认证/授权路径。
2. 模型只能提交聚焦 `question` 和可选最小 `context`；不得提交 base URL、flow、collection、Agent 工具组、TrustGraph workspace、credential id 或 token。
3. 服务端先解析 Data Formulator workspace 的精确知识 Profile，再使用 `default` 后备；Profile 或当前 identity 凭据未就绪时不向 Agent 提供 Skill，真正调用时仍再次授权并失败关闭。
4. 外部返回的最终答案、title 和 URI 都是不可信数据，先规范化再进入模型或前端；explain 只消费事件类型和必要计数，隐藏 Thought、Observation 正文、工具参数、原始 triples 与 token 级答案不进入 NDJSON。
5. 引用是数据，不是控制指令；任何来源内容都不能改变系统提示或工具权限。

## 5. 核心契约

### 5.1 调用身份

`SkillContext` 增加不可从 payload 覆盖的授权上下文：

```python
@dataclass(frozen=True)
class SkillAuthorization:
    identity_id: str
    workspace_id: str

@dataclass
class SkillContext:
    ...
    authorization: SkillAuthorization | None = None
```

迁移期允许 `None` 以保持现有独立 Skill 单元测试兼容；需要外部授权的 Skill 遇到 `None` 必须拒绝调用。后续所有 Agent 构造路径都应传入真实授权值，测试证明 payload 中同名字段不能覆盖它。

### 5.2 通用结果与 TrustGraph Provider

通用层承载一个聚焦问题、最小上下文、结果、引用和错误；TrustGraph 适配器实现既有 provider-neutral 合同：

```python
@dataclass(frozen=True)
class ContextItem:
    uri: str
    title: str | None = None
    provider: str = ""
    kind: Literal["source", "trace"] = "source"

@dataclass(frozen=True)
class BusinessContextResult:
    text: str
    context_items: tuple[ContextItem, ...] = ()
    truncated: bool = False

@dataclass(frozen=True)
class BusinessContextProgress:
    query_index: int | None
    phase: Literal[
        "searching", "filtering", "summarizing", "completed", "finalizing"
    ]

@dataclass(frozen=True)
class BusinessContextQuery:
    text: str
    identity_id: str
    workspace_id: str
    context: str = ""

class BusinessContextProvider(Protocol):
    def query(self, request: BusinessContextQuery) -> BusinessContextResult: ...
    def query_stream(
        self, request: BusinessContextQuery
    ) -> Generator[BusinessContextProgress, None, BusinessContextResult]: ...
```

约束：

- provider 每次查询重新核对 identity/workspace scope；授权上下文只用于服务端解析目标和凭据，不原样发给 TrustGraph。
- `text` 是一个可独立回答的聚焦业务问题；`context` 是可选的简短数据说明，只允许包含当前任务/决策、相关数据源或表在任务中的角色、字段名和类型、少量非敏感代表值或脱敏值模式以及用户明确约束。
- 工具 schema 不提供查询语言、URL、Flow、collection、workspace、tool group、credential 或 token 字段。
- provider 构造一个短的固定查询帧，把 `context` 明确标记为不可信本地数据；TrustGraph 原生 Agent 负责内部检索和多轮工具使用。
- `query_stream()` 是实际网络路径；`query()` 只消费同一个生成器并返回其最终 `BusinessContextResult`，不发送第二次请求，也不保留 REST fallback。
- `BusinessContextProgress` 只表达产品需要的轮次和五个有限阶段，不携带查询文本、thought、observation、工具参数、RDF 或原始 explain entity。
- `BusinessContextResult.text` 始终是可解析、有大小上限的 JSON，只包含最终答案和 provenance 元数据；不包含 AgentThought 或隐藏思考链。
- `ContextItem.uri` 必填，`title` 可空，`provider` 由后端赋值而不是相信外部字段；可选 `kind` 只允许 `source` 或 `trace`，旧记录缺省为 `source`。
- 当前 `2.8.14` `AgentAnswer` 不返回原始文档 source，因此只把请求的官方 Agent provenance URI 标成“retrieval trace”，并在成功结果中记录实际 `query_count`；不得递归扫描答案或 RDF payload 中的 URI。未来只有官方明确返回的文档 source 才可增加 citation。
- 外部正文超限时在明确边界截断并标记 `truncated`，不把完整内容写入日志。

### 5.3 引用输出与持久化

`ToolResult` 提供 `context_items` 和可选、有界的 `resume_text`，Agent router 负责：

1. 再次校验通用引用结构。
2. 发送供应商无关的 `context_info` 事件，不暴露 bearer、内部 target id 或原始响应。
3. 只在 Reasoning log 记录数量、provider 和稳定错误类别，不记录查询正文、来源正文或 token。
4. 前端把本轮引用与产生它的交互绑定，并写入 `InteractionEntry` 和最终 `TextTurn`。
5. 恢复 Session、导出/导入和历史回放后引用仍存在。
6. `public_summary` 只用于公开工具事件和日志；`resume_text` 只用于模型 trajectory 续接，并且只能包含最终答案、官方明确返回的文档来源与请求生成的 provenance trace 标识，不含 hidden thought、原始响应或凭据。

建议前端类型：

```ts
type ContextItem = {
  uri: string;
  title?: string;
  provider?: string;
  kind?: 'source' | 'trace';
};
```

已有历史数据缺少引用字段时按空数组处理，缺少 `kind` 时按 `source` 处理，不做破坏性迁移。前端 Sources 只显示 `source`；`trace` 使用独立的紧凑标签或分组，不把 session URN 冒充文档。调用过程先显示供应商无关的“正在核对业务知识…”，随后消费有限 `tool_progress`，按 `query_index` 原位更新每一轮；成功 trace 的标题显示实际查询轮数。这里不显示 TrustGraph ReAct 文本，也不新增 ContextItem metadata、事件持久化表或图谱视图。

inspection Skill 的 `handle_tool` 合同允许返回同步 `ToolResult`，也允许返回 `Generator[Event, None, ToolResult]`。Agent shell 检测生成器后只转发 `type=tool_progress` 的事件，并强制使用当前工具名；现有同步 Skill 和最终 `tool_result/context_info` 顺序不变。A14 事件最小形状为：

```json
{
  "type": "tool_progress",
  "tool": "query_business_context",
  "query_index": 1,
  "phase": "searching"
}
```

### 5.4 TrustGraph 知识 Profile（target）配置

配置分成全局策略和 Data Formulator workspace 到服务端知识 Profile 的显式映射。实现复用现有环境配置与 JSON 解析，不增加 YAML/文件监听器：

```text
TRUSTGRAPH_ENABLED=false
TRUSTGRAPH_TARGETS_JSON={...}
DF_ALLOWED_API_BASES=https://trustgraph.example.com/*
```

`TRUSTGRAPH_TARGETS_JSON` 顶层 key 可以是已经授权的 Data Formulator workspace id，也可以是保留 key `default`；value 只保存非 secret Profile 配置及 credential reference。解析顺序固定为精确 workspace key 优先、`default` 后备。

锁定 TrustGraph 版本的真实语义是：`agent_explain(..., collection=...)` 中的 collection 用于 Agent session provenance trace；GraphRAG、Document RAG、`structured-query` 等实际检索的 collection 由 Agent group 中各工具自己的配置决定。当前目标合同因此只保存 `trace_collection`，不增加 retrieval collection 列表：

```json
{
  "default": {
    "api_base": "https://trustgraph.example.com",
    "flow_id": "business-knowledge",
    "trace_collection": "business-context-traces",
    "agent_group": "data-formulator-readonly",
    "trustgraph_workspace": "business-knowledge",
    "credential_ref": "trustgraph:business-context-default",
    "socket_timeout_seconds": 120,
    "max_response_chars": 131072
  }
}
```

`trace_collection` 必填；`collection` 不再接受，出现时由目标配置的未知字段校验直接拒绝。`socket_timeout_seconds` 只传给官方 WebSocket SDK 的连接认证和心跳，不是整次 Agent 查询的总截止时间。无运行时消费者的旧 `name`、`connect_timeout_seconds`、`max_context_items` 以及语义不实的 `read_timeout_seconds` 均直接删除并按未知字段拒绝，不保留别名、双字段优先级或迁移分支。单知识域部署可以让 trace collection 与唯一查询 collection 同名，但不能再由这个名字推断检索范围。

TrustGraph 侧的 collection 路由只存在于 Agent group 工具配置中：

| 场景 | group 配置 | Data Formulator 行为 |
| --- | --- | --- |
| 单知识域 | 一个稳定领域知识工具 → 该域当前活动的版本化 collection | 发起一个高层查询；Agent 自行一轮或多轮检索 |
| 多知识域 | 少量描述明确的只读知识工具 → 各域当前活动 collection | 仍发起一个高层查询；Agent 按当前问题选择一个或多个 |
| 结构化记录 | 保留 `structured_query` → 受治理记录 collection | 外层合同不变，另做真实场景验收 |

授权或所有权不同先拆 TrustGraph workspace/Profile；当前一次高层查询不跨 workspace。同一 workspace 内的 collection 按发布生命周期和知识连通性划分，不按预想问题划分。Knowledge Core 可以把同一治理域的多个来源复用/装入该域的版本化 collection；不同领域不为了方便 Data Formulator 查询而预先合并。来源文件不同本身也不是拆分理由。Data Formulator 不保存 collection inventory 作为第二套路由事实来源，也不动态列举、fan-out 或合并结果。

每个领域工具只需要四项稳定路由信息：

| 字段 | 合同 |
| --- | --- |
| `name` | 稳定表达知识域，不包含 collection 版本号 |
| `description` | 说明内容、权威范围和明确排除项，不枚举预期问题 |
| `collection` | 指向当前活动版本，由 TrustGraph 控制面切换 |
| `group` | 包含 Data Formulator 使用的稳定只读 group 标签 |

发布新版本时先用 TrustGraph UI/CLI 对新 collection 做直接查询验收，再更新稳定工具的 `collection` 绑定，并按当前部署的正常方式使配置生效；回滚时切回旧绑定。新旧版本不能同时作为两个同域工具暴露给 Agent，避免把发布决策变成模型路由问题。

对应 identity 的 bearer token 使用现有 `/api/credentials/store` 合同写入加密 vault，source key 必须与 `credential_ref` 一致：

```json
{
  "source_key": "trustgraph:business-context-default",
  "credentials": {"bearer_token": "<secret>"}
}
```

规则：

- flag 默认关闭；Skill frontmatter 通过通用 `enabled_if` 门控制，关闭时不读取目标 JSON、不解析凭据、不注册或导入 Skill。
- 每次构造 `AnalystAgent` registry 时复用同一个 resolver 做本地就绪判断：精确或默认 Profile 存在，且当前 identity 的 reader credential 可解析时才提供 TrustGraph Skill。该判断不访问 TrustGraph 网络，不缓存新的授权状态；Provider 真正调用时仍重复解析和校验。
- 启用时配置缺失、精确和默认 Profile 都不存在、base URL 未通过现有 `validate_api_base` allowlist、URL 含 userinfo/query/fragment、非 HTTPS 或 credential 缺失都失败关闭。没有 Profile 时不增加前端选择器。
- `api_base` 在生产和测试均只接受 HTTPS；离线测试使用 HTTPS 会话替身，不为测试增加 HTTP 绕过。
- 同一个 `api_base` 必须支持 `/api/v1/socket` 的 WSS Upgrade。当前本机 9443 验证代理先补齐 Upgrade；真实生产部署没有证明 REST/WS 分离前，不增加 `socket_base`、浏览器目标字段或自动端口猜测。
- bearer 绑定的 TrustGraph workspace 是授权边界；`agent_group` 是服务端配置的单个只读工具组标签，也是这条 Agent 路径的工具可见性/路由边界，不新增 IAM。Data Formulator 请求时将它作为唯一 group 发送。单知识域可以只有一个稳定领域知识工具，多知识域则配置少量、描述明确的 collection-bound 只读工具，由 Agent 查询时选择。现有组中的 `structured_query` 保留并由 TrustGraph schema 自行描述，另以真实受治理结构化记录场景完成独立验收。
- `credential_ref` 必须使用独立的 `trustgraph:` namespace 并通过现有 identity-scoped vault 解析；目标 JSON 不能内嵌 bearer token。

### 5.5 TrustGraph 请求与响应

A14/A16 的实际网络路径使用锁定 SDK 提供的 [`agent_explain`](https://github.com/trustgraph-ai/trustgraph/blob/0bcfe9377c3d55b7199c16335b9e52ed91286233/trustgraph-base/trustgraph/api/socket_client.py#L619)：

```python
events = api.socket().flow(flow_id).agent_explain(
    question=framed_question,
    history=[],
    group=[server_bound_readonly_group],
    collection=server_bound_trace_collection,
    session_id=server_generated_uuid,
)
```

这里的 `server_bound_trace_collection` 只决定 Agent session provenance 写入位置，实际查询 collection 由 group 中各工具绑定。代码只从 `target.trace_collection` 传入该参数，没有旧字段读取路径。`Api` 仍只接收已校验的 `api_base`、TrustGraph workspace 和 vault bearer；官方客户端把 HTTPS base 转成同 origin 的 WSS `/api/v1/socket`。只增加一个可注入的 explain iterator factory 作为离线测试接缝，不实现自制 WebSocket 协议、重连器、事件存储或 REST fallback。

迭代规则固定为：

1. `ProvenanceEvent` 只读取 entity class 和该事件自身的官方 RDF 类型；第一轮从 `Analysis`（包括锁定 SDK 解析为 `Reflection` 的混合类型工具事件）或首个 `grounding` 开始，后续在前一轮 `observation` 后再次出现这些事件时递增 `query_index`。不读取或匹配 action 名。
2. `grounding/exploration → searching`，`focus → filtering`，`synthesis → summarizing`，provenance `observation → completed`，`Conclusion → finalizing`。若结构化查询只返回 observation 而没有前置可识别事件，创建并立即完成一个通用查询轮次，不猜具体工具名。
3. `AgentThought` 和 `AgentObservation` 的 `content` 完全丢弃；`AgentAnswer.content` 只在服务端顺序聚合，直到终态 `end_of_message/end_of_dialog`。`Reflection`、顶层 Question 和未知的新增 provenance 类型不生成 UI 文本。
4. 成功结果沿用 `BusinessContextResult`，在 provenance JSON 和 trace 标题中增加 `query_count`；当前 AgentAnswer 没有官方 document sources，因此不伪造 citation。
5. 正常结束、异常和上层 generator 关闭都在 `finally` 关闭官方 socket；认证、连接、超时、服务和缺少终态答案继续映射到现有稳定错误类别，不新增一套 WebSocket 专用错误枚举。

真实探针已经证明该序列会自动产生两轮 `grounding → exploration → focus → synthesis → observation`，随后 `Conclusion` 和终态 Answer；同一次调用还产生大量 Thought/Answer token，正是需要在服务端压缩而不能直通前端的内容。

### 5.6 稳定错误分类

外部异常不得把原始 URL、response body、headers 或 exception 文本传给模型/前端。第一版类别：

| 类别 | 触发 | 面向 Agent 的稳定语义 | 可重试 |
| --- | --- | --- | --- |
| `disabled` | flag 关闭 | 该能力未启用 | 否 |
| `not_configured` | workspace 无目标/凭据 | 该 workspace 未配置业务上下文 | 否 |
| `invalid_request` | 非对象参数、空/超限问题或上下文、未知字段、非法 session id | 查询不符合合同 | 否 |
| `unauthorized` | 401/403 | 业务上下文认证失败 | 需要人工处理 |
| `timeout` | 官方 socket 认证/心跳超时，或上游 Agent 明确返回超时 | 服务暂时超时 | 是 |
| `unavailable` | 网络错误、429、5xx | 服务暂时不可用 | 是 |
| `protocol_error` | 无效 JSON/合同漂移 | 服务响应不符合预期 | 否，先检查集成 |

日志只包含 category、目标 key、HTTP status（如适用）和 correlation id。原始异常可以作为 `raise ... from ...` 的内部 cause 保留，但不得被序列化到用户事件。

### 5.7 Copilot OAuth 和 capability

Copilot 纵向切片沿用现有模型注册与 Client，不建立平行调用栈：

1. 新增 server-owned device start/poll endpoint；普通模型调用永不启动交互式 device flow。
2. start 返回经过筛选的 `verification_uri`、`user_code`、`device_code` 的服务端句柄、`interval` 和 `expires_in`；前端不保存 access token。
3. poll 服从 GitHub `interval`、`expires_in`、`authorization_pending`、`slow_down`、`expired_token` 和 `access_denied` 语义。
4. GitHub access token 进入现有 credential vault，并以 identity 隔离。
5. 请求时用长期 token 换取短期 Copilot token；短期 token 只在请求局部内存中存在。
6. LiteLLM `1.91.3` 适配器必须带版本保护，并在请求局部覆盖其 Authenticator 解析点；禁止修改共享环境变量、home 目录或共享 token 文件。
7. capability probe 对每个候选模型分别执行 chat、streaming 和 tools，并记录可审计结果；当前 Agent 只展示三项均通过且不是 Responses-only 的模型。

A4 已固定以下应用合同：

- API 为 `GET /api/copilot/auth/status`、`POST /device/start`、`POST /device/poll`、`POST /device/cancel` 和 `POST /disconnect`，仅在 `GITHUB_COPILOT_ENABLED=true` 时注册；所有 identity 都由后端解析。
- 生产请求固定到 GitHub 官方 device/token endpoint，使用项目已有 `requests`；HTTP transport 和 monotonic clock 可注入测试替身，不接受前端 base URL。
- `GITHUB_COPILOT_CLIENT_ID` 是可选的非 secret 部署覆盖；未设置时复用锁定 LiteLLM `1.91.3` 的公开 client id 常量，避免复制另一套 OAuth provider 实现。
- device code 从不返回浏览器；pending transaction 使用随机不透明句柄、identity 绑定、全局上限、GitHub expiry 和并发 poll 门，服务重启会取消未完成登录。
- 完成后的 token 只写入 vault source `github-copilot:oauth`；新服务实例可从 vault 恢复连接状态。`disconnect` 删除本地凭据，不宣称撤销 GitHub 账户侧授权。
- 前端只在模型对话框显式点击后 start，按 `retry_after`/`interval` 计时，且只允许把精确的 `https://github.com/login/device` 作为隔离新标签链接。

A5 已固定以下模型调用与准入合同：

- `GITHUB_COPILOT_MODELS` 是逗号分隔的显式候选列表；没有该列表时即使 flag 开启也不注册模型。Copilot 不读取通用 provider 的 API key/base，长期 token 只从当前 identity 的 vault 解析。
- 适配器只支持锁定的 LiteLLM `1.91.3`，并同时校验 Authenticator 和 chat transformation 源码 SHA-256；任何版本或扩展点漂移都在发起模型请求前失败关闭。
- 既有 Authenticator 类的方法在进程内只安装一次无凭据适配；实际凭据由 `ContextVar` 指向当前 `CopilotTokenManager`。普通调用、惰性 stream 获取下一块和关闭 stream 都单独进入 scope，并在向应用 yield 前退出。
- 长期 GitHub token 经固定 GitHub Copilot token endpoint 换取短期 token；短期 token 和服务端返回的允许 API origin 只缓存在当前 Client manager 内，接近过期时刷新。环境变量、home/token 目录和 `Client.params` 均不保存这两层 token。
- capability probe 直接读静态 `litellm.model_cost` 判断 `mode`，不调用可能触发交互登录的 `get_model_info()`；非 `chat`/未知模式不访问网络。chat 候选分别执行 buffered chat、文本 stream、streamed required tool call，三项结果用布尔值和稳定错误码记录。
- capability 结果按 identity/model 有界保存在进程内，不含 token、prompt 或原始异常。公开列表和普通 `get_client` 都只接受当前 identity 三项全通过的候选；连接完成、断开、凭据缺失或失败复测会清除/替换资格及前端旧选择。
- 模型配置对话框先读取上述已有资格；只有缓存缺失、连接生命周期已使其失效，或用户点击显式“重新测试”时才调用 capability endpoint 发起网络探测。普通打开/关闭对话框不重复执行三次模型请求，也不新增周期刷新器。

GitHub 官方 device-flow 合同见 [Authorizing OAuth apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)：客户端必须遵守返回的最小轮询间隔，`slow_down` 后至少增加 5 秒，并处理 pending、过期和拒绝终态。

升级 LiteLLM 后，版本保护测试先失败，重新审计 Authenticator/transform 调用点后才能更新允许版本。

## 6. 实施切片与完成条件

每个切片先写聚焦失败测试，再做最小实现；测试与工程记录在同一个有意义节点更新。

### A0：M0-A 官方 SDK 合同与 TrustGraph 只读客户端（已完成）

建议文件：

- `py-src/data_formulator/analyst/business_context/base.py`
- `py-src/data_formulator/analyst/business_context/trustgraph.py`
- `tests/backend/analyst/test_business_context_contract.py`
- `tests/backend/analyst/test_trustgraph_client.py`

实现内容：

- 通用 result/context item 和稳定错误不变量。
- 默认关闭的 TrustGraph flag 解析。
- 经过校验的目标和值对象。
- 固定 `trustgraph-base==2.8.14` 和 `rdflib>=7.1,<8`，复用官方 API、RDF schema 与 translator。
- 本体 config get、S/P/O 与来源 named graph、只读 SPARQL 的确定性请求构造。
- typed literal、language、blank node、RDF-star 和 named graph 响应适配，结果/引用/JSON 大小受限。
- timeout、401/403、429/5xx、网络和协议错误的稳定分类。
- 测试证明错误消息及 `repr` 不包含 token 或外部 response body。

完成条件：所有测试使用替身，不访问网络；关闭态不构造 HTTP client；没有 UI 或 Agent 集成改动。

### A1：授权上下文与通用引用路由（已完成）

建议改动：`SkillContext`、`ToolResult`、`AnalystAgent` 的构造和事件路由，以及对应 Skill/Agent 测试。

完成条件：

- identity/workspace 来自后端路径，payload 无法覆盖。
- 现有 Skill 在没有引用时行为不变。
- 结构化引用只通过 router 发出，尺寸和错误已清洗。
- 关闭 TrustGraph 时 registry 和工具集合中均不存在该 Skill。

实现结果：授权 scope 与 payload 分离；inspection/action 两条 Skill 路径统一由 Agent 构造上下文；`ToolResult` 保持 `text, images` 位置参数兼容并增加结构化引用和安全公开摘要；router 对 URI 再校验、按 URI 去重、限制 50 项，只把数量/provider 写入 Reasoning log，原始 Skill 异常不再进入流或模型观察。

### A2：TrustGraph 只读 Skill 纵向接入（已完成）

新增 `SKILL.md`、`tools.json` 和 handler，只暴露 `inspect_trustgraph_ontology`、`query_trustgraph_triples`、`query_trustgraph_sparql` 三个只读工具，不暴露 Graph RAG、写操作或任意目标字段。handler 先严格校验结构化参数，再从授权上下文解析 provider。

完成条件：本体、knowledge/provenance 三元组、只读 SPARQL、无来源、非法目标覆盖、非对象参数、超时、未配置和认证失败场景都有 Agent 级测试；外部不可用不会破坏本地知识和正常 Agent 回答。

实现结果：新增通用 `enabled_if` registry 门、`TRUSTGRAPH_TARGETS_JSON` 精确 workspace 映射、identity-scoped vault credential 解析及三工具只读 Skill。模型只能提交 RDF/SPARQL 查询字段；外部 JSON 以明确的 untrusted data frame 进入模型，工具事件、Reasoning log 和浏览器可恢复 trajectory 使用安全摘要。稳定错误通过 `ToolResult.error_code` 标记为失败，Agent 可继续本地回答。

### A3：引用前端持久化（已完成）

扩展共享类型、流累计、Session 序列化和 Sources 组件。

完成条件：引用与正确交互绑定；刷新、恢复、导出/导入后仍存在；URI 安全打开；没有引用时 UI 与历史数据无变化。

实现结果：共享类型仅增加可选 `contextItems` 字段，不做破坏性 Session 迁移。前端用一个有 50 项上限的 provider-neutral 累计器消费 `context_info`，为每个制品的 `InteractionEntry` 保存生成时可用的不可变快照，并为最终 `TextTurn` 保存整轮快照；续接持久化文本时继承既有来源。现有 Redux、自动保存、恢复和 workspace ZIP 链路原样携带字段。共享 Sources 组件覆盖 Data Thread、交互卡和 ExplanationPanel；仅无 userinfo 的 HTTP(S) 可在隔离新标签打开，URN 不可点击，危险或无效历史值不渲染。空引用不增加字段或 UI。

### A4：Copilot device flow 与凭据生命周期（已完成）

先实现独立 endpoint/服务层，再接模型配置 UI。所有 HTTP 交互可注入替身，真实账号探针为 opt-in。

完成条件：identity 隔离、poll 节流/过期/拒绝、token 清洗、并发登录以及重启后的长期 token 解析都有测试；普通模型调用不会启动 device flow。

实现结果：新增有界、无休眠、可注入 HTTP/clock 的 device-flow service 和默认关闭的 blueprint；opaque handle 与后端 identity 绑定，GitHub `interval`、`slow_down`、本地过期、拒绝和取消均有稳定状态。长期 token 进入既有加密 vault，浏览器、响应和日志不含 access token/device code。模型配置对话框新增显式连接/断开 UI；`Client` 在 A5 完成前拒绝任何 `github_copilot/*` 构造，保证普通模型请求不触发 LiteLLM 共享文件 Authenticator。离线 A4 后端聚焦 40 项、认证/凭据/模型相邻回归 350 项、前端聚焦 4 项均通过。

### A5：LiteLLM 请求局部适配与 capability probe（已完成）

完成条件：

- 固定 LiteLLM 版本下，测试证明当前 identity 的短期 token 被用于当前请求且不串线。
- 并发两个 identity 时没有共享环境或文件状态。
- chat、streaming、tools 三类探针结果分别记录。
- Responses-only 或 tools 失败模型不进入 `AnalystAgent` 可选列表。
- Copilot flag 关闭时现有 provider 注册和调用测试不变。

实现结果：固定 LiteLLM `1.91.3` 版本和两段源码指纹，在既有 `Client`/LiteLLM 路径中安装无凭据的 Authenticator 方法适配。当前 identity 的 vault token 只进入 request-local manager，经既有 `requests` 换取和刷新短期 token；同步调用和惰性 stream 迭代都使用 `ContextVar` 隔离，并发身份不串线、不切换环境、不创建 token 文件。模型注册表只接受显式 `GITHUB_COPILOT_MODELS` 候选，静态拒绝 Responses-only/未知模式，再逐项实测 buffered chat、streaming 和 streamed tools；只有当前 identity 三项全通过的模型才由 API 发布、被前端保留且能在普通路由构造 Client。离线聚焦回归 101 项、后端全量 2302 项、前端 406 项和生产构建均通过；这些只证明代码回归门禁，不作为 Copilot 真实能力证据，真实账号结果单独见 A6/M0-B。

### A6：M0-B 真实外部探针

只有用户明确提供外部条件时运行：

- TrustGraph：真实 ontology、knowledge/provenance triples、只读 SPARQL、bearer/workspace、超时和错误格式。
- Copilot：device flow、chat、streaming、tool call、长期 token 过期以及短期 token 刷新。

探针输出只能记录布尔能力、耗时、状态分类、结果/引用数量和模型标识，不记录 SPARQL、RDF 内容或 token。缺少外部条件时记录“未执行及原因”；仓库内不搭建容器，用户明确授权的仓库外 WSL2 环境独立管理。

证据归属必须分离：Data Formulator 的 Vitest、前端生产构建和普通后端回归只属于 A7 交付门禁，不能证明 Copilot npm CLI/SDK 或真实账号可用。Copilot M0-B 只接受两类真实证据：在目标 Linux Node/npm 环境中运行官方 CLI/SDK 的账号请求，以及应用自身 device flow → identity vault → 短期 token → LiteLLM 的 chat、streaming、tools 链路。

执行结果（2026-08-19）：

- Copilot：应用 device flow 成功把真实账号 OAuth 凭据写入当前 identity 的加密 vault；`github_copilot/gpt-4.1` buffered chat、streaming 和 streamed required tool-call 三项均为 true，总耗时约 13 秒。短期 token 首次交换、缓存复用以及进入 60 秒刷新窗口后的重新交换成功，服务端返回的 API origin 为允许的 `api.individual.githubcopilot.com`。真实长/短 token 在应用日志、CLI/SDK 隔离状态目录和仓库 diff 中均为 0 命中，vault SQLite 不含长期 token 明文。
- 官方 npm 工具旁证：仓库外隔离安装 `@github/copilot` `1.0.80` 与 `@github/copilot-sdk` `1.0.11`；SDK JSON-RPC ping、真实账号 28 项模型目录以及 CLI `gpt-5.4` 文本调用通过。它们不进入产品依赖，不能替代既有 LiteLLM/`AnalystAgent` 路径。
- TrustGraph：官方 `trustgraph-base==2.8.14` 已在 Windows 项目环境直接安装并通过 import/依赖检查；本体、三元组、来源图和 SPARQL 的 70 项客户端/Provider/Skill 合同测试通过。仓库外专用 WSL2 环境的真实 `2.8.14` 服务完成 bearer、`default` Flow、HTTPS、空 knowledge/provenance triples、SPARQL `ASK`/`SELECT` 和完整 Skill→Provider→服务链路验证。临时唯一 ontology 成功返回 1 个 class/1 个引用并在 `finally` 中确认删除；缺失 ontology 稳定映射为 `not_configured`。
- 真实合同差异：在线 REST 的 `service/sparql-query` 在该部署返回 404，官方 Python `FlowInstance.sparql_query()` 使用的 `service/sparql` 成功；实现已以锁定 SDK/真实部署为准，不做双路径 fallback。官方 Compose 把 SPARQL processor 打包在名为 `rag` 的 processor group 内，但产品与探针只调用结构化 SPARQL，不调用 Graph RAG 或 text completion。
- TrustGraph 停止线：WSL2 + Docker 仅是用户明确授权的仓库外验收实验室，不写入仓库、不进入默认开发/测试、不成为产品依赖。结构化查询可在无 LLM 的情况下验证；取消 Data Formulator 摄取入口后，SiliconFlow key 和模型不再是本分支后续条件，绝不引入 Ollama。

### A7：集成回归与交付（离线门禁已完成）

完成条件：

- 两个 feature flag 默认关闭且关闭态无 API、Skill、模型或 UI 残留。
- 聚焦安全测试、后端全量、前端全量和生产构建通过。
- Windows 基线环境差异与外部未执行项如实写入工程记录。
- diff 不包含 secret、临时数据目录、token cache 或外部分支职责代码。

实现结果（2026-08-19）：`uv pip check` 确认 158 个已安装包依赖兼容；Windows 后端在 UTF-8/TTY 环境下执行最终全量门禁，除无本机符号链接权限的既知单项外，2352 项通过、13 项跳过、1 项 xfailed、1 项 deselected。Codex 内置 Node `24.19.0` 与 Yarn `1.22.22` 下，49 个前端文件、406 项测试全部通过，Vite `7.3.3` 生产构建通过；本机默认 Node `20.15.1` 因不满足 Vite 版本要求未用于门禁。此前仓库外 Linux Node `22.14.0` 门禁结果保持有效。

### A8：知识目录与图实体语义检索（已完成）

在既有 TrustGraph client/provider/Skill 上增加两个只读工具：

- `inspect_trustgraph_catalog`：列出当前目标、Flow、collection、document、processing 和 Knowledge Core，便于 Agent 先判断“有什么知识可查”。
- `search_trustgraph_entities`：接收查询文本和 limit，复用官方 embeddings 与 graph-embeddings 服务，返回带 score 的 RDF entity term。

实现顺序：先写 SDK 请求和返回规范化的客户端失败测试，再扩展 Provider 与 Skill；不修改前端，不引入 MCP 客户端，不实现自有 embedding、向量库或检索排序。

完成条件：五个 TrustGraph 工具可由同一只读 Skill 注册；目录和语义检索的请求路径、workspace/flow/collection、RDF term、score、无结果及协议漂移均有聚焦测试；原三工具行为不变。

实现结果（2026-08-19）：新增两个无目标覆盖参数的只读工具。目录直接调用官方 Flow、Collection、Library、Knowledge 高层 API 并输出规范化资源快照；实体搜索调用官方 `embeddings()` 后通过同一 `FlowInstance.request()` 请求 `service/graph-embeddings`，保留 RDF term 与有限数 score。Client/Provider/Skill 聚焦 95 项、business-context 与相邻 Skill/registry 回归 152 项通过；Windows UTF-8/TTY 后端全量 2336 项通过、13 项跳过、1 项 xfailed，仅 deselect 既有符号链接权限项；Python compileall 和 diff 检查通过。未新增 MCP 客户端、向量库或前端改动。

### A9：只读 GraphQL rows 查询（已完成）

使用官方 `FlowInstance.rows_query()` 执行显式 GraphQL，规范化 `data`、`errors` 和 `extensions` 后通过 TrustGraph 只读 Skill 返回。模型不得提交 collection、flow 或 workspace；这些目标继续由服务端绑定。

明确停止线：不创建 Data Formulator table，不调用 `Workspace.write_parquet*()`，不修改 Redux table state，不实现导入、同步或刷新，也不调用依赖 LLM 的 `structured_query()`/`nlp_query()`。

完成条件：GraphQL query、variables、operation name 和 `data/errors/extensions` 返回形状有合同测试；Provider/Skill 路径可用；测试证明没有 table/Workspace 写入调用。

实现结果（2026-08-19）：新增第六个只读工具 `query_trustgraph_rows`。客户端直接使用官方 `FlowInstance.rows_query()`，collection/flow/workspace 继续由服务端目标绑定；工具只接受显式 GraphQL、可选 variables 和 operation name，返回规范化的 `data/errors/extensions`。没有导入 table/Workspace 模块，没有 `write_parquet*()`、Redux table、同步或刷新调用，也没有调用依赖 LLM 的 `structured_query()`/`nlp_query()`。聚焦 109 项、相邻回归 166 项、Windows UTF-8/TTY 后端全量 2350 项通过，13 项跳过、1 项 xfailed，仅 deselect 既有符号链接权限项。

真实空环境冒烟进一步发现：TrustGraph `2.8.14` rows service 在 workspace 未装载 GraphQL schema 时以 HTTP 200 返回 `rows-query-error` 和稳定的 no-schema 状态。项目现在只把这个精确状态映射为 `not_configured`；其他 rows service 错误仍保持 `unavailable`。新增正反合同后 TrustGraph Client/Provider/Skill 聚焦 111 项通过，真实 Skill 调用也返回 `business_context.not_configured`，不再把部署配置缺失误报成服务故障。

### A10：文档与 Context Core 准备（已取消）

2026-08-19 按用户确认取消整个切片。Data Formulator 不增加文档上传、processing 状态、Knowledge/Context Core list/load/unload/bulk 写操作，也不为这些操作增加 service/API/UI。A8 已实现的 document、processing 和 core 目录读取保持只读。

同次范围决定取消 `row_embeddings_query()` 行数据语义搜索。A9 的显式 GraphQL rows 查询继续保留，不导入 Data Formulator 表、不写 Workspace、不做同步或刷新。

### A11：真实业务验收与 MCP 外部兼容

不建设 Data Formulator 内的 TrustGraph 工作台或导航入口。官方 `trustgraph-ui` 已提供 Knowledge Explorer、Ontology Workbench、SPARQL Workbench、GraphQL Workbench、Document Ingestion 等完整界面，并发布 `@trustgraph/trustkit` 组件库。npm 实时注册表显示 `trustkit@2.0.3` 要求 React 19，而 Data Formulator 使用 React 18；因此不复制组件源码、不升级应用基线，官方 UI 作为独立应用使用。A14 只借鉴 ExplainTimeline 的有限阶段交互，不改变这一依赖决定。

补充核对的 `@trustgraph/portal` 是 `private: true` 的 React 19/Vite 完整 Workbench，而不是可安装的第四个 UI 库。它组合 TrustKit、React provider/state，并自行拥有登录/API key、SocketProvider、workspace 同步、QueryClient、BrowserRouter、主题、状态栏和插件壳；当前 `/agent`、`/explain` 只在页面内创建新查询，不接受现有 query/session/explain id 作为深链输入。因此 Portal 继续独立使用，不做 npm 依赖、源码 vendoring、iframe 或双登录。可复用的设计证据只有其 UI service 对 `/api/v1/socket` 的同源 WebSocket 转发，这与 A14 的单 `api_base` WSS 前置一致。

完成条件：A8/A9 使用真实业务 collection 完成非破坏性验收。只有存在明确外部客户端需求时才补 MCP 配置说明，产品内部仍使用 Python SDK；Data Formulator 前端不增加 TrustGraph 页面、组件或链接。

当前进展（2026-08-19）：已用仓库外真实 TrustGraph 服务逐一冒烟六个只读工具。目录返回 1 个 Flow 和 1 个 collection，图实体搜索、knowledge triples 均正常返回空结果，SPARQL `ASK` 正常返回 `true`；GraphQL rows 与 ontology 分别因未装载 schema 和 0 个 ontology 配置返回 `not_configured`。这证明传输、认证、Skill/Provider/SDK 调用和错误边界可用，但不等于真实业务数据验收完成；A11 仍等待带业务 ontology、rows schema 和实体数据的 collection。

### A12：TrustGraph 原生 Agent 收敛（代码与真实验收完成）

撤下 `inspect_trustgraph_catalog`、`search_trustgraph_entities`、`query_trustgraph_rows`、`inspect_trustgraph_ontology`、`query_trustgraph_triples` 和 `query_trustgraph_sparql` 六个外层模型工具，替换为：

```text
query_business_context(question: string, context?: string)
```

`question` 说明待解决的业务含义；`context` 只说明当前任务/决策、相关数据源或表在任务中的角色、字段与类型、少量非敏感代表值或脱敏值模式和用户明确约束。TrustGraph 原生 Agent 负责选择服务器配置的知识与结构化查询工具并自行迭代。Data Formulator 保留唯一产品 Agent、授权映射、vault、出站控制、稳定错误和通用引用通道。

完成条件：

- registry 启用后只暴露一个 TrustGraph 工具，关闭态仍无残留；
- provider-neutral `BusinessContextProvider.query()` 成为实际调用合同，不再定义 Skill 私有的六操作 Protocol；
- 真实请求只到 `service/agent`，并固定 Flow、collection、只读 group、workspace、credential、session id、空 history 和 `streaming=false`；
- 单元测试覆盖最小载荷、scope、目标覆盖拒绝、响应/错误边界和 trace 引用；
- 真实场景覆盖“未决业务含义自动查”“明确用户规则跳过”“无答案或服务不可用失败关闭”；
- TrustGraph 部署自己的 OpenAI-compatible 配置使用 SiliconFlow、`Qwen/Qwen3.5-27B`、Qwen variant 和 `thinking=off`，不误用 Data Formulator 的 LiteLLM 配置。

实现结果（2026-08-20）：外层 registry 现在只注册 `query_business_context`；Skill 构造 provider-neutral `BusinessContextQuery`，provider 再次核对 identity/workspace scope，客户端只允许官方 `service/agent` 路径和固定请求形状。系统提示只要求在会改变分析结果的未决业务含义上查询，并明确最小上下文为当前操作/决策、相关数据源或表的角色、字段名与类型、少量非敏感代表值或脱敏值模式和用户约束；整表、原始敏感值、完整聊天、代码、路径、凭据和路由信息禁止发送。原生 Agent 的最终答案作为不可信证据进入当前模型观察；只有官方显式返回的 `sources` 才作为文档来源，session provenance 单独标成非文档 trace。

最终离线门禁：Client 44 项、business-context/Client/Provider/Skill 四文件聚焦 118 项、Analyst/Agent 相邻回归 706 项通过；Windows UTF-8/TTY 后端全量 2334 项通过、13 项跳过、1 项 xfailed，仅排除 1 个当前账户无权限创建的符号链接用例；Node `24.19.0` 下前端 49 文件/406 项测试和生产构建通过，compileall、`uv pip check`、`uv lock --check`、`git diff --check` 通过。真实环境已动态配置 `knowledge-query` 和 `structured-query` 到 `data-formulator-readonly`，两者绑定 `dfm-validation-core-v1`；Flow 只覆盖两个模型参数为 `Qwen/Qwen3.5-27B`，其余参数由 blueprint 默认解析；部署文件已设置 Qwen variant、`thinking=off` 和已有 SiliconFlow key。

真实重载验收（2026-08-20）：文本补全以唯一 active `deploy-openai` 实例重新创建后，真实 `Qwen/Qwen3.5-27B`、`thinking=off` 探针返回 `TG_OK`。Flow 更新曾重建 librarian exchange 而保留旧 consumer binding，按用户明确要求只重载仓库外 existing `control` 服务后恢复；未改仓库 Docker 配置。真实调用进一步暴露 `2.8.14` HTTP gateway 的终态消息形状，适配器增加上述严格官方兼容合同。合成业务知识原来只有 triples 和 `rdfs:comment`，不满足 GraphRAG 的实体上下文索引及非 schema 边检索规则；验收数据按 TrustGraph 官方 `load-knowledge` 语义补充 entity contexts，以及领域中立的业务定义、计量基础、比较规则和不可互换关系。最终 Data Formulator reader bearer → HTTPS → 单个 `query_business_context` → 原生 Agent 成功：ReAct 第 1 轮自动调用 graph-rag，第 2 轮给出有证据的定义与对齐规则，librarian 成功持久化 thought/observation/answer，返回真实 session trace 且无文档来源伪造。

本体/图谱统一检索收口（2026-08-20）：进一步确认 TrustGraph 的 ontology config 用于指导摄取，Agent 不会直接把配置项当作业务知识搜索。验收数据按现有 `businessDefinition` 图谱模式，把 class、object/datatype property、domain/range、定义和来源边实际导入目标 collection，并为类和属性建立 graph entity contexts；精确 SPARQL 与 GraphRAG 均验证成功。固定 Agent 任务帧现在明确只用本轮列出的 `knowledge_query`/`structured_query`，不发明 `search`/`browse`，不做 row embeddings；第一轮未覆盖多部分问题时由 TrustGraph Agent 自行缩窄并继续查。真实清洗场景一轮完成，跨“类型定义、两个术语不可互换、比较前提”的场景自动两轮完成，中文输入保持完整。官方 MCP server 虽暴露 triples/SPARQL，但 `2.8.14` flow 镜像的出站 `mcp-tool` 与镜像内 MCP 客户端签名不兼容；临时配置已删除，未修改 TrustGraph 源码或引入旁路。

### A13：最小产品化收口（主路径与真实验收已完成）

A12 已证明单工具、原生 Agent 和真实知识链路可用。Data Formulator 已经持有用户正在分析的表，TrustGraph 在第一版中的职责是补充受治理的业务含义，而不是成为第二个数据查询引擎；因此 `knowledge_query` 是生产基线。现有组中的 `structured_query` 保留，但不扩展 Data Formulator 外层查询面，后续单独补充真实场景验收。A13 只修正普通用户实际使用时会遇到的主路径问题，按以下顺序实施：

1. **目标与就绪**：在现有 `TRUSTGRAPH_TARGETS_JSON` 中增加 `default` 后备，精确 workspace key 仍优先；registry 在请求时用同一 resolver 检查目标和当前 identity reader 凭据，不访问网络。未就绪时不向模型提供 Skill，Provider 仍保留最终授权检查；一个只读状态 endpoint 把同一配置判断显示在当前 Workspace 菜单，但不把它包装成服务健康状态。
2. **发现与触发**：通用 registry 同时列出 Skill 的 tools 和 actions，tool-only Skill 不再显示“无 action”；系统提示只说明“业务含义会改变结果时核对”，不要求用户说本体、三元组或图谱。固定 TrustGraph 任务帧只指导必需的 `knowledge_query` 和“只能使用服务器实际提供的工具”；可选工具依赖 TrustGraph 自己的 group schema，不向 Data Formulator 增加工具清单配置。离线回归用可重复的 scripted model 从当前未预加载 registry 进入真实 `/api/agent/analyst-streaming` 路由，仓库外验收再用实际 Qwen 重跑普通用户输入；二者不互相冒充。
3. **用户反馈与来源**：为 `query_business_context` 增加一个中英文通用进度；`ContextItem.kind` 把文档 `source` 与 session `trace` 分开，旧数据默认 `source`，不增加 TrustGraph 管理页面或 ReAct 过程 UI。
4. **续接证据**：在通用 `ToolResult` 中增加有界 `resume_text`，只承载最终答案、官方明确文档来源和请求生成的 provenance trace 标识；公开事件继续使用固定 `public_summary`。暂停/恢复沿用现有 trajectory，不创建服务端存储，也不依赖重复查询才能保留刚取得的结论。
5. **真实知识验收**：生产候选 collection 必须实际包含名称/别名、定义、规则、关系、来源和可检索图实体上下文；用普通分析或清洗语言验证定义、关系和一个需要自动补查的多部分问题。只读组确认不含 row embeddings、写操作和管理工具；现有 `structured_query` 不移除，另用真实受治理结构化记录场景验证它。
6. **Copilot 减少重复探测**：模型对话框复用已有 identity/model capability 结果，只在缓存缺失、连接变化或用户显式复测时访问网络。

完成条件：

- 完整用户输入覆盖“语义会改变结果而自动查”“用户规则明确或机械任务而跳过”“证据不足或服务不可用而不编造”，并断言单个语义缺口由 TrustGraph 原生 Agent 内部完成必要的多轮检索；
- 单元/前端测试覆盖精确目标优先、默认后备、未就绪不广告、tool-only registry、进度完成/失败、source/trace 旧数据兼容、`resume_text` 续接和 Copilot cache 复用；
- 真实验收记录业务知识准备内容、reader 身份、目标 collection、实际调用轮数和 trace，不提交业务数据或 secret；
- 聚焦测试通过后执行 `uv run pytest`、`yarn test` 和 `yarn build`，仍不把 Docker 或仓库外 TrustGraph 环境变成普通回归依赖。

A13 明确不做：新增 TrustGraph 查询工具、行级语义匹配、Data Formulator 摄取/管理 UI、动态目标注册中心、后台健康检查、服务端 resume 数据库、MCP 内部通道、第二套 Agent runtime，以及没有真实故障证据的额外 JSON/status 兼容分支。

实现结果（2026-08-20）：现有目标解析器支持精确 workspace key 优先、`default` 后备；`AnalystAgent` 用同一 resolver 和当前 identity reader credential 在请求构造期过滤 registry，真正调用仍重新解析。新增的状态 endpoint/UI 复用同一 resolver，只显示当前 Workspace 的本地配置状态，不访问 TrustGraph 网络。registry/system prompt 对称描述 tools/actions，TrustGraph 固定帧不再点名可选 `structured_query`，服务器现有只读组仍保留它。完整 `/api/agent/analyst-streaming` scripted 回归从未加载 Skill 的用户输入出发，覆盖自动加载并查询、明确规则/机械任务跳过、服务不可用时不编造。通用引用新增 `source|trace`，前端分组持久化并保持旧会话兼容；`query_business_context` 只有一个中英文进度；`ToolResult.resume_text` 与公开摘要分离，最大 1 Mi 字符并只用于浏览器续接 trajectory。Copilot capability store 复用成功和失败结果，连接生命周期继续失效缓存，UI 提供显式复测。

真实验证结果：本机默认目标和精确目标均解析为“已配置”，新建 Data Formulator Workspace 通过 `default` 使用当前 `Qwen/Qwen3.5-27B`、`thinking=off` 与真实 reader。普通多部分中文输入自动加载 TrustGraph，外层按两个独立语义缺口发起 2 次高层查询；两个官方 session trace 内部分别记录 2 次和 1 次 `knowledge_query`。用户明确固定映射规则时 0 次加载、0 次查询。临时把单个测试 Workspace 指向不存在的 Flow 后，Skill 自动加载、查询稳定返回 `protocol_error`，Qwen 明确保留原值且不编造；该临时坏目标已删除。以上使用领域中立合成知识，只证明产品链路，不冒充生产候选知识验收；整个过程未执行 Docker 命令，也未修改 TrustGraph 源码。

仓库验证结果：聚焦后端 106 项和前端 19 项通过；Windows UTF-8/TTY 后端全量 2346 项通过、13 项跳过、1 项 xfailed、1 项 deselected（仅既有符号链接权限项）；内置 Node 下前端 51 文件/412 项通过，Vite `7.3.3` 生产构建通过。Python compileall、`uv lock --check`、`uv pip check`、中英文 locale JSON、Markdown 相对链接/代码围栏、凭据模式扫描和 `git diff --check` 均通过。

### A14：`agent_explain` 实时查询步骤（已完成）

A14 只解决长查询期间“看起来卡住”和多轮检索不可见的问题，不改变外层工具、触发提示、知识准备、授权、最终答案或 Recipe 边界。完整数据流为：

```text
query_business_context
  → TrustGraphProvider.query_stream
  → official agent_explain WebSocket
  → BusinessContextProgress
  → Skill tool_progress
  → existing /analyst-streaming NDJSON
  → existing thinkingSteps
  → final ToolResult + context_info
```

按以下四个小步骤实施：

1. **WSS 前置与客户端合同**
   - 先让当前 allowlisted 9443 HTTPS 验证入口透传 `/api/v1/socket` Upgrade；生产仍使用同一个 `api_base`，不增加 `socket_base`。
   - 在 `test_trustgraph_client.py` 用假的官方 explain iterator 固定请求参数、事件顺序、最终答案聚合、两轮计数、socket close 和现有错误映射，再把 `TrustGraphClient.query()` 改成消费 `query_stream()`。
2. **Skill/Agent 流式工具合同**
   - `handle_tool` 允许同步 `ToolResult` 或生成器；TrustGraph Skill 把 provider progress 转为唯一新事件 `tool_progress`，最终仍返回现有 framed `ToolResult`。
   - Agent shell 只负责转发有限字段并继续发送既有 `context_info`/`tool_result`；现有同步 Skill、消息 trajectory、resume_text 和 Reasoning log 不改结构。
3. **现有运行步骤与轻量 trace**
   - `agentProgress.ts` 根据 `query_index` 原位更新一行：检索、筛选、汇总、完成；新一轮才增加一行，`finalizing` 显示“正在形成业务知识结论”。成功/失败仍由现有 `tool_result` 收口。
   - 不新建 Timeline 页面或状态库；成功 trace 只把标题更新为“TrustGraph retrieval trace · N queries”，结果 JSON 的 provenance 增加 `query_count`，不扩展 `ContextItem` schema。
   - 增加中英文固定文案和聚焦 Vitest，旧的单一进度、无 progress 事件、无 context item 场景保持兼容。
4. **真实回归与文档收口**
   - 先跑 Client/Provider/Skill/Agent 和前端聚焦测试，再执行 `uv run pytest`、`yarn test`、`yarn build`。
   - 用当前领域中立知识从真实 `/analyst-streaming` 输入完成一次自动两轮查询，确认浏览器看到有限步骤，NDJSON/日志中没有 Thought、Observation 正文、参数、triples、bearer 或答案 token；保留轮次和 trace，不把合成知识称为生产验收。

TrustKit 决策保持简单：不安装 `@trustgraph/trustkit`、`@trustgraph/react-state`、`@trustgraph/react-provider` 或 `@trustgraph/client`。它的 `ExplainTimeline` 和事件分类只提供交互参考；`AgentWithTimelineView` 自己拥有 Agent/session/state 链且当前包要求 React 19，不适合嵌入 React 18/MUI 的现有 AnalystAgent 页面。

Portal 决策同样保持简单：不安装或内嵌 `@trustgraph/portal`。它是完整应用且未发布为 npm 消费包，当前也没有按本次查询 trace 打开完整 Explain 页的稳定路由合同；A14 不为此增加 Portal URL、凭据透传、iframe 或自定义深链。将来只有官方提供稳定只读深链且部署确有独立 Portal URL 时，再单独评估一个普通外链，不改变本次实时步骤实现。

A14 明确不做：完整 explain DAG、图谱渲染、文档 provenance 反查、原始事件持久化、可点击 TrustGraph 管理入口、浏览器 WebSocket、自动重连服务、第二套 endpoint、第二个 Agent runtime、MCP 通道、TrustGraph 源码修改，以及为了未知未来事件增加多层 fallback。未知 provenance 只忽略，缺少终态答案才按现有 `protocol_error` 失败。

完成条件：

- 一轮和自动两轮的 fake iterator 合同均产生正确有限步骤、`query_count` 和最终答案；Thought/Observation/参数/triples 从未出现在公开事件。
- 完整 Agent 路径的事件顺序为 `tool_start → tool_progress* → context_info? → tool_result`，同步 Skill 行为不变，失败能结束当前进度。
- 前端相同轮次只更新一行，第二轮新增一行，最终 trace 与 document Sources 继续分组；中英文测试通过。
- 当前 HTTPS/WSS 入口和真实 Qwen/TrustGraph 完整查询通过，随后全量后端、前端和生产构建门禁通过。

实现结果（2026-08-20）：TrustGraph 客户端实际网络路径已经替换为官方 `agent_explain`，同步 `query()` 只消费同一 `query_stream()`，没有 REST fallback。provider 把 explainability entity 压缩为 `BusinessContextProgress`；Skill/Agent 只公开 `tool/query_index/phase` 四个字段，继续按原顺序发送 `context_info` 和最终 `tool_result`。AgentAnswer 只在服务端聚合到终态，Thought、Observation 正文、action 参数、triples 和未知 provenance 均不进入 NDJSON。成功结果 provenance 增加 `query_count`，trace 标题显示实际轮数。

现有前端 `thinkingSteps` 用一个轻量本地映射按 `query_index` 原位更新检索、筛选、汇总和完成；第二轮才新增一行，`finalizing` 增加结论行，最终仍由既有 `tool_result` 收口。未增加 Timeline 页面、状态库、TrustKit/Portal 依赖、浏览器 WebSocket 或新端点。

真实验收中，仓库外 9443 TLS 代理已透传 `/api/v1/socket` Upgrade；运行时组合公共 certifi 与本地 TrustGraph CA，公共 SiliconFlow `/models` 到达 401 鉴权边界且本地 WSS 到达 bearer 鉴权边界。真实 provider 对领域中立多部分问题自动产生两轮完整阶段并返回 `query_count=2`。真实 `/analyst-streaming` 从未加载状态自动完成 `load_skill → query_business_context → tool_progress* → context_info → tool_result → completion`；一次运行还观察到同一高层查询内部两轮。独立公开流扫描确认 progress 字段严格有界、bearer 和原始 explain 字段均未出现、公开工具结果保持安全摘要。真实浏览器会话进一步确认当前 Workspace 显示“业务知识已配置”，运行步骤实际从通用等待原位更新为检索、证据完成和结论，最终答案与独立不可点击的“检索轨迹（1）”正常落入会话。聚焦后端 97 项通过；Windows UTF-8/TTY 后端全量 2339 项通过、13 项跳过、1 项 xfailed、1 项 deselected（仅既有符号链接权限项）；内置 Node 下前端 51 文件/414 项和生产构建通过；compileall、锁文件与依赖一致性检查通过。

### A15：IOF 制造业知识准备与真实验收（已完成）

A15 不增加产品功能面，只把 A13/A14 从领域中立合成数据推进到可追溯的公开制造业知识：

1. 从 IOF 官方仓库固定 `Release_202602`、提交 `4c905ad22a93a1c6a5893d0907f32330074c8200`，选择 Annotation Vocabulary、Core 和 Production Planning；记录固定 blob URL、SHA-256、MIT 许可证及 Production Planning 的 provisional 状态。
2. 在 TrustGraph 部署侧把 4,835 条上游 RDF triples 写入 GraphRAG 实际查询的默认知识图；来源元数据和 RDF-star 派生关系写入 `urn:graph:source`，三个原始 RDF 文档写入 Library。用上游 label、定义、示例、父类和关系建立 218 个实体上下文，不在装载脚本中创造行业答案。
3. 用精确 SPARQL、英文语义检索和直接 GraphRAG 验证 Production Order、Production Plan、Manufacturing Operation、Machine 和 Process Plan 等实体及来源。
4. 用真实中文 `/analyst-streaming` 数据清洗输入验证自动 Skill 发现、一个高层查询内两轮检索、实时步骤和最终结论。直接中文 embedding 对英文 IOF 索引不稳定，因此固定任务帧只增加通用跨语言补查：首轮缺证时使用保持业务含义的常用语或英文等价词再查一次，最终仍以请求语言回答；没有制造业词表或字段名特判。
5. 查询失败按零证据处理，Skill 禁止用模型记忆、通用行业经验或未声明假设补答案。

真实结果：验证目标含三个原始文档、6,878 条知识/来源/溯源记录和 218 个实体上下文；精确查询与直接 GraphRAG 均命中固定 IOF 来源。真实表结构包含生产订单、生产计划、操作、设备、计划数量和事件时间字段，Agent 自动完成 `load_skill → query_business_context`，TrustGraph 内部两轮检索后建议不要合并三类对象，并正常 completion；没有 Python 或图表调用。相关 Client/Skill 聚焦测试 58 项通过。

锁定 `trustgraph-base==2.8.14` 的直接 GraphRAG 响应含来源，但高层 `AgentAnswer` 和 explain 事件不透传内部 source 列表。当前产品只保留真实 session trace，不增加第二条低层查询或从答案 URL 反推 citation。来源清单、哈希和部署合同见 [TrustGraph 制造业知识准备与验收](trustgraph-manufacturing-knowledge.md)。公共 IOF 验收不能替代组织自己的生产术语、编码、规则和来源治理；保留的 `structured_query` 仍需单独用真实受治理记录验收。

### A16：Collection 与知识 Profile 收敛（已实施并真实验收）

官方 [Workspace](https://docs.trustgraph.ai/overview/workspaces.html) 和 [data ownership model](https://github.com/trustgraph-ai/trustgraph/blob/0bcfe9377c3d55b7199c16335b9e52ed91286233/docs/tech-specs/data-ownership-model.md) 的边界是：workspace 负责所有权隔离，collection 是其中的扁平知识分区；各 RAG/structured 工具查询一个 collection，原生 Agent 只有通过 group 中多个 collection-bound 工具才能间接跨 collection。锁定源码也把 [`AgentRequest.collection`](https://github.com/trustgraph-ai/trustgraph/blob/0bcfe9377c3d55b7199c16335b9e52ed91286233/trustgraph-base/trustgraph/schema/services/agent.py#L30-L35) 明确标为 provenance trace collection。TrustGraph 不会因 Data Formulator 只给出 workspace 就自动发现并检索所有 collection。

A16 采用以下最小设计：

1. **先 Workspace，后 Collection**：授权或所有权不同先拆 workspace/Profile；当前调用不跨 workspace。同一 workspace 内只在发布生命周期、图关系或检索排名需要隔离时拆 collection；同一域的多个来源可通过 Knowledge Core 装入同一版本化 collection。它不按问题临时组合。
2. **Workspace 授权，Group 路由**：bearer/workspace 决定隔离和授权；group 只筛选该 workspace 内本轮 Agent 可见的工具，不建立第二套权限系统。每个可见知识域用一个描述明确的 collection-bound 工具表达；TrustGraph Agent 根据当前问题选择一个或多个并可多轮调用。Data Formulator 只传一个 group，不保存 collection 数组、不扫描 workspace、不 fan-out 或合并排名。
3. **Profile 只是现有 target 配置**：精确或默认 Profile 只包含 TrustGraph workspace、Flow、一个只读 group、trace collection、credential reference 和现有 timeout/size limits；不新增实体、数据库、管理 API 或前端选择器。
4. **领域工具稳定，collection 版本可切换**：工具名、描述和 group 标签不随发布版本改变；控制面验收新 collection 后只更新工具绑定，并按部署要求使配置生效；旧版保留用于人工回滚但不同时暴露给 Agent。
5. **代码只改三个语义错误**：`TrustGraphTarget.collection` 和目标 JSON 字段直接改为必填的 `trace_collection`，旧字段出现即配置失败；任务帧不再写死 `knowledge_query`；进度解析不再写死 `knowledge_query`/`structured_query` action 名，而依据可信 provenance 阶段显示通用查询轮次。

官方 [tool 配置](https://docs.trustgraph.ai/reference/configuration/config-types) 把 `collection` 作为 `knowledge-query` 的静态配置，group 不自动枚举 workspace collection。当前方案只面向少量稳定知识域；如果以后出现大量动态 collection，再把 catalog/router 作为 TrustGraph 能力单独设计，A16 不提前增加组件。

Knowledge Core 的生成、选取、装载、各域 collection 发布和 group 工具配置都是查询前的 TrustGraph 控制面工作，由官方 UI/CLI 与部署清单承担；`query_business_context` 请求期间不创建 collection、不调用 `load_kg_core`、不枚举 Core 或切换 group。当前“业务知识已配置”仍只表示 Profile 与 reader credential 在本地可解析，不冒充 group/collection 在线健康检查。

A16 已按以下顺序完成：

1. **字段合同**：删除 `TrustGraphTarget.collection`，改为必填的 `trace_collection`；同步更新目标解析、SDK 调用、当前开发配置和聚焦测试，并验证 `collection` 会被未知字段校验拒绝。
2. **通用 Agent 合同**：任务帧只引用“本轮可见的只读知识工具”；进度只依据 provenance 阶段计数，使用任意合法工具名的测试证明没有 action 硬编码。
3. **单域基线**：用一个干净版本化 collection 验证定义、关系、跨语言补查和证据不足路径。
4. **双域路由**：在同一 group 中配置两个稳定领域工具，分别验证只需工具 A、只需工具 B、必须同时使用 A+B 的三类问题。
5. **版本切换**：构建同一领域的新 collection 版本，直接验收后切换稳定工具绑定并使配置生效，确认 Data Formulator 配置和请求不变，并验证可切回旧版。
6. **完整门禁**：运行聚焦后端、全量后端、前端测试和生产构建，再更新 A16 工程记录；不把外部部署未完成写成代码已完成。

A16 验收分三层：

- **字段合同**：只接受必填 `trace_collection`，缺失或出现 `collection` 均配置失败；模型 payload 仍不能覆盖 Profile/group/collection；现有 source/trace、续接、错误和实时步骤保持不变。
- **单域真实路径**：新建不混合合成 fixture 的版本化知识域 collection；一个稳定的领域知识工具完成定义、关系和自动补查场景。
- **跨域真实路径**：用同一 group 的两个 collection-bound 只读工具验证当前问题触发的单域选择和跨域多轮；`agent_explain` 仍只公开通用轮次。如果锁定版本不能把子查询来源或 trace 完整关联到父 session，只记录该协议边界，不在 Data Formulator 补做低层二次查询。

路由验收不依赖 hidden thought 或 UI 猜 action：先分别直接查询两个 collection，确认每个域都有独占、可核对来源的事实；再让 Agent 回答 A-only、B-only 和必须组合两域事实的问题。Data Formulator 产品侧只断言最终证据、通用 `query_count` 和 session trace；验收脚本使用官方 provenance 的精确 `tg:action` 元数据核对实际工具，不把 action、thought 或参数传到产品事件。工具绑定与 collection 版本由 TrustGraph 控制面部署记录证明。

真实验收 group 当前包含三个只读工具：稳定业务术语工具绑定干净 `dfm-business-glossary-v3`，稳定制造业本体工具绑定 `dfm-iof-release-202602-v2`，既有 `structured_query` 保持原配置。A-only 只调用术语工具，B-only 只调用本体工具，A+B 分别调用两者；`structured_query` 未被这些知识问题误用。业务术语同一 Core 另发布到 `dfm-business-glossary-v4`，直接 GraphRAG 验证后只切换稳定工具绑定，Data Formulator 请求不变且成功，随后已回滚到 `v3`。这些是分域路由和发布验收集合，不是组织生产默认值。

A16 仓库门禁：聚焦后端 101 项、Analyst 后端 94 项通过；Windows UTF-8/TTY 全量后端 2343 项通过、13 项跳过、1 项 xfailed、1 项 deselected（仅既有 symlink 权限项）；内置 Node `24.19.0` 下前端 51 文件/414 项和 Vite `7.3.3` 生产构建通过；Python compileall、`uv lock --check` 和 `uv pip check` 通过。

## 7. 合同与功能测试矩阵

| 层 | 必测场景 |
| --- | --- |
| 值对象 | 空/超限 question、可选 context、空 identity/workspace、非法 source URI、socket timeout/response budget |
| 配置 | flag 未设置/false；关闭态不读 vault；精确 workspace Profile 优先、`default` 后备、两者均无；请求时 reader credential 就绪/缺失；`trace_collection` 必填且 `collection` 作为未知字段拒绝；旧六工具字段拒绝；HTTPS/userinfo/query/fragment/origin |
| 提示与 Skill | 仅一个高层工具；tool-only registry 明确列出工具；未决含义会改变结果才查询；明确规则/机械操作跳过；固定帧只使用当前 group 实际提供的只读知识工具并依据描述选择，不出现固定内部工具名或 collection；不得发明 search/browse；不做行级语义匹配；最小上下文字段齐全；不发送整表/原始敏感值/完整聊天/代码/路径/凭据/路由 |
| 请求 | 官方 `agent_explain` WebSocket；bearer；服务端 workspace/Flow/trace collection/group；retrieval collection 由 group 工具绑定；session id；空 history；模型参数不能覆盖 Profile；同一 `api_base` 的 WSS Upgrade；结束/异常时 socket close |
| 响应与引用 | provenance 只映射有限 phase 和 `query_count`；聚合终态 `AgentAnswer`；丢弃 Thought、Observation 正文、参数、triples 和 answer token 事件；仅接收官方显式 `sources`；答案中的任意 URI 不生成 citation；文档标 `source`、session provenance 标 `trace`；旧数据默认 source；缺少终态答案失败关闭 |
| 大小 | question/context、wire prompt、答案 JSON、source title/URI、引用数量和截断后 JSON 边界；UTF-8/中文不破坏 |
| 错误 | socket 认证/心跳 timeout；上游 Agent timeout；401/403；429；5xx；连接失败；无效 JSON；SDK/REST 合同漂移 |
| 清洗 | token、URL query、response body、外部异常文本不出现在稳定错误、流或日志字段中 |
| 兼容 | 不导入 TrustGraph Skill 时现有 registry 不变；现有 `ToolResult(text, images)` 构造保持兼容；缺少 `kind`/`resume_text` 的旧 Session 正常恢复 |
| 用户交互 | `query_business_context` 先显示通用进度，再按真实 `query_index` 原位更新检索/筛选/汇总/完成并在成功/失败后收口；任意合法工具 action 名不影响通用 provenance 阶段和轮次；Sources 与 Retrieval trace 分组正确，成功 trace 显示查询轮数；暂停续接使用有界 `resume_text` 而非固定成功摘要 |
| 真实场景 | 从未预加载 Skill 的完整 `/analyst-streaming` 输入验证清洗/映射/分组前的业务含义缺口；干净的单知识域 collection 完成定义/关系/自动补查；双知识域工具组完成 A-only、B-only 和 A+B 查询时路由；稳定领域工具切换新旧 collection 版本时 Data Formulator 配置不变；实时步骤与真实 provenance 一致；明确用户规则和机械任务跳过；证据不足/服务不可用不编造；同一语义缺口不机械重复外层调用 |
| Copilot | 已有三项 capability 结果时打开模型对话框不发起新探测；缓存缺失、连接变化和显式复测会探测并更新资格 |
| 范围边界 | Skill 不出现目录/RDF/SPARQL/GraphQL/row-embeddings/摄取/管理工具；查询路径不创建 collection、不调用 `load_kg_core`、不枚举 Core 或修改 group；不触碰 Workspace；Data Formulator 不新增自制 TrustGraph 工作台 |

## 8. 验证策略

开发中按风险递增运行：

1. 新增的 business context / TrustGraph 聚焦测试。
2. 现有 analyst、skills、model registry、auth 和 session 聚焦测试。
3. `uv run pytest`；Windows 环境差异不得用修改产品语义的方式掩盖。
4. `yarn test`。
5. 使用满足 Vite `7.3.3` 要求的 Node 版本执行 `yarn build`。

仓库开发和回归不启动 Docker。仓库外 WSL2 真实探针必须由显式人工命令运行，默认测试永不访问网络，也不依赖该环境。

## 9. 可观测性与隐私

允许记录：

- feature flag 状态；
- provider 和内部 target 名称；
- 稳定错误 category；
- HTTP/WebSocket status、耗时区间、响应字节数、source/trace 数量、查询轮数和有限 phase；
- capability probe 的布尔结果和模型标识。

禁止记录：

- bearer/access/Copilot token、device code；
- Authorization header、完整 credential reference；
- SPARQL 正文、RDF/literal 内容、TrustGraph 响应正文；
- AgentThought、AgentObservation 正文、工具参数、原始 provenance triples 和 token 级答案；
- 外部 response body 或带 query/fragment 的 URL；
- identity id 的原值。需要关联时使用现有安全的 request/correlation id。

## 10. 回滚与兼容

- 每个纵向切片由独立 flag 或尚未注册的模块隔离，可在不迁移数据的情况下撤回。
- 通用数据类型只新增可选字段，旧 Session 和旧前端数据按空引用处理。
- provider/Skill 不修改现有本地知识实现；TrustGraph 失败只影响本次可选查询。
- Copilot 不改变现有 provider 的凭据或模型命名；关闭 flag 后注册表恢复当前行为。
- 不在 M0-A 修改热点文件 `app.py`、`src/app/App.tsx` 或 Redux 根类型；到纵向集成时采用小型注册提交。

## 11. 外部条件与停止线

以下条件不能通过本分支自行假设或绕过：

- TrustGraph 真实 base URL、允许的 Flow/workspace/只读工具组、trace collection、各工具绑定的 retrieval collection 和测试 bearer token。
- 同一 allowlisted HTTPS base 对 `/api/v1/socket` 提供有效 WSS Upgrade；当前本机 9443 验证入口已经满足并完成真实 Agent explain 回归，生产入口仍需按部署环境确认。
- 生产 origin allowlist、credential vault 生命周期和管理员配置方式的最终确认。

GitHub Copilot 测试 identity 条件和仓库外 TrustGraph 的历史结构化接口冒烟均已完成。A12 的原生 Agent target、reader bearer、只读工具组、Qwen 配置和部署重载，A14 的 HTTPS/WSS 实时步骤，A15 的固定版本 IOF 制造业知识一轮/自动两轮/中文成功场景，以及 A16 的字段硬切、通用提示/进度、干净单域、双知识域路由和版本切换/回滚均已完成。企业生产知识、collection、workspace、工具组和 bearer 仍是部署条件，这些值不硬编码到本分支；保留的 `structured_query` 仍需真实受治理结构化记录场景验收。若后续官方 SDK、REST 文档与真实服务再次不一致，先记录精确差异并更新合同测试，不增加无边界兼容猜测。

生产候选知识验收使用以下最小清单，不在 Data Formulator 建设摄取流程：

1. 通过 TrustGraph 官方 UI/CLI 让固定版本公共知识与组织名称、别名、定义、适用规则、关键关系和来源形成可追溯的 Knowledge Core；部署清单记录 Core id 和来源版本。ontology 配置本身不算已导入知识。
2. 先按授权和所有权选择 TrustGraph workspace；不同 workspace 不由一次 Data Formulator 查询联邦访问。
3. 在同一 workspace 内按发布生命周期和知识连通性决定 collection 边界；只把同一治理域需要的 Core 装入该域的干净版本化 collection，并建立对应知识工具可检索的图实体上下文。不要按测试问题临时组合，也不要把 Data Formulator 配成 collection fan-out 客户端。
4. 在同一只读 Agent group 中为每个本轮可见知识域配置名称和描述稳定的 collection-bound 查询工具；新版本直接验收后切换工具绑定，旧版、测试和归档 collection 不同时进入 Agent 可见工具集。
5. 为知识 Profile 创建只读 reader bearer，并用现有 vault reference 绑定 `default` 或精确 workspace target；Profile 的 `trace_collection` 不作为 retrieval collection 清单。
6. 用普通业务语言分别验证一个定义问题、一个关系问题和一个需要 Agent 自动补查的多部分问题；保留最终答案、调用轮数和 session trace，不保存 hidden thought。再补 A-only、B-only 和必须使用两个可见工具的 A+B 场景。
7. 确认只读工具组不含 row embeddings、写操作或管理工具；保留现有 `structured_query`，并用真实受治理结构化记录场景补充独立验收。

## 12. 当前执行顺序

已完成：

1. 落地本文并从 Feature 工程记录链接。
2. 为通用结果/引用值对象和 TrustGraph 官方 SDK 适配先写失败测试。
3. 实现最小 `base.py` 与 `trustgraph.py`，使用官方 API/RDF translator 完成本体、三元组和只读 SPARQL 客户端；当时尚未注册 Skill 或修改 UI。
4. 完成聚焦、相邻、后端全量、前端全量和生产构建验证并更新工程记录。
5. 完成 A1 授权上下文、通用引用路由、安全工具摘要和异常边界；新增合同测试、相邻回归及完整交付门禁均通过。
6. 完成 A2 默认关闭的 TrustGraph Skill、服务端 workspace 目标映射和 identity-scoped vault 解析；当前工具面已收敛为本体、三元组、只读 SPARQL，目标覆盖、非对象参数和稳定故障均有 Agent 级测试。
7. 完成 A3 前端引用累计、逐制品/最终文本绑定、Session 与 ZIP 往返持久化、安全 Sources 展示；旧会话和无引用路径保持不变。
8. 完成 A4 应用拥有的 Copilot device flow、identity-scoped vault 生命周期、默认关闭路由、显式连接 UI 和普通模型请求失败关闭保护；全量后端 2274 通过、13 跳过、1 xfailed、1 个 Windows 符号链接权限项未运行，前端 403 通过，生产构建通过。
9. 完成 A5 LiteLLM `1.91.3` 版本/源码指纹保护、请求及惰性 stream 局部 Authenticator 适配、两层 token 生命周期、显式候选模型注册、identity-scoped 三项 capability probe 和前端资格撤销联动；离线聚焦回归 101 项、后端全量 2302 项、前端 406 项、生产构建和 diff 检查通过。
10. 完成 A7 离线集成门禁并刷新远端引用；`origin/main` 与 `upstream/main` 仍为固定基线 `5477f0e`，未合并移动的 `dev`；仓库默认回归未启动 Docker。
11. 完成 A6 Copilot 真实账号 device flow、`gpt-4.1` chat/streaming/tools、短期 token 刷新和明文泄漏复核；用仓库外官方 npm CLI/SDK 作旁证，但未改变产品运行时。TrustGraph 改为 Windows 可直接安装的官方 `trustgraph-base==2.8.14`，离线结构化合同 70 项通过；仓库外 WSL2 服务已验证本体、knowledge/provenance triples、SPARQL 和完整 Skill 路径。
12. 完成最终交付门禁：`uv pip check` 通过；分支收口时后端 2352 项通过、13 项跳过、1 项 xfailed，仅按既有记录 deselect 1 个需要 Windows 符号链接权限的测试；前端在内置 Node `24.19.0` 下 49 个文件、406 项通过，生产构建通过；此前 Linux Node `22.14.0` 结果保持有效。
13. 完成 A8 知识目录与图实体语义检索的客户端、Provider、Skill 合同与最小实现；聚焦 95 项、相邻回归 152 项和后端全量 2336 项通过。
14. 按用户确认撤回 TrustGraph rows 直接入表/同步，并完成 A9 只读 GraphQL rows；聚焦 109 项、相邻回归 166 项和后端全量 2350 项通过。
15. 完成 A8/A9 的真实空环境非破坏性冒烟：目录、图实体搜索、triples、SPARQL 真实链路通过；rows 缺少 schema 与 ontology 缺少配置均准确返回 `not_configured`；新增 rows 正反合同后聚焦 111 项通过。
16. 按用户确认取消 A10、行数据语义搜索和 Data Formulator 内 TrustGraph UI；保留官方 TrustGraph UI 独立使用。

17. 完成 A12 单个 `query_business_context`、`BusinessContextProvider.query()`、TrustGraph 原生 Agent 客户端、最小上下文提示和 120 项聚焦合同。
18. 完成专用只读 Agent group、目标 collection、reader bearer、Qwen Flow、Qwen variant、`thinking=off` 和 SiliconFlow key 配置；真实请求已到 Agent，准确暴露运行进程旧 token 的 `unavailable`。

19. 按用户明确授权完成仓库外 TrustGraph text-completion/control 重载，重跑原生 Agent 真实成功场景和 Data Formulator 完整交互。
20. 完成 ontology/图谱统一检索的数据准备、精确 SPARQL/GraphRAG 验证、Agent 一轮与自动两轮 trace、中文输入，以及无 row embeddings/MCP 死配置的收口。

21. 完成 `default` 目标后备、请求时就绪判断、当前 Workspace 配置状态、tool-only registry 和完整用户输入三类回归，确认自动查询逻辑真实可达。
22. 完成单一进度、`source`/`trace`、有界 `resume_text` 和旧 Session 兼容，未增加 TrustGraph 管理 UI 或恢复服务。
23. 完成固定版本 IOF Core/Production Planning 的公开制造业知识装载、来源验证和真实中文清洗两轮验收；待部署方再用组织自己的生产候选知识执行定义、关系和多部分问题验收，并为已保留的 `structured_query` 补一个确实需要受治理结构化记录的场景。
24. 完成 Copilot capability cache 复用、显式复测，以及聚焦/全量后端、全量前端和生产构建门禁。
25. 完成 A14：9443 WSS Upgrade、客户端/Provider/Skill/Agent 流式合同、现有运行步骤、轻量 trace 查询轮数和真实一轮/两轮全链路回归均已落地。
26. 完成 A16 Collection/Profile 设计纠偏：确认 workspace 承担授权隔离，collection 是同一 workspace 内按治理域形成的扁平分区，检索范围由 group 工具绑定，未知问题由 Agent 在查询时路由，`AgentRequest.collection` 是 trace 语义；不再把跨域总集合作为默认。
27. 完成 A16 实现和真实验收：硬切 `trace_collection` 且拒绝旧字段，任务帧与进度移除 action 硬编码；完成业务术语、制造业本体的 A-only/B-only/A+B 路由，以及稳定工具 `v3 → v4 → v3` collection 绑定切换。
28. 完成 TrustGraph Profile 配置语义收口：删除无消费者字段，使用 `socket_timeout_seconds` 表达官方 WebSocket SDK 的真实超时语义，状态 API/UI 只声明 `configured/unconfigured`；跨语言等价词提前到首轮调用后，真实双域查询由四轮降为两轮。Explainability 的 REST triples 合同缺口已提交上游 [trustgraph-ai/trustgraph#1096](https://github.com/trustgraph-ai/trustgraph/pull/1096)，当前产品继续锁定官方 `2.8.14`，不依赖个人 fork。

当前执行：A14-A16 主路径和本轮 Profile 配置语义收口均已完成。后续部署工作只剩组织自己的生产候选知识，以及保留的 `structured_query` 真实受治理结构化记录场景；二者不通过 Data Formulator 增加摄取或路由层解决。上游 Explainability 修复只有在官方发布后才升级并重跑真实合同。

`acdfb3c5` 保留 A0-A11 的技术基础和历史验证，`3d345091` 包含 A12 原生 Agent 收敛及配套文档。A12 产品代码和真实验收已经完成；六工具历史结果只作为底层技术证据。
