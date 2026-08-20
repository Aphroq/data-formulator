# Analysis Integrations 实施方案

## 1. 文档状态

| 项目 | 内容 |
| --- | --- |
| 适用分支 | `feat/analysis-integrations` |
| 固定上游基线 | Data Formulator `0.8.0b1` / `5477f0e236426dc8f74a498ec400414fba7fbc0f` |
| 当前目标 | 在同一个 `AnalystAgent` 与 Data Formulator 工作区中增加一个 TrustGraph 原生 Agent 驱动的业务上下文查询能力和可选 GitHub Copilot 模型 |
| 当前实施节点 | A12 产品代码、离线合同和真实原生 Agent 验收完成：六个底层 TrustGraph 工具已收敛为一个高层查询，复用原生 Agent 的多轮检索和 provenance |
| 外部验证节点 | reader bearer、合成知识、专用只读工具组、目标 collection、Qwen Flow 和 non-thinking 部署均已生效；ontology 定义/关系已作为可查询知识导入知识图，真实 Data Formulator 查询覆盖一轮、自动两轮和中文输入并持久化官方 session trace |
| 最后更新 | 2026-08-20 |

本文把项目级架构约束细化为 Analysis Integrations 分支可执行的代码、测试和验收计划。项目事实来源仍以当前检出源码和测试为准；实现决定变化后，应同时更新本文和同目录工程记录。

## 2. 目标与非目标

### 2.1 交付目标

1. 建立供应商无关的业务上下文结果、稳定错误和结构化引用契约。
2. 将 Data Formulator 后端已经授权的 identity 和 workspace 明确传入 Skill，不从模型参数或前端 payload 推断。
3. 通过一个 `query_business_context(question, context?)` 把业务语义缺口交给 TrustGraph 原生 Agent；用户和外层模型不需要掌握图谱查询术语。
4. TrustGraph Agent 使用服务器绑定的只读工具组和 collection，自行按需多轮调用知识与结构化查询能力。
5. 查询只发送聚焦问题与最小相关上下文；只消费最终答案和真实 provenance trace，不消费隐藏思考链，也不从任意 URI 猜来源。
6. 将引用从 Skill 结果送入 Agent 流，并持久化到 Data Thread 的对应消息或产物。
7. 在现有 LiteLLM Client 路径中接入 GitHub Copilot device flow，不引入 Copilot SDK 或第二套 Agent runtime。
8. 对 Copilot 模型逐个探测 chat、streaming 和 tools 能力，只注册符合当前 `AnalystAgent` Chat Completions 契约的模型。
9. 复用官方 `trustgraph-ui` 承担管理和完整图谱可视化，不在 Data Formulator 复制工作台。
10. 保证 `TRUSTGRAPH_ENABLED=false` 和 `GITHUB_COPILOT_ENABLED=false` 时没有残留 Skill、API、模型或 UI 行为。

### 2.2 明确不做

- 不实现 Recipe、Schedule、Run、Worker 或后台 Executor。
- 不把 `row_embeddings_query()` 或其他 TrustGraph 底层查询直接暴露给 Data Formulator 外层模型。
- 不在 Data Formulator 暴露文档摄取、processing、Knowledge/Context Core load/unload/bulk 或其他 TrustGraph 写操作。
- 不复制、vendoring 或重写 TrustGraph 官方工作台组件；需要管理和完整可视化时使用独立官方 `trustgraph-ui`。
- 不在正常 Recipe Run 中调用 LLM、TrustGraph 或 Workflow Replay。
- 不把 GitHub access token、Copilot 短期 token 或 TrustGraph bearer token写入前端状态、日志、Recipe、普通配置文件或测试夹具。
- 产品实现和默认开发/回归不使用 Docker、Docker Compose、LiteLLM Proxy、Copilot SDK 或额外消息基础设施；用户明确授权的仓库外 WSL2 验收环境不进入产品依赖。
- 第一版不注册 LiteLLM 标记为 Responses-only 的 Copilot 模型。

### 2.3 功能优先调整（2026-08-19）

后续实施以用户能直接使用的知识能力为里程碑，不再为凭据隔离、输出大小限制或引用清洗单独开新切片。A0-A7 已形成的相关基础设施保持现状并作为回归边界；A8/A9/A11 的六个底层接口与真实数据验证保留为历史技术证据，不再定义产品工具面。2026-08-20 的 A12 决定以本节、项目系统设计和 A12 切片为当前事实；后文 A0-A11 中描述的六工具结构只用于解释历史实现与验证，不再约束最终实现。

