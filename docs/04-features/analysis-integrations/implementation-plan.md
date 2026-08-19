# Analysis Integrations 实施方案

## 1. 文档状态

| 项目 | 内容 |
| --- | --- |
| 适用分支 | `feat/analysis-integrations` |
| 固定上游基线 | Data Formulator `0.8.0b1` / `5477f0e236426dc8f74a498ec400414fba7fbc0f` |
| 当前目标 | 在同一个 `AnalystAgent` 与 Data Formulator 工作区中增加可发现、可查询的 TrustGraph 本体/RDF 知识图谱能力和可选 GitHub Copilot 模型 |
| 当前实施节点 | A0-A9 已完成并提交为 `acdfb3c5`；行语义搜索、A10 知识准备和 Data Formulator 内 TrustGraph UI 已取消；后续只做真实业务数据验收 |
| 外部验证节点 | M0-B：Copilot 和仓库外 TrustGraph `2.8.14` 验收均完成；生产目标和真实业务本体/数据仍由部署方后续提供 |
| 最后更新 | 2026-08-19 |

本文把项目级架构约束细化为 Analysis Integrations 分支可执行的代码、测试和验收计划。项目事实来源仍以当前检出源码和测试为准；实现决定变化后，应同时更新本文和同目录工程记录。

## 2. 目标与非目标

### 2.1 交付目标

1. 建立供应商无关的业务上下文结果、稳定错误和结构化引用契约。
2. 将 Data Formulator 后端已经授权的 identity 和 workspace 明确传入 Skill，不从模型参数或前端 payload 推断。
3. 通过官方 Python SDK 展示 TrustGraph Flow、collection、document、processing 和 Knowledge Core 目录，并提供图实体语义发现。
4. 以只读 Skill 接入 TrustGraph 本体、RDF 三元组、来源图和 SPARQL 查询；不调用 Graph RAG，也不让 TrustGraph 生成自然语言答案。
5. 通过显式 GraphQL 只读查询 TrustGraph rows；结果保持结构化，但当前阶段不写入 Data Formulator 表或 Workspace，也不做同步。
6. 将引用从 Skill 结果送入 Agent 流，并持久化到 Data Thread 的对应消息或产物。
7. 在现有 LiteLLM Client 路径中接入 GitHub Copilot device flow，不引入 Copilot SDK 或第二套 Agent runtime。
8. 对 Copilot 模型逐个探测 chat、streaming 和 tools 能力，只注册符合当前 `AnalystAgent` Chat Completions 契约的模型。
9. 复用官方 `trustgraph-ui` 承担管理和完整图谱可视化，不在 Data Formulator 复制工作台。
10. 保证 `TRUSTGRAPH_ENABLED=false` 和 `GITHUB_COPILOT_ENABLED=false` 时没有残留 Skill、API、模型或 UI 行为。

### 2.2 明确不做

- 不实现 Recipe、Schedule、Run、Worker 或后台 Executor。
- 不接入 `row_embeddings_query()`，不增加行数据语义搜索。
- 不在 Data Formulator 暴露文档摄取、processing、Knowledge/Context Core load/unload/bulk 或其他 TrustGraph 写操作。
- 不复制、vendoring 或重写 TrustGraph 官方工作台组件；需要管理和完整可视化时使用独立官方 `trustgraph-ui`。
- 不在正常 Recipe Run 中调用 LLM、TrustGraph 或 Workflow Replay。
- 不把 GitHub access token、Copilot 短期 token 或 TrustGraph bearer token写入前端状态、日志、Recipe、普通配置文件或测试夹具。
- 产品实现和默认开发/回归不使用 Docker、Docker Compose、LiteLLM Proxy、Copilot SDK 或额外消息基础设施；用户明确授权的仓库外 WSL2 验收环境不进入产品依赖。
- 第一版不注册 LiteLLM 标记为 Responses-only 的 Copilot 模型。

### 2.3 功能优先调整（2026-08-19）

后续实施以用户能直接使用的知识能力为里程碑，不再为凭据隔离、输出大小限制或引用清洗单独开新切片。A0-A7 已形成的相关基础设施保持现状并作为回归边界；A8/A9 已完成知识发现和只读结构化查询。2026-08-19 再次收缩范围：取消行数据语义搜索及 A10 文档/Context Core 知识准备，不实现 TrustGraph rows 入表、同步或刷新，也不自建 TrustGraph UI。

