# 系统设计

## 设计目标

在不改变 Data Formulator 核心交互模型的前提下，增加可信上下文、确定性 Recipe 和轻量后台运行。

系统只保留一个产品编排者 `AnalystAgent`。TrustGraph 原生 Agent 通过一个只读业务上下文 Skill 接入，并只充当外部检索提供者；知识摄取、工具组、Context Core 管理和完整图谱工作台继续使用 TrustGraph 官方 UI，不在 Data Formulator 建立第二套管理面。GitHub Copilot 是 LiteLLM provider。这些分析集成不进入正常 Recipe Run。

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
  ├─ TrustGraph Skill（一个高层业务上下文查询）
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

### TrustGraph 业务上下文检索

Data Formulator 只保留一个产品编排者：现有 `AnalystAgent`。TrustGraph 原生 Agent 作为外部、只读的业务上下文检索提供者，不拥有 Data Thread、Workspace、本地 Python 执行、图表或任何提交动作，因此不构成第二套 Data Formulator Agent runtime。

主调用链固定为：

```text
用户的分析 / 清洗 / 转换请求
  → AnalystAgent 判断是否存在会改变结果的未决业务含义
  → query_business_context(question, context?)
  → 服务端解析知识 Profile（TrustGraph workspace + Flow + 只读 Agent group + trace collection）
  → 服务端通过 agent_explain 接收实时 provenance 和最终答案
  → TrustGraph 原生 Agent 按工具描述选择一项或多项 collection-bound 只读查询
  → provenance 被压缩成安全的查询轮次/阶段并进入现有 NDJSON 流
  → 最终业务上下文答案 + 查询轮数 + 真实检索轨迹标识
  → AnalystAgent 结合本地数据继续执行或请求澄清
```

Data Formulator 发给外部提供者的载荷保持简单：

- `question`：一个可独立回答的聚焦业务问题，例如某个状态、分类、口径、映射、单位、时间边界或关系应如何解释；
- `context`（可选）：只包含该答案会影响的当前操作、相关数据源或表在任务中的角色、字段名和类型、少量非敏感代表值或脱敏后的值模式，以及用户已经明确的约束。

不发送整表、无关行、原始敏感值、完整聊天历史、代码、文件路径、identity、Data Formulator workspace id、目标 URL、Flow、collection、工具组或凭据。外层模型不负责选择 TrustGraph 内部查询策略，也不生成 SPARQL/GraphQL；一次高层调用通常应由 TrustGraph Agent 自行完成必要的工具选择和多轮检索。只有出现另一个独立的语义缺口，或返回明确指出缺少某项上下文时，外层才再次调用。

#### Collection 与知识 Profile

锁定版本只有四个需要进入本项目设计的事实：workspace 是授权隔离边界；collection 是 workspace 内的扁平知识分区；每个 RAG/structured 工具绑定一个 collection；`agent_explain(..., collection=...)` 中的 collection 只用于 Agent session provenance trace。TrustGraph Agent 能在 group 内多轮调用工具，但不会因拿到 workspace 就自动枚举全部 collection。

职责只保留现有五层，不新增路由服务：

| 层 | 只负责什么 |
| --- | --- |
| `AnalystAgent` | 判断是否存在会改变分析结果的业务含义缺口，并提交一个聚焦问题 |
| TrustGraph target（文档中称知识 Profile） | 绑定 API、workspace、Flow、一个只读 group、trace collection 和凭据引用；管理员默认来自服务器配置，identity/workspace 精确覆盖是一个非 secret JSON 配置，不是 collection 清单或知识管理实体 |
| Agent group | 通过 TrustGraph 工具的 group 标签筛出本轮 Agent 可见的查询工具；它是产品路由清单，不是新的 IAM 边界 |
| 查询工具 | 用名称和描述说明知识范围，并静态绑定自己的 retrieval collection |
| TrustGraph Agent | 根据当前问题选择一个或多个工具、按需多轮调用并汇总答案 |

授权和路由不能混在一起：bearer 绑定的 TrustGraph workspace 决定调用者能进入哪个隔离空间；group 只限制 Data Formulator 这条 Agent 路径向模型展示哪些工具。Data Formulator 不用 group 代替 TrustGraph 授权，也不因为 bearer 能看见 workspace 就把所有 collection 自动加入 group。

```text
控制面：来源 → Knowledge Core → 按治理域发布 collection → 配置只读工具 → 加入 group

查询面：用户请求 → query_business_context → Profile/group
                                      → TrustGraph Agent
                                      → 工具 A / 工具 B（按当前问题选择）
                                      → 答案 + trace
```