TrustGraph 内部接入继续复用官方 Python SDK，但改为调用原生 `service/agent`。官方 MCP server 适合给外部 MCP 客户端提供兼容能力；本项目不增加 MCP transport、会话和工具参数转换层，也不在 Data Formulator 重写 TrustGraph 的 Agent loop。

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
  │                  TrustGraph 原生 Agent
  │                                    │
  │        只读工具组 → knowledge/structured query
  │                                    │
  │               最终答案 + provenance trace
  │                                    │
  └──────────────────────────── Agent event router
                                       │
                              Data Thread 持久化引用
```

信任边界规则：

1. identity 和 Data Formulator workspace id 只能来自后端认证/授权路径。
2. 模型只能提交聚焦 `question` 和可选最小 `context`；不得提交 base URL、flow、collection、Agent 工具组、TrustGraph workspace、credential id 或 token。
3. 服务端配置把 Data Formulator workspace 映射到固定目标；没有映射时失败关闭。
4. 外部返回的最终答案、title 和 URI 都是不可信数据，先规范化、限长、去重和清洗，再进入模型或前端；隐藏思考链不消费。
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

@dataclass(frozen=True)
class BusinessContextResult:
    text: str
    context_items: tuple[ContextItem, ...] = ()
    truncated: bool = False

@dataclass(frozen=True)
class BusinessContextQuery:
    text: str
    identity_id: str
    workspace_id: str
    context: str = ""

class BusinessContextProvider(Protocol):
    def query(self, request: BusinessContextQuery) -> BusinessContextResult: ...
```

约束：

- provider 每次查询重新核对 identity/workspace scope；授权上下文只用于服务端解析目标和凭据，不原样发给 TrustGraph。
- `text` 是一个可独立回答的聚焦业务问题；`context` 是可选的简短数据说明，只允许包含当前任务/决策、相关数据源或表在任务中的角色、字段名和类型、少量非敏感代表值或脱敏值模式以及用户明确约束。
- 工具 schema 不提供查询语言、URL、Flow、collection、workspace、tool group、credential 或 token 字段。
- provider 构造一个短的固定查询帧，把 `context` 明确标记为不可信本地数据；TrustGraph 原生 Agent 负责内部检索和多轮工具使用。
- `BusinessContextResult.text` 始终是可解析、有大小上限的 JSON，只包含最终答案和 provenance 元数据；不包含 AgentThought 或隐藏思考链。
- `ContextItem.uri` 必填，`title` 可空，`provider` 由后端赋值而不是相信外部字段。
- 当前 `2.8.14` Agent REST 响应不返回原始文档 source，因此只把请求的官方 Agent provenance URI 标成“retrieval trace”；不得递归扫描答案或 RDF payload 中的 URI。未来只有官方明确返回的文档 source 才可增加 citation。
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
    "agent_group": "data-formulator-readonly",
    "trustgraph_workspace": "finance",
    "credential_ref": "trustgraph:finance-prod",
    "connect_timeout_seconds": 3,
    "read_timeout_seconds": 120,
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
- `agent_group` 是服务端配置的单个只读工具组；Data Formulator 请求时将它作为唯一 group 发送。该组应绑定目标 collection，只包含允许的知识/结构化读取工具。
- `credential_ref` 必须使用独立的 `trustgraph:` namespace 并通过现有 identity-scoped vault 解析；目标 JSON 不能内嵌 bearer token。

### 5.5 TrustGraph 请求与响应

使用官方 `trustgraph-base==2.8.14` 同步 API，并注入可测试的 `requests.Session`。一个很小的 `Api` 子类只补官方版本未开放的请求安全控制：精确路径白名单、禁止 redirect、connect/read 分离 timeout 和 session 注入；它不是自定义传输协议、搜索器或网络代理。

唯一外部请求是原生 Agent service：

```text
POST {api_base}/api/v1/flow/{flow}/service/agent
Authorization: Bearer <resolved token>
```

请求体只包含服务器控制值和经过裁剪的查询：

```json
{
  "question": "<固定短帧：聚焦问题 + 可选最小上下文>",
  "history": [],
  "group": ["<server-bound read-only group>"],
  "collection": "<server-bound collection>",
  "session_id": "<server-generated UUID>",
  "streaming": false
}
```