TrustGraph 内部接入优先复用官方 Python SDK。官方 MCP server 适合给外部 MCP 客户端提供兼容能力，但它没有提供 SDK 无法覆盖的内部产品能力；因此不在 Python 后端再增加 MCP transport、会话和工具参数转换层。

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
  │               服务端 workspace → target 显式映射
  │                                    │
  │                         官方 Python SDK
  │                                    │
  │            目录/语义/RDF/SPARQL/GraphQL rows
  │                                    │
  │                 结构化 JSON + context_items
  │                                    │
  └──────────────────────────── Agent event router
                                       │
                              Data Thread 持久化引用
```

信任边界规则：

1. identity 和 Data Formulator workspace id 只能来自后端认证/授权路径。
2. 模型只能选择本体读取、S/P/O/graph/limit 或只读 SPARQL；不得提交 base URL、flow、collection、ontology id、TrustGraph workspace、credential id 或 token。
3. 服务端配置把 Data Formulator workspace 映射到固定目标；没有映射时失败关闭。
4. 外部返回的文本、title 和 URI 都是不可信数据，先规范化、限长、去重和清洗，再进入模型或前端。
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

通用层只承载结果、引用和错误；TrustGraph 的主动查询使用结构化类型，不再把自然语言问答当成 provider 合同：

```python
@dataclass(frozen=True)
class ContextItem:
    uri: str
    title: str | None = None
    provider: str = ""

@dataclass(frozen=True)
class BusinessContextResult:
    text: str
    context_items: tuple[ContextItem, ...] = ()
    truncated: bool = False

class TrustGraphProvider(Protocol):
    def inspect_catalog(
        self,
        authorization: SkillAuthorization,
    ) -> BusinessContextResult: ...
    def search_entities(
        self,
        query: TrustGraphEntitySearch,
        authorization: SkillAuthorization,
    ) -> BusinessContextResult: ...
    def get_ontology(self, authorization: SkillAuthorization) -> BusinessContextResult: ...
    def query_triples(
        self,
        query: TrustGraphTripleQuery,
        authorization: SkillAuthorization,
    ) -> BusinessContextResult: ...
    def query_sparql(
        self,
        query: TrustGraphSparqlQuery,
        authorization: SkillAuthorization,
    ) -> BusinessContextResult: ...