先选 workspace，再划 collection：授权或所有权不同的知识进入不同 TrustGraph workspace/Profile，当前一次 `query_business_context` 不做跨 workspace 联邦查询。同一 workspace 内，只有发布生命周期不同，或者知识不应共享图关系与检索排名时才拆 collection；同一治理域的多个来源可以通过 Knowledge Core 装入同一 collection。不能按某个测试问题临时组合，也不因来源文件不同就机械拆分。Knowledge Core 只解决同一域内的来源复用和版本发布，不承担跨域路由。

| 判断 | 放入同一 collection | 保持不同 collection |
| --- | --- | --- |
| 是否属于同一授权和所有权空间 | 继续在同一 workspace 判断 | 否：拆 workspace/Profile，不靠 collection 隔离 |
| 是否需要一起发布和回滚 | 是 | 否 |
| 是否需要在同一图中维护直接关系并统一检索排名 | 是 | 否 |
| 仅仅因为来源文件不同 | 不是拆分理由 | — |
| 仅仅因为某个问题可能同时提到两类知识 | — | 不合并；查询时由 Agent 调两个工具 |

每个知识域使用稳定的工具名、范围描述和 group 标签，collection id 可以带版本。发布时先构建并直接验证新 collection，再把该稳定工具的 `collection` 绑定切到新版本，并按当前 TrustGraph 部署的正常方式使配置生效；回滚则切回旧版本。不要把新旧版本同时作为两个领域工具交给 Agent 选择，版本选择属于控制面而不是问题路由。

Data Formulator 既不保存 retrieval collection 数组，也不枚举 workspace、fan-out 或合并跨 collection 排名。它只发送一个服务器绑定的 group；问题到来后由 TrustGraph Agent 读取组内工具描述完成路由。查询期间不创建 collection、不调用 `load_kg_core`、不修改 group。若将来出现大量动态 collection，锁定版本缺少原生 catalog/router，应作为 TrustGraph 能力缺口单独处理；A16 不为尚未出现的规模增加组件。

知识 Profile 按“当前 identity/workspace 精确覆盖 → `TRUSTGRAPH_TARGETS_JSON` 精确项或 `default` 管理员后备”解析；一个 Profile 只进入一个 TrustGraph workspace。精确覆盖只保存 API、workspace、Flow 和知识工具范围，reader token 以派生的 `trustgraph:workspace:*` 引用进入现有 vault；固定 trace collection 不进入 UI。工具配置和 retrieval collection 版本仍由 TrustGraph UI/CLI 管理，Profile 不复制这些清单。单知识域可以只有一个稳定领域知识工具；同一 workspace 内的多知识域配置少量、描述清楚的工具。工具描述只说明知识内容、权威范围和明确排除项，不枚举预期问题或写行业特例。现有 `structured_query` 保留；group 不加入 row embeddings、通用文本补全、写操作、摄取或管理工具。

固定任务帧不写死任何内部工具名，只要求原生 Agent 使用本轮实际提供的只读知识工具、选择最小充分集合、必要时补查，并在证据不足时停止。跨语言首轮缺证时仍可保持业务含义补查一次。进度也不根据 `knowledge_query`/`structured_query` 名称分支，而只把可信 provenance 阶段归一化成通用“第 N 次业务知识检索”。

A16 已完成三个语义收敛：`TrustGraphTarget` 和目标 JSON 只接受必填 `trace_collection`，旧 `collection` 字段直接触发配置错误；任务帧依据本轮实际可见的只读知识工具及描述选择最小充分集合；实时进度按官方 provenance 类型和阶段计数，不维护 action 名单。真实单域、跨域和稳定工具 collection 版本切换均已验证。除此之外不增加 collection 配置层、catalog、查询协调器、前端选择器或新的 Agent runtime。

每次创建 `AnalystAgent` 时，用同一个 target resolver 对知识 Profile 做一次不访问网络的就绪判断：当前 identity/workspace 能解析到用户精确覆盖或管理员后备，且 vault 中存在对应 reader 凭据时，registry 才向模型提供 TrustGraph Skill；否则不宣称该能力可用。`GET /api/agent/business-context-status` 复用同一判断给当前 Workspace 菜单显示配置状态，不调用 TrustGraph 网络。用户显式打开连接弹窗时可读取非 secret 字段；显式点击测试才通过官方 `Api.flow().list()` 验证连接并列出 Flow，20 秒超时，不运行 Agent 查询。Provider 在真正查询时仍重复解析并失败关闭，避免把 registry 或 UI 状态当成授权/健康检查。全局 flag 继续决定模块是否导入；这里不增加后台探测或缓存服务。