`FlowInstance.agent()` 是原生能力，但该版本 REST 高层签名没有开放 `collection` 和 `session_id`；适配器使用同一官方 `FlowInstance.request("service/agent", ...)` 补齐，不实现任何查询规划。锁定版本存在官方客户端/网关形状差异：同步 SDK 描述聚合 `{answer}`，`2.8.14` HTTP gateway 实际返回终态 `{message_type, content, end_of_message, end_of_dialog, ...}`。适配器只接受非空聚合 answer，或 `message_type` 为 `answer`/`final-answer` 且两个完成标志都严格为 `true` 的非空 content；thought、observation、partial answer 和其他漂移全部失败关闭。输出被包装为有大小上限的 JSON，其中只把官方 `agent_session_uri(session_id)` 作为检索轨迹，不虚构图标识；过长答案在 JSON 边界内截断。

### 5.6 稳定错误分类

外部异常不得把原始 URL、response body、headers 或 exception 文本传给模型/前端。第一版类别：

| 类别 | 触发 | 面向 Agent 的稳定语义 | 可重试 |
| --- | --- | --- | --- |
| `disabled` | flag 关闭 | 该能力未启用 | 否 |
| `not_configured` | workspace 无目标/凭据 | 该 workspace 未配置业务上下文 | 否 |
| `invalid_request` | 非对象参数、空/超限问题或上下文、未知字段、非法 session id | 查询不符合合同 | 否 |
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

## 7. 合同与功能测试矩阵

| 层 | 必测场景 |
| --- | --- |
| 值对象 | 空/超限 question、可选 context、空 identity/workspace、非法 source URI、timeout/response/context-item budget |
| 配置 | flag 未设置/false；关闭态不读 vault；workspace 无目标；旧六工具字段拒绝；HTTPS/userinfo/query/fragment/origin；reader credential 缺失 |
| 提示与 Skill | 仅一个高层工具；未决含义会改变结果才查询；明确规则/机械操作跳过；定义/编码/分类/状态/范围/单位/规则/关系指向 `knowledge_query`，结构化事实才用 `structured_query`；不得发明 search/browse；不做行级语义匹配；最小上下文字段齐全；不发送整表/原始敏感值/完整聊天/代码/路径/凭据/路由 |
| 请求 | 官方 `service/agent` 精确路径；bearer；服务端 workspace/Flow/collection/group；session id；空 history；`streaming=false`；模型参数不能覆盖目标 |
| 响应与引用 | 非空聚合 answer，或两个完成标志均为 `true` 的官方终态 answer/content；拒绝 thought、observation 和 partial answer；仅接收官方显式 `sources`；答案中的任意 URI 不生成 citation；session trace 明确标成非文档来源；其他类型漂移失败关闭 |
| 大小 | question/context、wire prompt、答案 JSON、source title/URI、引用数量和截断后 JSON 边界；UTF-8/中文不破坏 |
| 错误 | connect/read timeout；401/403；429；5xx；连接失败；无效 JSON；SDK/REST 合同漂移 |
| 清洗 | token、URL query、response body、外部异常文本不出现在稳定错误、流或日志字段中 |
| 兼容 | 不导入 TrustGraph Skill 时现有 registry 不变；现有 `ToolResult(text, images)` 构造保持兼容 |
| 真实场景 | 清洗/映射/分组前的业务含义缺口；明确用户规则跳过；证据不足/服务不可用不编造；同一语义缺口不机械重复外层调用 |
| 范围边界 | Skill 不出现目录/RDF/SPARQL/GraphQL/row-embeddings/摄取/管理工具；不触碰 Workspace；Data Formulator 不新增自制 TrustGraph 工作台 |

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

- TrustGraph 真实 base URL、允许的 Flow/collection/workspace/只读工具组和测试 bearer token。
- 生产 origin allowlist、credential vault 生命周期和管理员配置方式的最终确认。

GitHub Copilot 测试 identity 条件和仓库外 TrustGraph 的历史结构化接口冒烟均已完成。A12 的原生 Agent target、reader bearer、合成 collection、只读工具组、Qwen 配置、部署重载以及一轮/自动两轮/中文成功场景均已完成。生产业务知识、collection、workspace、工具组和 bearer 仍是部署条件，尤其必须把需要查询的 ontology 定义、关系及来源实际导入目标知识图；这些值不硬编码到本分支。若后续官方 SDK、REST 文档与真实服务再次不一致，先记录精确差异并更新合同测试，不增加无边界兼容猜测。

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

当前执行：分支最终回归、diff 检查和工程记录收口。

`acdfb3c5` 保留 A0-A11 的技术基础和历史验证。A12 产品代码和真实原生 Agent 验收已经完成；六工具历史结果只作为底层技术证据。