```

约束：

- provider 在每个操作上重新核对 identity/workspace scope；授权上下文只用于服务端解析目标和凭据，Data Formulator identity/workspace 不原样发给外部服务。
- `inspect_catalog` 无模型可覆盖的目标参数；返回当前 target 及 Flow、collection、document、processing、Knowledge Core 的规范化快照。
- `TrustGraphEntitySearch` 只接受查询文本和 limit；客户端调用官方 embedding 与 graph-embeddings 服务并返回 RDF term/score。
- `TrustGraphTripleQuery` 只接受可选 subject/predicate IRI、typed object、`knowledge|provenance` 和有界 limit；`TrustGraphSparqlQuery` 只接受有界查询文本和 limit。
- `BusinessContextResult.text` 对 TrustGraph 始终是可解析、有大小上限的 JSON；模型看到明确的不可信数据帧，不接收由 TrustGraph 生成的回答文本。
- `ContextItem.uri` 必填，`title` 可空，`provider` 由后端赋值而不是相信外部字段。
- 来源按规范化 URI 去重，保留首次出现顺序；数量和单字段长度有上限。
- 外部正文超限时在明确边界截断并标记 `truncated`，不把完整内容写入日志。

### 5.3 引用输出与持久化

`ToolResult` 扩展 `context_items`，Agent router 负责：

1. 再次校验通用引用结构。
2. 发送供应商无关的 `context_info` 事件，不暴露 bearer、内部 target id 或原始响应。
3. 只在 Reasoning log 记录数量、provider 和稳定错误类别，不记录查询正文、来源正文或 token。
4. 前端把本轮引用与产生它的交互绑定，并写入 `InteractionEntry` 和最终 `TextTurn`。
5. 恢复 Session、导出/导入和历史回放后引用仍存在。

建议前端类型：

```ts
type ContextItem = {
  uri: string;
  title?: string;
  provider?: string;
};
```

已有历史数据缺少字段时按空数组处理，不做破坏性迁移。

### 5.4 TrustGraph 目标配置

配置分成全局策略和 Data Formulator workspace 到 TrustGraph 目标的显式映射。实现复用现有环境配置与 JSON 解析，不增加 YAML/文件监听器：

```text
TRUSTGRAPH_ENABLED=false
TRUSTGRAPH_TARGETS_JSON={...}
DF_ALLOWED_API_BASES=https://trustgraph.example.com/*
```

`TRUSTGRAPH_TARGETS_JSON` 顶层 key 是已经授权的 Data Formulator workspace id；value 只保存非 secret 配置及 credential reference：

```json
{
  "df-workspace-id": {
    "name": "finance-prod",
    "api_base": "https://trustgraph.example.com",
    "flow_id": "finance-graph",
    "collection": "policies",
    "trustgraph_workspace": "finance",
    "ontology_id": "finance-ontology",
    "credential_ref": "trustgraph:finance-prod",
    "connect_timeout_seconds": 3,
    "read_timeout_seconds": 30,
    "max_sparql_chars": 8000,
    "max_results": 100,
    "max_response_chars": 131072,
    "max_context_items": 50
  }
}
```

对应 identity 的 bearer token 使用现有 `/api/credentials/store` 合同写入加密 vault，source key 必须与 `credential_ref` 一致：

```json
{
  "source_key": "trustgraph:finance-prod",
  "credentials": {"bearer_token": "<secret>"}
}
```

规则：

- flag 默认关闭；Skill frontmatter 通过通用 `enabled_if` 门控制，关闭时不读取目标 JSON、不解析凭据、不注册或导入 Skill。
- 启用时配置缺失、目标未映射、base URL 未通过现有 `validate_api_base` allowlist、URL 含 userinfo/query/fragment、非 HTTPS 或 credential 缺失都失败关闭。
- `api_base` 在生产和测试均只接受 HTTPS；离线测试使用 HTTPS 会话替身，不为测试增加 HTTP 绕过。
- `credential_ref` 必须使用独立的 `trustgraph:` namespace 并通过现有 identity-scoped vault 解析；目标 JSON 不能内嵌 bearer token。

### 5.5 TrustGraph 请求与响应

M0-A 使用官方 `trustgraph-base==2.8.14` 同步 API，并注入可测试的 `requests.Session`。一个很小的 `Api` 子类只补官方版本未开放的请求安全控制：精确路径白名单、禁止 redirect、connect/read 分离 timeout 和 session 注入；它不是自定义传输协议或网络代理。

本体读取由官方高层配置 API 构造请求：

```text
POST {api_base}/api/v1/config
operation=get, key=(type=ontology, key={server-bound ontology_id})
```

图查询由官方 `FlowInstance` 完成：

```text
POST {api_base}/api/v1/flow/{flow}/service/triples
POST {api_base}/api/v1/flow/{flow}/service/sparql
Authorization: Bearer <resolved token>
```

三元组请求只含服务端 collection/workspace、`streaming=false`、有界 limit、可选 S/P/O 和 `g`。知识图使用默认图，来源图固定 `g=urn:graph:source`。SPARQL 在发网前由 `rdflib>=7.1,<8` 解析，只允许 `SELECT`、`ASK`、`CONSTRUCT`、`DESCRIBE`，递归拒绝 `SERVICE`；TrustGraph 更新接口不在 Skill 中暴露。

输入输出复用官方 `TermTranslator` 和 `TripleTranslator`。适配结果保留：

- IRI 和 blank node；
- literal value、datatype 和 language；
- RDF-star quoted triple；
- named graph；
- SPARQL query type、variables/rows、ASK boolean 或 graph triples。

结果数量、引用数量和完整 JSON 大小分别受限；超限返回仍是有效 JSON 的截断 envelope，不产生半截 JSON。响应类型、binding 宽度、RDF term 或 ontology 结构漂移统一按稳定 `protocol_error` 处理。

### 5.6 稳定错误分类

外部异常不得把原始 URL、response body、headers 或 exception 文本传给模型/前端。第一版类别：

| 类别 | 触发 | 面向 Agent 的稳定语义 | 可重试 |
| --- | --- | --- | --- |
| `disabled` | flag 关闭 | 该能力未启用 | 否 |
| `not_configured` | workspace 无目标/凭据 | 该 workspace 未配置业务上下文 | 否 |
| `invalid_request` | 非对象参数、非法 IRI/RDF term、超限、SPARQL 更新或 `SERVICE` | 查询不符合合同 | 否 |
| `unauthorized` | 401/403 | 业务上下文认证失败 | 需要人工处理 |
| `timeout` | connect/read/total 超时 | 服务暂时超时 | 是 |
| `unavailable` | 网络错误、429、5xx | 服务暂时不可用 | 是 |
| `protocol_error` | 无效 JSON/合同漂移 | 服务响应不符合预期 | 否，先检查集成 |

日志只包含 category、目标的非敏感内部名称、HTTP status（如适用）和 correlation id。原始异常可以作为 `raise ... from ...` 的内部 cause 保留，但不得被序列化到用户事件。

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

不建设 Data Formulator 内的 TrustGraph 工作台或导航入口。官方 `trustgraph-ui` 已提供 Knowledge Explorer、Ontology Workbench、SPARQL Workbench、GraphQL Workbench、Document Ingestion 等完整界面，并发布 `@trustgraph/trustkit` 组件库。npm 实时注册表显示 `trustkit@2.0.3` 要求 React 19，而 Data Formulator 使用 React 18；因此不复制组件源码、不升级应用基线，官方 UI 作为独立应用使用。

完成条件：A8/A9 使用真实业务 collection 完成非破坏性验收。只有存在明确外部客户端需求时才补 MCP 配置说明，产品内部仍使用 Python SDK；Data Formulator 前端不增加 TrustGraph 页面、组件或链接。

当前进展（2026-08-19）：已用仓库外真实 TrustGraph 服务逐一冒烟六个只读工具。目录返回 1 个 Flow 和 1 个 collection，图实体搜索、knowledge triples 均正常返回空结果，SPARQL `ASK` 正常返回 `true`；GraphQL rows 与 ontology 分别因未装载 schema 和 0 个 ontology 配置返回 `not_configured`。这证明传输、认证、Skill/Provider/SDK 调用和错误边界可用，但不等于真实业务数据验收完成；A11 仍等待带业务 ontology、rows schema 和实体数据的 collection。

## 7. 合同与功能测试矩阵

| 层 | 必测场景 |
| --- | --- |
| 值对象 | 非法 IRI、typed literal datatype/language 冲突、空 identity/workspace、空 URI、非法 timeout/limit/response budget |
| 配置 | flag 未设置/false/非法值；关闭态不读文件；启用态缺目标；workspace 无映射；HTTP/userinfo/query/fragment；origin 不允许 |
| 请求 | config/triples/官方 SDK sparql 精确路径；bearer；服务端 workspace/collection/ontology；knowledge/provenance graph；模型参数不能覆盖目标 |
| SPARQL | `SELECT`/`ASK`/`CONSTRUCT`/`DESCRIBE`；拒绝 update、`SERVICE`、语法错误和超限查询 |
| 响应 | IRI、blank node、typed/language literal、RDF-star、named graph；SELECT binding、ASK boolean、graph triples；类型漂移 |
| 大小 | SPARQL、结果数、完整 JSON、title、URI、引用数量边界；UTF-8/中文不破坏 |
| 错误 | connect/read timeout；401/403；429；5xx；连接失败；无效 JSON；SDK/REST 合同漂移 |
| 清洗 | token、URL query、response body、外部异常文本不出现在稳定错误、流或日志字段中 |
| 兼容 | 不导入 TrustGraph Skill 时现有 registry 不变；现有 `ToolResult(text, images)` 构造保持兼容 |
| 知识目录 | Flow、collection、document、processing、Knowledge Core 正常/空列表、时间与可选字段规范化、SDK 返回形状漂移 |
| 语义检索 | query/limit 校验；embeddings → graph-embeddings 两次官方调用；RDF entity/score、空向量、非有限数、空结果与超限 |
| 结构化查询 | 显式 GraphQL、variables、operation name、data/errors/extensions 与协议漂移；断言不创建 table、不写 Workspace、不做同步 |
| 范围边界 | Skill 不出现 `row_embeddings_query`、Library/processing 或 Knowledge/Context Core 写工具；Data Formulator 不新增自制 TrustGraph 工作台 |

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
- HTTP status、耗时区间、响应字节数、来源数量；
- capability probe 的布尔结果和模型标识。

禁止记录：

- bearer/access/Copilot token、device code；
- Authorization header、完整 credential reference；
- SPARQL 正文、RDF/literal 内容、TrustGraph 响应正文；
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

- TrustGraph 真实 base URL、允许的 flow/collection/workspace/ontology 和测试 bearer token。
- 生产 origin allowlist、credential vault 生命周期和管理员配置方式的最终确认。

GitHub Copilot 测试 identity 条件和仓库外 TrustGraph 的真实结构化调用/错误边界冒烟均已完成；有数据的 GraphQL rows 与业务语义验收尚未完成。生产 TrustGraph 的真实 business ontology、collection、workspace、rows schema 和 bearer 仍是部署条件，不硬编码到本分支。当前保留的只读目录与查询能力不需要为摄取流程配置 SiliconFlow 模型。若后续官方 SDK、REST 文档与真实服务再次不一致，先记录精确差异并更新合同测试，不增加无边界兼容猜测。

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

当前执行：

17. A11 等待带业务 ontology、GraphQL rows schema 和实体数据的真实 collection 后完成结果语义验收；MCP 仅在出现明确外部客户端需求时补兼容说明。

分支实现与测试已提交为 `acdfb3c5`；除上述外部业务数据验收外，没有剩余产品代码切片。

当前不再有阻塞 A8/A9 实现的外部条件。生产部署仍需配置真实 workspace 映射、ontology id、collection 和 bearer，并用实际业务数据完成语义与结构化查询验收；取消的管理/摄取流程不再作为后续实施项。