TrustGraph 的 ontology 配置是给摄取流程使用的规则，用来约束可抽取的类型、属性和关系；知识查询搜索的则是其工具所绑定 collection 中已经导入的知识。需要在分析和清洗中自动核对的类定义、属性、domain/range 和业务关系，应由部署方连同来源实际装载到相应的可查询 collection，并建立图实体上下文；随后由该 Profile 的只读知识工具检索。Data Formulator 不直读 ontology 配置，也不为此增加 SPARQL 或 triples 产品工具。

公开 IOF 制造业验收进一步固定了部署侧的最小装载合同：原始知识 triples 进入 GraphRAG 实际查询的默认知识图；文件、版本、哈希和 RDF-star 派生关系进入 `urn:graph:source`；原始 RDF 保存在 Library；实体上下文只使用上游 label、定义、示例、父类和关系，不由装载器编造业务定义。完整来源清单见 [TrustGraph 制造业知识准备与验收](../04-features/analysis-integrations/trustgraph-manufacturing-knowledge.md)。这仍是 TrustGraph 部署职责，不增加 Data Formulator 写路径。

产品内部继续使用锁定的官方 Python SDK，业务查询只走 `Api.socket().flow(...).agent_explain(...)` 这一条原生流式路径；Flow、trace collection、只读 group、TrustGraph workspace、credential 和 session id 均由解析后的 Profile 绑定，retrieval collection 由 group 中各查询工具绑定。浏览器不直连 TrustGraph，连接 API 只返回非 secret 路由字段和 `has_credential`，永不返回 bearer。同步 `query()` 只作为消费同一 explain iterator 的入口，不保留一套并行 REST fallback，不实现自己的搜索、查询规划或 Agent loop。MCP 只作为独立外部互操作入口；锁定镜像的出站 `mcp-tool` 与其 MCP 客户端签名不兼容，内部 Agent 不依赖该路径。

TrustGraph 返回内容按不可信证据处理。Data Formulator 消费最终答案和结构化 provenance 事件类型，但不回传或展示 `AgentThought`、`AgentObservation` 正文、工具参数、原始 triples 或 token 级答案分片。每次请求由 Data Formulator 生成 session id，并用官方 Agent provenance URI 形成真实轨迹引用；只有 TrustGraph 官方响应明确给出的文档来源才作为文档 citation，禁止递归收集任意 RDF/RDFS/实体 IRI 冒充来源。供应商无关的 `ContextItem.kind` 区分 `source` 与 `trace`，旧数据缺省为 `source`；前端的 Sources 只列文档来源，trace 以独立的紧凑检索轨迹展示，并在标题中保留实际查询轮数和终态。若无答案、认证失败、超时、服务错误或协议漂移，查询失败关闭；若答案本身说明证据不足，`AnalystAgent` 不得据此执行会改变语义的数据操作。

锁定的 `trustgraph-base==2.8.14` 中，直接 GraphRAG 能返回文档来源，但高层 `AgentAnswer` 不包含内部 GraphRAG source 列表，explain 事件也不提供可替代的来源合同。产品因此只展示 session trace，不二次调用底层 GraphRAG、不从答案 URL 反推 citation；后续只有官方 Agent 合同明确透传来源时才扩展。

调用期间先显示“正在核对业务知识…”，收到 explain provenance 后原位更新成“第 N 次业务知识检索”的有限阶段，最后显示“正在形成业务知识结论”。这些步骤来自真实事件但不是 ReAct 思考链。`ToolResult.public_summary` 继续用于公开工具事件和日志；另增加有界、仅供模型 trajectory 续接的 `resume_text`，只保存最终答案、官方明确返回的文档来源和请求生成的 provenance trace 标识，不含 hidden thought、原始响应或凭据。暂停恢复不新增服务端状态库，也不依赖重新查询才能记住刚取得的业务知识。

#### 实时查询步骤

Skill inspection tool 允许返回同步 `ToolResult`，也允许用生成器先产生少量 `tool_progress` 再返回同一个 `ToolResult`。现有同步 Skill 不变；Agent shell 只转发结构化进度字段，Route 仍按既有 `/analyst-streaming` NDJSON 序列化，不增加浏览器 WebSocket 或新端点。

```json
{
  "type": "tool_progress",
  "tool": "query_business_context",
  "query_index": 2,
  "phase": "filtering"
}
```

`phase` 只保留 `searching`、`filtering`、`summarizing`、`completed` 和 `finalizing`。后端按以下方式压缩锁定版本的 explain 事件：

| TrustGraph explain 事件 | 产品进度 |
| --- | --- |
| 官方 `Analysis` 类型（包括被锁定 SDK 解析为其他实体的混合类型事件），或首个 `grounding` | 开始第 N 次查询，统一称“业务知识检索” |
| `grounding` / `exploration` | `searching` |
| `focus` | `filtering` |
| `synthesis` | `summarizing` |
| `observation` provenance | 当前查询 `completed`；不读取 observation 正文 |
| `Conclusion` | `finalizing` |
| `AgentThought`、`AgentObservation` 内容、answer token | 不生成进度；answer token 只在服务端聚合最终答案 |

前端复用现有 `thinkingSteps`：同一 `query_index` 只更新一行，下一轮才新增一行。成功的最终 trace 只增加 `query_count` 和完成摘要；失败由现有 `tool_result` 收口，不额外制造 trace。不存整份事件流，不渲染图谱。这样既能看见 TrustGraph 自动补查，又不会复制 TrustKit 的完整 Timeline、状态层或 Agent 控制台。

锁定 SDK 对同时声明 `Analysis`、`ToolUse`、`Reflection` 和 `Thought` 的真实工具调用事件会优先构造 `Reflection`。适配器只对该事件自身的官方 `rdf:type = tg:Analysis` 做精确补充判断，使查询开始能在 `grounding` 前实时出现；不读取 `tg:action`、隐藏 thought、参数或任意 URI，普通 `PatternDecision` 不会被计为查询。

TrustGraph 自身 LLM 配置与 Data Formulator LiteLLM 配置相互独立。当前部署使用 OpenAI-compatible Qwen variant，把模型设为 `Qwen/Qwen3.5-27B`，`thinking=off`；API token 和 base URL只存在 TrustGraph 部署环境。官方 `trustgraph-ui` 继续承担工具组、collection、摄取、Context Core、Ontology/SPARQL/GraphQL 和完整图谱管理，Data Formulator 不复制这些页面。

### 通用引用通道

不在 AnalystAgent 中硬编码 TrustGraph：

- `SkillContext` 增加明确的 identity/workspace 信息。
- `ContextItem` 增加可选 `kind: source | trace`，旧数据默认按 `source` 处理。
- `ToolResult` 增加结构化 `context_items` 和可选有界 `resume_text`；`public_summary` 与续接证据保持不同用途。
- Skill inspection tool 可以选择流式产生经过 Agent shell 路由的 `tool_progress`，最终仍返回一个 `ToolResult`；不为 TrustGraph 建第二套事件总线。
- Agent 把清洗后的引用作为 `context_info` 事件发送。
- 前端把引用持久化到对应 Data Thread 消息或产物，而不是只显示在瞬时 thinking step。

### GitHub Copilot

继续使用现有 LiteLLM Client：

- `auth_mode` 增加 `oauth_device`。
- 模型注册表允许没有 API key 的 OAuth endpoint。
- Client 正确解析 provider/model 前缀。
- 可用性检查从文本 ping 升级为能力探测，至少记录 chat、streaming 和 tools。
- 模型对话框优先复用当前 identity/model 已有的三项 capability 结果；只有连接状态改变、缓存缺失或用户显式复测时才重新访问网络。
- 顶部操作区在 feature flag 开启时显示当前 identity 的 Copilot 连接状态，并打开独立管理弹窗；弹窗复用模型对话框中的同一个 device-flow 面板，不建立第二套认证状态或凭据逻辑。连接图标和 TrustGraph 图标进入正常 flex 操作区，不与绝对居中的 Workspace 标题叠放。
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

实时查询步骤也不直接嵌入 `@trustgraph/trustkit`。TrustKit 的 `ExplainTimeline` 只作为交互和事件分类参考；Data Formulator 用现有 React 18、MUI 和运行步骤区域实现紧凑状态，避免引入 React 19、TrustGraph React state/provider、TanStack Query/Zustand 和另一套 Agent session。

`@trustgraph/portal` 是完整 Workbench 应用而非组件边界：它拥有认证、SocketProvider、workspace、BrowserRouter、QueryClient、主题和插件运行时，当前也没有接收既有 explain/session 标识的深链合同。因此不把 Portal 作为依赖、iframe 或 Data Formulator 内嵌页面。它的 Python UI service 对 `/api/v1/socket` 做同源 WebSocket 转发，只作为现有 TrustGraph 入口必须支持 WSS Upgrade 的实现证据；Data Formulator 仍由服务端 Python SDK 调用 TrustGraph。

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
- TrustGraph `api_base` 的 WSS Upgrade 使用同一目标和 bearer；浏览器不获得 TrustGraph 连接信息，`AgentThought`、observation 正文、工具参数和原始 provenance triples 不进入 NDJSON。
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
