# Analysis Integrations 工程记录

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 分支 | `feat/analysis-integrations` |
| Worktree | `D:\projects\dfm-wt-analysis` |
| 本机实例 | `analysis`：后端 5568、Vite 5174、数据目录 `D:\projects\dfm-runtime\analysis` |
| 基线 | 共享文档提交，父提交为 Data Formulator `5477f0e` |
| 当前阶段 | A13 主路径、A14 `agent_explain` 实时查询步骤、A15 IOF 制造业知识验收和 A16 Collection/Profile 收敛均已完成。`structured_query` 继续保留，不接入行级语义匹配 |

## 目标

在现有 `AnalystAgent` 和 Data Formulator 数据工作区中增加一个通用的 TrustGraph 业务上下文查询能力和可选 Copilot 模型，不创建第二个 Data Formulator Agent runtime。

## 范围

- 通用结果、结构化引用和稳定错误契约。
- 一个 `query_business_context(question, context?)` 工具；`context` 只携带当前决策、相关数据源/表角色、字段/类型、少量非敏感代表值或脱敏值模式和用户明确约束。
- TrustGraph 原生 Agent 通过服务器知识 Profile 绑定的 Flow 和只读工具组自行执行一轮或多轮 collection-bound 查询；group 列出该 workspace 内本轮可见的长期知识域，Agent 在当前问题到来后选择一个或多个工具，不为未知问题预先组合跨域总集合。现有组继续保留 `structured_query`，Data Formulator 不把它设为第一版依赖，后续用受治理结构化记录场景单独验收；六个底层查询不再暴露给外层模型。
- TrustGraph 最终答案、官方明确返回的文档来源和独立检索轨迹；通过 `agent_explain` 把真实多轮 provenance 压缩成有限的实时查询步骤，不解析或展示隐藏思考链、observation 正文、工具参数、原始 triples，也不递归收集任意 URI 冒充文档来源。
- TrustGraph 管理和完整可视化复用官方 `trustgraph-ui` Portal；Portal 是自行持有认证、WebSocket、workspace、路由和主题的完整应用，并非可嵌入组件，当前也没有按既有 explain/session 标识打开的稳定深链。TrustKit 只作为 ExplainTimeline 交互参考，不作为项目依赖。Data Formulator 不使用 Portal iframe，也不实现行语义搜索、文档摄取或 Context Core 写操作。
- `SkillContext` identity/workspace 与 `ToolResult` citation 契约。
- Citation 在 Data Thread 中的持久化展示。
- LiteLLM Copilot `oauth_device`、provider 解析和能力探测。
- `TRUSTGRAPH_ENABLED`、`GITHUB_COPILOT_ENABLED`。

不包含 Recipe、Schedule、Run 或 Worker。

详细契约、切片、测试矩阵与停止线见 [Analysis Integrations 实施方案](implementation-plan.md)；固定 IOF 来源、装载合同和真实结果见 [TrustGraph 制造业知识准备与验收](trustgraph-manufacturing-knowledge.md)。

## 实施顺序

按可独立验证、可回滚的小型纵向切片实施：

1. **M0-A 离线合同探针（已完成）**：固定 `trustgraph-base==2.8.14` 和 LiteLLM `1.91.3`；TrustGraph 复用官方 API/RDF translator，并用 HTTPS 会话替身锁定本体、三元组、SPARQL、认证和错误分类。
2. **M0-B 真实环境探针（已完成）**：真实 GitHub Copilot 账号已验证 device flow、chat、streaming、tools 和短期 token 刷新；TrustGraph 已在仓库外专用 WSL2 环境验证 bearer、`default` Flow、本体、knowledge/provenance triples、SPARQL `ASK`/`SELECT` 和完整 Skill 路径，不依赖 Graph RAG 或 SiliconFlow 模型。
3. **通用引用契约（已完成）**：先为 `SkillContext` identity/workspace、`ToolResult.context_items`、流事件清洗和大小限制增加失败测试，再修改通用类型和 Agent 路由。
4. **TrustGraph 纵向切片（已完成）**：增加官方 SDK 客户端、三个结构化只读 Skill 工具、显式 workspace 目标映射、SSRF/超时/错误清洗和默认关闭的后端路径。
5. **引用持久化切片（已完成）**：前端累计本轮结构化引用，持久化到对应 `InteractionEntry` 和结束 `TextTurn`，再用独立 Sources 组件展示；不只写入瞬时 thinking step。
6. **Copilot 认证切片（已完成）**：增加应用拥有的 device-flow endpoint、identity 隔离的凭据生命周期、默认关闭路由和显式连接 UI；普通模型请求在请求局部适配完成前失败关闭。
7. **Copilot 模型切片（已完成）**：A5 增加带 LiteLLM 版本/源码指纹保护的请求局部适配和逐模型 capability probe；只有通过 chat、streaming、tools 的模型才可供 `AnalystAgent` 选择和调用。
8. **集成与回归（离线门禁和真实探针已完成）**：两个默认关闭的 feature flag、关闭态、后端、前端和生产构建门禁均已验证；这些普通回归与 Copilot/TrustGraph M0-B 真实探针分开记证据，二者均已完成。
9. **A8 知识发现（已完成）**：复用官方 Python SDK 增加知识目录和图实体语义检索；不引入 MCP 客户端或自制向量算法。
10. **A9 只读结构化查询（已完成）**：接入官方 `rows_query()`，把 GraphQL `data/errors/extensions` 作为结构化证据返回；不创建表、不写 Workspace、不做同步。
11. **A10 知识准备（已取消）**：不在 Data Formulator 增加文档上传、processing 或 Context Core 装卸入口。
12. **A11 真实业务验收与 MCP 兼容（历史验证完成）**：六个底层接口和外层 Qwen 手工编排已证明传输与数据可用，但暴露方式不作为最终产品架构。MCP 仍仅作可选外部兼容。
13. **A12 原生 Agent 收敛（已完成）**：改为一个高层业务上下文查询；复用 provider-neutral `BusinessContextQuery`，由 TrustGraph 原生 Agent 完成多轮检索，并以真实 provenance trace 取代任意 URI 来源提取。真实 Qwen/GraphRAG/librarian/Data Formulator reader 链路已成功验收。
14. **A13 最小产品化收口（主路径与真实验收已完成）**：未增加新系统；已完成默认目标、当前 Workspace 配置状态与请求时就绪判断、tool-only Skill 发现和完整用户输入回归、单一进度提示、source/trace 与续接证据，以及 Copilot capability 缓存复用。当前 Qwen/TrustGraph 已重跑自动查询、跳过和运行期失败路径；生产候选知识验收继续作为部署前独立条件。
15. **A14 `agent_explain` 实时步骤（已完成）**：服务端使用官方 WebSocket explain iterator，把 provenance 映射为 `tool_progress`；浏览器继续消费现有 `/analyst-streaming` NDJSON，前端复用 `thinkingSteps`，成功 trace 只增加查询轮数摘要。当前 HTTPS 验证入口已支持 `/api/v1/socket` Upgrade；未新增 `socket_base`、TrustKit 依赖、浏览器直连或第二套 Agent runtime。
16. **A15 IOF 制造业知识验收（已完成）**：固定 IOF `Release_202602` 的 Annotation Vocabulary、Core 和 Production Planning，保留文件哈希、原始 RDF 和来源关系；真实中文数据清洗输入自动加载 Skill，同一个 TrustGraph Agent 两轮检索后区分生产订单、生产计划和制造操作。公共本体不冒充企业生产知识。
17. **A16 Collection/Profile 收敛（已完成）**：workspace/bearer 负责授权和所有权隔离，当前调用不跨 workspace；group 只筛选其中的 Agent 可见工具。collection 按生命周期和知识连通性形成长期知识域，由 Agent 在查询时选择领域工具。Knowledge Core 仅在同一域内组合来源。领域工具保持稳定，发布时切换其绑定的 collection 版本。Profile 仍是现有 target 配置；代码已硬切 `trace_collection`、按实际工具描述形成通用任务帧，并从官方 provenance 类型生成与 action 名无关的实时步骤。真实单域、双域和版本切换/回滚均已通过。

## 开发记录

收口说明：M0-A 至 A11 的“待提交”节点是在同一增量工作区内逐步形成的历史状态；实现与测试已统一落入 `acdfb3c5`，配套事实来源文档由本次工程记录提交承载，最终状态以表格末行和“合并前检查”为准。

| 日期 | 阶段 | 实质变更 | 验证 | 提交 |
| --- | --- | --- | --- | --- |
| 2026-08-18 | 准备 | 核对真实 Skill、模型注册表和 LiteLLM 扩展点，建立共享文档与独立 Worktree | 固定源码审查、文档检查 | `docs: establish project plan` |
| 2026-08-18 | 准备 | 增加仓库级 Agent 指南并配置 fork remote | 文档链接、范围和 Git remote 核对 | `docs: add repository agent guide` |
| 2026-08-18 | 准备 | Agent 指南中文化，工程记录迁入 Feature 独立目录 | 文档链接、目录和旧路径检查 | `docs: localize agent guide and organize feature records` |
| 2026-08-18 | 准备 | 补充上游文档检索规则和无 Docker 开发约束 | 上游指南入口、文档链接和范围检查 | `docs: preserve upstream guidance and prohibit docker` |
| 2026-08-18 | 准备 | 固定多 Worktree 本机实例和资源隔离约定 | 端口、数据目录、浏览器状态和文档链接检查 | `docs: define multi-worktree runtime isolation` |
| 2026-08-18 | M0 准备 | 刷新所有远端引用；核对固定基线、TrustGraph 固定提交、LiteLLM `1.91.3`、现有 Skill/引用/模型认证路径并细化实施切片 | 相关后端测试 126 通过；前端 391 通过；生产构建通过；Windows 基线在 UTF-8/TTY 环境下 2130 通过、13 跳过、1 xfailed，另有 1 个符号链接权限项未运行 | 待提交 |
| 2026-08-18 | M0-A | 新增供应商无关的 business context 结果/引用值对象和稳定错误类别；建立默认关闭、服务端目标绑定、SSRF/大小限制和 secret-free 错误边界；新增详细实施方案 | 新增/相邻聚焦测试 87 通过；Agent/安全/模型相邻回归 612 通过；后端全量在 UTF-8/TTY 环境下 2191 通过、13 跳过、1 xfailed、1 个 Windows 符号链接权限项未运行；前端 391 通过；生产构建通过 | 待提交 |
| 2026-08-18 | A1 | 新增后端注入且与 payload 隔离的 `SkillAuthorization`；扩展兼容旧位置参数的 `ToolResult.context_items/public_summary`；统一两条 Skill 调用路径，限制、去重并清洗引用事件，外部工具正文只进入模型观察，流与 Reasoning log 使用安全摘要；Skill 异常不再暴露原始异常文本 | 新增合同测试 40 通过；Agent/Skill/路由相邻回归 670 通过；后端全量 2208 通过、13 跳过、1 xfailed、1 个 Windows 符号链接权限项未运行；前端 391 通过；生产构建通过 | 待提交 |
| 2026-08-18 | A2 | 新增通用 Skill `enabled_if` 门，关闭时 TrustGraph 不注册且不导入；复用环境 JSON、`DF_ALLOWED_API_BASES`、现有 identity-scoped credential vault 和 `requests` 完成精确 workspace 目标解析；外部数据以 untrusted JSON 帧进入模型，以结构化引用和安全摘要向外路由；稳定错误可恢复且不泄露原始异常 | Analysis/Agent 聚焦合同 102 通过；Agent/Skill/vault/路由相邻回归 721 通过；后端全量 2233 通过、13 跳过、1 xfailed、1 个 Windows 符号链接权限项未运行；前端 391 通过；生产构建通过 | 待提交 |
| 2026-08-18 | A3 | 扩展共享 `ContextItem` 及 `InteractionEntry`/`TextTurn` 可选引用字段；复用既有流处理、Redux 状态、workspace 自动保存和 ZIP 导入导出链路累计并持久化引用，不增加平行 Session 存储；每个制品保存生成时可用的不可变来源快照，结束文本保存整轮去重来源，续接文本继承既有来源；新增共享 Sources 组件，HTTP(S) 使用隔离新标签打开，URN 只展示，非法 scheme、userinfo、反斜杠和超限字段失败关闭 | A3 前端聚焦 8 通过、相邻前端 39 通过；workspace ZIP 引用往返 9 通过；前端全量 399 通过；生产构建通过；后端全量在 UTF-8/TTY 环境下 2234 通过、13 跳过、1 xfailed、1 个 Windows 符号链接权限项未运行 | 待提交 |
| 2026-08-18 | A4 | 复用 `requests`、现有统一错误协议和 identity-scoped encrypted credential vault，实现应用拥有的有界 device-flow service；device code 只保留在服务端内存，浏览器只接收 GitHub user code、精确验证地址和不透明句柄；非阻塞 poll 遵守 interval、slow_down、expiry、deny/cancel，并发 transaction 与 identity 隔离；成功 token 写入 `github-copilot:oauth`，disconnect 只删除当前 identity；flag 关闭时 blueprint/UI 均不存在；模型配置对话框仅在显式点击后启动授权，`Client` 在 A5 前拒绝 `github_copilot/*`，防止 LiteLLM 隐式登录或共享文件写入 | A4 后端聚焦 40 通过；auth/vault/model 相邻回归 350 通过；前端聚焦 4、相邻 43 通过；关闭/开启态实际 app route/config 探针符合预期；后端全量 2274 通过、13 跳过、1 xfailed、1 个 Windows 符号链接权限项未运行；前端全量 403 通过；生产构建通过 | 待提交 |
| 2026-08-18 | A5/A7 | 审计并锁定 LiteLLM `1.91.3` Copilot Authenticator/chat transformation 源码指纹；用 `ContextVar` 和既有 `requests` 实现 identity/request-local 的长期令牌解析、短期令牌交换/刷新及惰性 stream 迭代隔离，不修改环境或 token 文件；模型注册表把 `GITHUB_COPILOT_MODELS` 作为显式候选而非通用 secret provider，直接读取静态 `model_cost` 拒绝非 chat 模式，逐模型实测 buffered chat、streaming、streamed tools；服务端只发布并允许当前 identity 三项均通过的模型，连接变化和失败复测同步撤销缓存及前端旧选择 | Copilot/model/security 聚焦回归 101 通过；前端 A5 聚焦 15 通过；后端全量 2302 通过、13 跳过、1 xfailed、1 个 Windows 符号链接权限项未运行；前端 49 文件、406 通过；Node `22.14.0` 生产构建通过；`git diff --check` 通过；远端刷新后 `origin/main`/`upstream/main` 仍为 `5477f0e` | 待提交 |
| 2026-08-19 | A6/M0-B Copilot | 使用真实 Copilot 账号完成应用拥有的 device flow，并从加密 vault 经请求局部 LiteLLM 适配执行模型准入；另在目标 Linux Node/npm 环境的仓库外隔离目录安装官方 `@github/copilot` `1.0.80` 与 `@github/copilot-sdk` `1.0.11`，仅作外部合同探针，不加入产品依赖或第二个 Agent runtime | 外部真实能力证据：`github_copilot/gpt-4.1` 的 chat、streaming、tools 均通过，约 13 秒；短期 token 缓存及刷新窗口内重新交换通过；SDK JSON-RPC ping、真实模型目录（28 项）和 CLI `gpt-5.4` 文本调用通过；真实长/短 token 在日志、隔离状态目录和 diff 中 0 命中，vault SQLite 不含明文。后端/前端测试只记为相关代码回归，不作为 M0-B 能力证明 | 待提交 |
| 2026-08-19 | M0-B TrustGraph | 在仅限外部验收的显式例外下，于仓库外 `D:\WSL` 创建专用 WSL2 + Docker 运行环境并启动 TrustGraph `2.8.14` 官方 OpenAI 部署；模型端点预留 SiliconFlow OpenAI 兼容 `/v1`，token 保持空值且不硬编码模型；本地 Caddy CA 只服务项目适配器 HTTPS 探针；未安装或启动 Ollama，也未向仓库增加容器依赖 | 外部真实服务证据：UI 入口 200；无 bearer 的 Flow 请求 401，bootstrap bearer 的 `list-flows` 200 并返回 `default`；项目适配器经校验证书链后将假 token 映射为 401/`unauthorized`；Ollama 容器和镜像计数均为 0。普通后端、前端和构建结果统一归入 A7，不作为 TrustGraph M0-B 能力证明 | 待提交 |
| 2026-08-19 | TrustGraph 结构化更正 | 按产品范围移除 Graph RAG 调用面；Windows 项目环境直接加入官方 `trustgraph-base==2.8.14` 与 `rdflib>=7.1,<8`，复用官方 Config/Flow/RDF schema/translator，实现 bound ontology、knowledge/provenance triples、只读 SPARQL；Skill 收敛为三个无目标覆盖字段的只读工具，并修复 Agent 将非对象工具参数静默变成空对象的问题 | TrustGraph client 37、Provider 17、Skill/Agent 16，合计 70 项通过；真实服务返回空 knowledge/provenance triples、`ASK=true`、`SELECT` 5 行；临时 ontology 返回 1 class/1 引用并确认清理；完整 Skill SPARQL 返回 3 行及安全摘要；`service/sparql-query` 404 后改用官方 SDK 已验证的 `service/sparql`；Python compileall 与 `git diff --check` 通过 | 待提交 |
| 2026-08-19 | 最终交付门禁 | 保留完整实施计划并只追加实际验收结果；复核 Python 依赖，使用仓库外 WSL 测试副本和隔离 Linux Node/Yarn 完成前端门禁，未调用 Windows Node/npm/yarn | `uv pip check`：158 个包兼容；后端 UTF-8/TTY 全量门禁 2311 通过、13 跳过、1 xfailed、1 deselected（仅 Windows 符号链接权限项）；Linux Node `22.14.0` + Linux Yarn `1.22.22`：49 文件、406 测试通过；Vite `7.3.3` 生产构建通过 | 待提交 |
| 2026-08-19 | A8 功能规划 | 复核 TrustGraph `2.8.14` 官方 Python SDK 与官方 MCP server：内部主链路确定为 SDK；MCP 仅作外部兼容。新增 A8-A11 路线，先交付知识目录和图实体语义检索，再做结构化 rows 入表、知识准备和 UI 收口 | 官方 SDK 方法/返回形状源码核对；官方 MCP `initialize`/`tools/list` 返回 31 个工具；文档范围、架构与里程碑同步检查 | 待提交 |
| 2026-08-19 | A8 知识发现 | 在既有官方 SDK client/provider/只读 Skill 上新增 `inspect_trustgraph_catalog` 和 `search_trustgraph_entities`；目录规范化 Flow、collection、document、processing、Knowledge Core，语义检索复用官方 embeddings 与 graph-embeddings 并保留 RDF term/score；原本体、三元组和 SPARQL 工具保持不变 | Client/Provider/Skill 聚焦 95 项、business-context 与相邻 Skill/registry 回归 152 项通过；Windows UTF-8/TTY 后端全量 2336 项通过、13 项跳过、1 项 xfailed，仅 deselect 既有符号链接权限项；Python compileall 与 `git diff --check` 通过 | 待提交 |
| 2026-08-19 | A9 范围更正 | 按用户确认撤回 TrustGraph rows 直接入表和同步方案；A9 只保留官方 GraphQL rows 的只读查询合同，禁止写 Data Formulator table/Workspace 或建立 refresh 链路 | 源码仅做只读路径核对，尚未写 A9 实现；产品、架构、交付和 Feature 计划同步检查 | 待提交 |
| 2026-08-19 | A9 只读 GraphQL rows | 新增 `query_trustgraph_rows`，调用官方 `FlowInstance.rows_query()`，支持显式 query、variables、operation name，并规范化 `data/errors/extensions`；未调用 `structured_query()`/`nlp_query()`，未导入 table/Workspace 模块 | Client/Provider/Skill 聚焦 109 项、business-context 与相邻 Skill/registry 回归 166 项通过；Windows UTF-8/TTY 后端全量 2350 项通过、13 项跳过、1 项 xfailed，仅 deselect 既有符号链接权限项；Python compileall 与零 Workspace 写入检索通过 | 待提交 |
| 2026-08-19 | A10/UI 范围收缩 | 按用户确认取消行数据语义搜索和整个 A10 文档摄取/Context Core 装载入口；官方 `trustgraph-ui` 已包含 Knowledge Explorer、Ontology、SPARQL、GraphQL、摄取等现成界面，Data Formulator 不再规划 TrustGraph 前端。保留 A8/A9 历史记录，不删除已完成事实 | 核对官方 `trustgraph-ui` monorepo 和 `@trustgraph/trustkit` 导出面；npm 实时注册表确认 `trustkit/client/react-provider/react-state` 已于 2026-08-18 发布 `2.0.3`，其中 `trustkit` 要求 React 19；同步产品、架构、交付与 Feature 文档并执行 Markdown/diff 检查 | 待提交 |
| 2026-08-19 | A11 空环境只读冒烟 | 通过仓库外 WSL2 TrustGraph `2.8.14` 和项目真实 Skill → Provider → 官方 Python SDK 路径逐一调用六个只读工具；发现 rows service 在未装载 GraphQL schema 时返回 `rows-query-error`，新增窄合同把该官方状态从误报的 `unavailable` 修正为 `not_configured`，其他 rows service 错误仍保持 `unavailable` | 真实服务：目录、图实体搜索、knowledge triples、SPARQL `ASK` 四条链路通过，`ASK=true`；rows 与 ontology 均准确返回 `not_configured`，对应当前环境 0 个 ontology 且未装载 rows schema，不伪报业务数据验收完成；TrustGraph Client/Provider/Skill 聚焦 111 项通过 | 待提交 |
| 2026-08-19 | A10/UI 收口复核 | 确认产品代码没有 `row_embeddings_query()`、摄取/Core 写操作、TrustGraph 页面或导航；既有 `ContextSources` 只展示供应商无关的分析引用，不是 TrustGraph 管理 UI | Windows 项目 Python 环境下 business-context、TrustGraph Client/Provider/Skill 共 144 项通过；检索产品源码与前端依赖未发现取消能力；未启动 WSL、Docker、TrustGraph 服务或 Node 前端门禁 | 待提交 |
| 2026-08-19 | 分支交付收口 | 完成代码审查和边界检索；将 Copilot 面板最后一处英文兜底错误改为中英文 i18n；实现、测试与依赖统一提交，事实来源文档同步收口 | 聚焦后端 284 项、前端 23 项通过；`uv pip check` 158 个包兼容；UTF-8/TTY 后端全量 2352 项通过、13 项跳过、1 项 xfailed、1 项 deselected（仅既有 Windows 符号链接权限项）；内置 Node `24.19.0` 下 49 个前端文件、406 项测试通过，Vite `7.3.3` 生产构建通过；Python compileall、`uv lock --check`、`git diff --check` 和凭据模式扫描通过 | `acdfb3c5`（实现与测试）；本记录提交（文档） |
| 2026-08-19 | 业务语义主动核对 | 在供应商无关的 Agent 系统提示中加入实质性语义核对门，并扩展 TrustGraph Skill 的按需触发指导：分析、数据准备、清洗、转换等任务若依赖未决的术语、状态、类别、标识、度量、范围、规则或关系，且不同解释会改变结果，则主动获取权威上下文；不要求用户使用知识图谱术语，不对每个词机械查询，证据不足时澄清或显式说明限制 | AnalystAgent 系统提示与 TrustGraph Skill 聚焦合同 31 项通过；Python compileall、Markdown 代码围栏/占位符和 `git diff --check` 通过 | 本次提交 |
| 2026-08-19 | SiliconFlow 全局模型 | 为全局模型注册表增加仅服务端可用的 `{PROVIDER}_EXTRA_BODY` JSON 对象，并在统一 LiteLLM Client 中复制后传递；公开模型列表不暴露该值，浏览器自定义模型不能注入。Git 忽略的本机 `.env` 注册 `Qwen/Qwen3.5-27B`，只设置 `enable_thinking=false`，未配置 temperature、top_p、上下文或正式 Agent 输出上限，也未把密钥写入 Git；该模型属于 Data Formulator LLM provider，不是 TrustGraph 依赖 | 真实 chat/stream/tools 7/7 通过且无 `reasoning_content`；真实 Agent 的模糊业务含义请求完成 `load_skill` 和三次 TrustGraph 只读调用，明确规则请求不触发 TrustGraph；能力探针中的 8/32 仅限制极短探针输出，不限制模型上下文，正式 Analyst 流未设置该值 | 待提交 |
| 2026-08-19 | 本机端到端与交付门禁 | 创建隔离验证 Workspace 和 4 行通用工作项数据；配置 TrustGraph 独立 feature flag、精确 Workspace target、只绑定本机的 HTTPS 入口和 CA。在 Agent 统一 tool-call 分发边界对 provider 参数只解析一次；只接受 JSON 对象，不猜补畸形内容，不把无效字符串交给任何 Skill/Action 或写回 assistant history，失败后由模型下一轮重试 | TrustGraph 配置合同 5/5；实际 `/api/agent/analyst-streaming` 自动加载 Skill 并尝试目录查询，因 vault 无有效 bearer 安全返回 `not_configured` 后澄清，未编造业务含义；真实 Qwen 重跑完成 `load_skill` 和三次 TrustGraph 查询并正常结束，参数错误与思考内容均为 0；相关聚焦 136 项通过。UTF-8/PTY 后端全量除 Windows 无符号链接权限用例外 2362 项通过、13 项跳过、1 项 xfailed；前端 406 项和生产构建通过。Copilot vault/请求隔离通过，但 GitHub token exchange 当天返回临时不可用/无效响应，未虚报真实 3/3 成功 | 待提交 |
| 2026-08-20 | 本机配置复检 | 将 Git 忽略的本机 `.env` 中两个 JSON 对象改为整体单引号包裹，避免 `uv --env-file` 去除内部双引号；应用自己的 `python-dotenv` 读取方式保持兼容。未改变模型参数、TrustGraph target 或凭据边界 | 两种加载路径均成功解析 target 与 `enable_thinking=false`；TrustGraph 非秘密配置验收 5/5，HTTPS 匿名 401 且缺凭据稳定失败关闭；真实 Qwen chat/stream/tools 与两种 Agent 场景 15/15，模糊语义自动多轮查询、明确规则不查询、思考内容与非法工具参数均为 0。有效 bearer 仍未提供，因此没有伪报真实知识装载和六工具数据语义验收完成 | 待提交 |
| 2026-08-20 | A11 合成知识真实链路 | 从现有 `deploy-openai` 安装配置经官方 `whoami` 合法恢复管理员操作能力，仅用其创建一年期专用 `reader` API key；Data Formulator 只在 `local:lenovo` identity 的加密 vault 中保存 reader key，未保存 admin token。创建并启动专用 TrustGraph workspace/`default` Flow，装载通用合成 ontology、schema、collection、document、RDF、实体向量和 rows；修正仓库外验收装载器在 Windows/WSL 下 `localhost` 优先 IPv6导致的 WebSocket 超时，未改产品运行时代码 | reader `whoami` 仅返回 `reader`；装载 55 个四元组、6 个实体向量和 3 行结构化数据。真实 Skill → Provider → 官方 SDK 六工具 6/6：目录 1 个目标 collection、实体 3、本体 5 classes、rows 3、triples 10、SPARQL `ASK=true`；真实 `/api/agent/analyst-streaming` 使用 Qwen 自动完成 `load_skill`、实体检索和两轮三元组查询，TrustGraph 结果均为 `ok`、错误 0、最终 `completion`。这些证据证明真实技术链路，不代替生产业务数据的语义确认 | 待提交 |
| 2026-08-20 | A12 原生 Agent 架构更正 | 复核锁定 SDK 和 TrustGraph `2.8.14` 源码后确认原生 Agent 已支持工具组、`knowledge-query`、`structured-query` 和 Explainability；撤回六个底层产品工具，改为一个 provider-neutral 业务上下文查询。系统提示和 Skill 只提交一个聚焦问题及可选最小上下文；服务器绑定 Flow、collection、只读工具组和凭据。真实环境已把 `knowledge-query`/`structured-query` 绑定到专用只读组和目标 collection，Flow 模型切为 `Qwen/Qwen3.5-27B`，部署配置使用 Qwen variant、`thinking=off` 并安全写入已有 SiliconFlow key | 聚焦 120 项、Analyst/Agent 699 项通过；UTF-8/TTY 后端全量 2327 通过、13 跳过、1 xfailed，仅排除 1 个 Windows 符号链接权限项；Node `24.19.0` 下前端 49 文件/406 项与生产构建通过；compileall、`uv pip check`、`uv lock --check`、`git diff --check` 通过。真实 Data Formulator reader bearer → HTTPS → `service/agent` 已到达 TrustGraph，当前稳定返回 `unavailable`；独立 text-completion 探针确认唯一阻塞是运行进程尚未重载新环境，仍返回 `401 Invalid token`；未使用 Docker 命令、未伪报真实 Agent 成功 | `3d345091` |
| 2026-08-20 | A12 重载与真实原生 Agent 验收 | 按用户明确要求只重载仓库外 existing `deploy-openai` 的 text-completion 与 control 服务：前者载入既有 SiliconFlow 凭据，后者恢复 Flow 重建后丢失的 librarian RabbitMQ binding；清理误创建的重复 text-completion 实例，最终只保留 active project 中一个实例。根据真实响应确认 TrustGraph `2.8.14` HTTP gateway 返回终态 AgentResponse，而同步 SDK 仍读取旧 `{answer}`，在适配器边界增加严格双形状规范化，拒绝 thought/observation/partial answer。验收知识原来只有 triples/`rdfs:comment`，补充官方 entity contexts 索引和 GraphRAG 可遍历的领域中立业务关系，不在 Data Formulator 写死术语或答案 | Qwen 文本补全真实返回 `TG_OK`；Graph embeddings 命中 engagement/coverage，GraphRAG 返回权威定义、不可互换和实体键/范围/单位/报告期对齐规则；真实 Data Formulator `query_business_context` 返回 `ok`，ReAct 第 1 轮自动调用 graph-rag、第 2 轮完成回答，librarian 保存 thought/observation/answer，trace 为官方 session URI。Client 44 项、四文件聚焦 118 项、Analyst/Agent 706 项、后端全量 2334 项和前端 406 项通过，生产构建及 Python/依赖/锁文件/diff 门禁通过；13 项跳过、1 项 xfailed，仅排除 1 个 Windows 符号链接权限用例；未改仓库 Docker/Compose 文件 | `3d345091` |
| 2026-08-20 | A12 本体/图谱统一检索 | 真实验证确认 ontology 配置只指导摄取，不会被 Agent 直接当作业务知识搜索；按现有图谱建模方式把类定义、object/datatype property、domain/range、`businessDefinition` 和来源边实际导入同一 collection，并补齐图实体上下文。Data Formulator 固定任务帧明确只用本轮工具：定义/编码/分类/状态/范围/单位/规则/关系走 `knowledge_query`，结构化事实才走 `structured_query`，禁止通用 search/browse 和行级语义匹配；多部分证据不足时允许原生 Agent 缩窄问题再查。未修改 TrustGraph 源码 | 验收 collection 共导入 105 条 RDF/quads 和 16 个图实体上下文；SPARQL 精确确认 WorkItem 定义及 5 个 domain/range，GraphRAG 返回定义。普通清洗场景 1 次 `knowledge_query` 完成；跨定义、不可互换与比较规则的场景由同一 Agent 自动 2 次 `knowledge_query`，librarian trace 保存两轮 thought/observation；中文输入通过。临时 MCP triples/SPARQL 配置因 `2.8.14` 出站客户端签名不兼容已删除，未注册死工具；聚焦回归 91 项、后端全量 2334 项、前端 406 项和生产构建通过 | `3d345091` |
| 2026-08-20 | A13 最小产品化设计 | 复核 A12 当前实现和真实验收后，将剩余工作收敛为主路径产品化：默认目标加精确 workspace 覆盖、请求时本地就绪判断、tool-only Skill 可发现、完整用户输入回归、单一进度提示、`source`/`trace` 区分、有界 `resume_text`、生产候选知识验收和 Copilot capability 复用。生产基线只要求 `knowledge_query`；现有只读组中的 `structured_query` 保留，另找真实受治理结构化记录场景验收，不因 A13 暂未使用而移除 | 产品范围、现有能力、系统设计、交付计划和 Feature 实施方案已同步；未改产品代码、TrustGraph 部署或凭据，文档一致性与 diff 检查见本次工作区验证 | 待提交 |
| 2026-08-20 | A13 最小产品化实现 | 复用现有 resolver、Skill registry、Agent trajectory、Data Thread 引用通道和 capability store：增加精确 workspace → `default` 目标解析、当前 Workspace 本地配置状态、请求级目标/reader 就绪过滤、tool/action 对称发现、单一业务知识进度、`source`/`trace` 分组、最大 1 Mi 字符的模型续接证据，以及 Copilot 成功/失败 capability 缓存复用和显式复测；固定 TrustGraph 帧只指导 `knowledge_query`，没有新增查询工具、服务或管理 UI，也未移除服务器组的 `structured_query` | 聚焦后端 106 项、前端 19 项通过；Windows UTF-8/TTY 后端全量 2346 项通过、13 项跳过、1 项 xfailed、1 项 deselected（仅既有符号链接权限项）；内置 Node 下前端 51 文件/412 项与 Vite `7.3.3` 生产构建通过；compileall、`uv lock --check`、`uv pip check`、locale JSON、Markdown 链接/围栏、凭据扫描和 `git diff --check` 通过。真实 `Qwen/Qwen3.5-27B`、`thinking=off` 链路中新 Workspace 通过 `default` 显示已配置；多部分输入产生 2 次外层查询，两个 session 内分别执行 2 次和 1 次 `knowledge_query`；明确规则 0 次查询；临时坏 Flow 返回 `protocol_error` 后模型保留原值。临时配置已清理，合成知识不冒充生产知识 | 待提交 |
| 2026-08-20 | A14 `agent_explain` 实时步骤设计 | 核对锁定 `trustgraph-base==2.8.14` 的 `agent_explain`/explainability 类型、官方 TrustKit/React packages 和现有 Skill/NDJSON/`thinkingSteps` 路径，将方案收敛为服务端单 WebSocket、一个 `tool_progress` 事件、有限阶段映射和 trace 查询轮数摘要；不安装 TrustKit，不新增浏览器 WebSocket、路由、状态库或完整 ReAct UI | 真实 reader 直连同一 Gateway 完成一次普通中文多部分问题：17 个 provenance 事件、2 轮 `grounding → exploration → focus → synthesis → observation`、最终 `Conclusion`；同时观察到 185 个 Thought 和 243 个 Answer 分片，确认它们必须丢弃/仅服务端聚合。当时 9443 Upgrade 返回 400，已由后续 A14 实现修通 | 已由 A14 实现落地 |
| 2026-08-20 | A14 Portal 补充调研 | 核对官方 `@trustgraph/portal` package、入口、认证壳、路由、Agent/Explain 页面和 UI service。Portal 是 2026-08-13 从 demo 改名的 `private: true` React 19/Vite 完整 Workbench，不是第四个发布库；它组合 TrustKit/provider/state 并自行拥有登录、Socket、workspace、QueryClient、Router、主题和插件运行时。当前 `/agent`、`/explain` 不接受既有 query/session/explain id 深链，因此不安装、不复制、不 iframe；继续作为独立管理/完整追踪界面。其 `/api/v1/socket` 同源 Upgrade 代理只用于佐证 A14 的单 `api_base` WSS 前置 | 官方源码与 npm registry 交叉核对；`@trustgraph/portal` 未发布、`@trustgraph/trustkit@2.0.3` 要求 React 19；未修改产品代码或外部服务 | 已收口 |
| 2026-08-20 | A14 `agent_explain` 实时步骤实现 | 将 TrustGraph 实际网络路径改为官方 `Api.socket().flow(...).agent_explain(...)`，`query()` 只消费同一生成器；新增 provider-neutral `BusinessContextProgress`、Skill/Agent `tool_progress` 合同、有限阶段压缩、终态答案聚合、socket 关闭、`query_count` 和现有 `thinkingSteps` 原位更新。Thought、Observation 正文、action 参数、triples 和 answer 分片不进入 NDJSON；同步 Skill、引用、续接和错误合同保持不变 | 聚焦后端 97 项通过；Windows UTF-8/TTY 后端全量 2339 项通过、13 项跳过、1 项 xfailed、1 项 deselected（仅既有符号链接权限项）；内置 Node 下前端 51 文件/414 项与 Vite `7.3.3` 生产构建通过；compileall、`uv lock --check`、`uv pip check` 和 `git diff --check` 通过。仓库外 9443 代理已支持 WSS Upgrade；真实 provider 自动两轮并返回 `query_count=2`，真实 `/analyst-streaming` 自动加载 Skill、完成一轮及包含两轮的查询并正常 completion。独立公开流扫描确认 progress 字段有界、bearer/explain 原始字段 0 泄漏、公开工具结果仍为安全摘要；真实浏览器会话显示“业务知识已配置”，并实际经历通用等待、检索、证据完成和结论阶段，最终答案及独立不可点击的“检索轨迹（1）”正常落入会话 | 待提交 |
| 2026-08-20 | A15 IOF 制造业知识与真实清洗验收 | 从 IOF 官方仓库固定 `Release_202602`/提交 `4c905ad2`，装载 Annotation Vocabulary、Core、Production Planning 三个 RDF 文档；原始知识进入 GraphRAG 默认知识图，固定 GitHub blob、文件哈希和 RDF-star 派生关系进入来源图，218 个实体上下文仅由上游定义/关系构造。固定 Agent 任务帧增加通用跨语言补查规则，Skill 明确查询失败不能由模型记忆替代；未修改 TrustGraph 源码或增加 Data Formulator 摄取面 | 4,835 条上游 RDF triples，验证目标共 6,878 条知识/来源/溯源记录、3 个原始文档和 218 个实体上下文；精确 SPARQL、英文语义检索及直接 GraphRAG 均命中 IOF 定义。真实中文 `/analyst-streaming` 使用生产订单/计划/操作/设备/数量/时间字段，自动完成 `load_skill`、单个 `query_business_context` 内两轮检索和 completion，无 Python/图表调用；聚焦后端 58 项通过。锁定 Agent 协议不透传 GraphRAG sources，因此只保留真实两轮 trace，不伪造 citation | 待提交 |
| 2026-08-20 | A16 Collection/Profile 设计纠偏 | 复核 TrustGraph workspace、collection、Knowledge Core、工具配置和 Agent group 后，撤销“默认组合一个 serving collection”的结论：Core 只解决同一治理域内的来源复用，未知问题由 Agent 在 collection-bound 工具间实时路由。最终架构不新增组件：workspace/bearer 授权，group 筛选本轮可见工具，Profile 只是现有 target；领域工具名和描述保持稳定，发布时只切换其 collection 版本。A16 代码仅更正 `trace_collection`、任务帧工具名和进度 action 三处语义硬编码，并按字段合同、单域、双域、版本切换和完整门禁实施。大量动态 collection 需要 TrustGraph 侧 catalog/router，当前不伪装成已支持 | 产品范围、现有能力、系统设计、交付计划、Feature 实施方案和制造业部署说明已同步；本节点仅文档设计，未修改代码、TrustGraph 配置或凭据 | 待提交 |
| 2026-08-21 | A16 Collection/Profile 实现与真实验收 | 目标合同直接删除 `collection` 并只接受必填 `trace_collection`，无旧字段兼容；任务帧依据本轮实际只读工具的名称与描述选择最小充分集合，不写死 action；实时步骤按官方 `Analysis` 类型和 GraphRAG 阶段计数。真实混合类型工具事件虽被锁定 SDK 解析成 `Reflection`，适配器也只精确识别该事件自身的 `tg:Analysis` 类型，不公开 action、thought、参数或 triples。TrustGraph 验收组使用稳定业务术语工具、制造业本体工具并保留 `structured_query`，没有行级语义工具 | 干净业务术语 Core 装入 `dfm-business-glossary-v3`，固定 IOF Core 装入 `dfm-iof-release-202602-v2`；A-only 只调用术语工具，B-only 只调用本体工具，A+B 各调用一次并得到两轮完整实时步骤。由同一 Core 发布 `dfm-business-glossary-v4` 后，仅切换稳定工具绑定即可在 Data Formulator 请求不变时查询成功，随后已切回 `v3`。外部文本补全消费者曾因中止请求留下队列工作，精确重载该处理组后恢复；锁定 SDK 缺少总请求取消仍列为运维风险。聚焦后端 101 项、Analyst 后端 94 项通过；Windows UTF-8/TTY 全量后端 2343 项通过、13 项跳过、1 项 xfailed、1 项 deselected（仅既有 symlink 权限项）；内置 Node `24.19.0` 下前端 51 文件/414 项和 Vite `7.3.3` 生产构建通过；compileall、`uv lock --check`、`uv pip check` 通过 | 待提交 |

## 已确认决策

- Data Formulator 只保留现有 `AnalystAgent` 作为产品编排者；TrustGraph 原生 Agent 是 Skill 后面的外部只读检索提供者，不拥有 Data Thread、Workspace、本地工具或用户交互。
- TrustGraph 不只响应直接知识问答。在交互式 `AnalystAgent` 中，未决业务含义若会实质改变数据选择、计算、映射、连接、分组、去重、单位、时间边界、解释或结论，应在执行前按需加载相关 Skill 并迭代取证；规则明确或不影响结果的机械操作不查询。该指导不改变 Recipe/Run 不调用 TrustGraph 的边界。
- 全局 OpenAI 兼容模型可以通过服务端 `{PROVIDER}_EXTRA_BODY` 设置最小的提供商原生请求默认值；该对象不公开，只允许 trusted registry 配置进入 LiteLLM，浏览器 payload 不能覆盖。SiliconFlow 模型配置与 TrustGraph 的只读 SDK 查询路径相互独立。
- Copilot 继续经过 LiteLLM，不接 Copilot SDK。
- Copilot M0-B 以目标 Linux Node/npm 环境中的官方 CLI/SDK 真实账号请求和产品自身 device flow → Vault → LiteLLM 链路为证；Linux 前端测试与构建只属于 A7 普通回归。
- 引用通道是通用 Skill 契约，不在 Agent 中硬编码 TrustGraph。
- Skill 授权上下文只能由已认证路由注入，并与自由 payload 分离；迁移期无授权的本地 Skill 仍兼容，需要外部服务的 Skill 必须失败关闭。
- 引用 URI 只接受 `http`、`https` 和 `urn`，Agent router 再校验、按 URI 去重并限制每个工具事件最多 50 项；Reasoning log 只记录数量和 provider。
- `ToolResult.public_summary` 是外部工具正文的可选安全替代，只用于前端工具事件和运维摘要，完整正文仍只作为模型观察。
- Skill frontmatter 的通用 `enabled_if` 是后端 availability 门；flag 关闭时对应 Skill 不进入 registry，Python 模块也不导入。
- TrustGraph 使用 `TRUSTGRAPH_TARGETS_JSON` 保存非 secret 目标；解析顺序固定为当前 Data Formulator workspace 的精确 key 优先、保留 key `default` 后备。`credential_ref` 必须在独立 `trustgraph:` namespace 中，并通过现有 identity-scoped vault 解析 `bearer_token`。
- 每次构造 Agent registry 时复用同一目标解析器做本地就绪判断；只有目标和当前 identity 的 reader 凭据均存在才提供 TrustGraph Skill，不做外部健康探测。当前 Workspace 菜单通过只读状态 endpoint 显示同一配置判断，不能据此声称服务在线；Provider 调用时仍重新授权并失败关闭。
- `ToolResult.public_summary` 继续只服务公开工具事件和日志；有界 `resume_text` 只把最终答案和官方明确来源用于模型 trajectory 续接，不保存 hidden thought、原始响应或凭据，也不增加服务端恢复数据库。
- 前端引用字段只做可选增量，不提升 Session schema 版本；旧 Session 缺字段时保持原对象形状和 UI，现有自动保存、恢复以及 ZIP 导出/导入会原样保留结构化引用。
- 来源在前端再次规范化、按 URI 去重并限制 50 项；可选 `ContextItem.kind` 区分 `source` 与 `trace`，旧数据默认 `source`。只有无 userinfo 的 HTTP(S) 文档来源生成 `target="_blank"`、`rel="noopener noreferrer"` 链接，trace 即使是 HTTP(S) 也不作为文档链接，并单独展示。
- 外部上下文作为不可信数据处理。
- capability probe 至少覆盖 chat、streaming 和 tools。
- TrustGraph 产品内部主通道固定使用官方 `trustgraph-base==2.8.14` 的原生 Agent；外层只提供一个 `query_business_context`，底层目录、graph embeddings、ontology/triples/SPARQL/GraphQL 不再注册为六个模型工具。
- 通用 Skill registry 分别描述 tool 和 action；tool-only Skill 不再显示“无 action”后让模型误以为没有能力。验收从真实用户输入和当前未预加载 registry 开始，不以测试中手工注入 `_loaded_skills` 代替发现链路。
- 高层查询只发送聚焦问题和可选最小上下文。最小上下文包括当前操作/决策、相关数据源或表的角色、字段名和类型、少量非敏感代表值或脱敏值模式、用户明确约束；不发送整表、无关行、原始敏感值、完整聊天、代码、路径、identity/workspace 或目标配置。
- TrustGraph workspace 是授权/所有权边界，collection 是其中的扁平知识分区，不是目录或自动检索层级；各 RAG/structured 工具自己绑定一个 collection。Knowledge Core 是 workspace 级独立抽取制品，可通过 `load_kg_core(id, flow, collection)` 在同一治理域内复用和组合来源；它不是未知问题的路由机制，也不要求把所有领域预先合并。锁定 SDK 的 `AgentRequest.collection` 用于 session provenance trace，不能作为全部内部工具的 retrieval 路由。
- bearer 绑定的 TrustGraph workspace 是授权和所有权边界；Agent group 只是该 workspace 内本轮模型可见工具的路由清单，不新增 IAM。组内按发布生命周期和知识连通性配置一个或少量 collection-bound 工具，Agent 根据当前问题选择并可多轮调用。领域工具名、范围描述和 group 标签保持稳定，发布时只切换其 collection 版本；固定任务帧遵循当前 group 实际工具，不硬编码 `knowledge_query`。现有组继续保留 `structured_query`，后续再用受治理结构化记录做独立验收。不向该组加入 row embeddings/行级语义匹配、通用文本补全、写操作、摄取或管理工具。
- Data Formulator 的服务端知识 Profile 只绑定 TrustGraph workspace、Flow、单个 Agent group、trace collection 和凭据引用；不保存 retrieval collection 数组，不动态扫描 workspace，不 fan-out，也不自行合并跨 collection 排名。用户、前端和模型不能选择 Profile 或原始 collection id。
- Core 装载和各知识域 collection 的版本发布只发生在查询前的 TrustGraph 控制面；每次 `query_business_context` 只读取 group 已绑定的已发布集合，绝不临时创建 collection、调用 `load_kg_core`、枚举 Core 或切换 group。当前产品源码也不存在这些写路径。
- ontology 配置用于指导摄取流程；Agent 搜索的是工具所绑定 collection 中已经导入的知识。需要自动核对的类型定义、属性、domain/range 和关系必须由部署方连同来源实际装载到相应知识域，并建立图实体上下文。
- 公共制造业验收使用固定版本 IOF 文件和哈希：知识 triples 进入 GraphRAG 默认知识图，来源元数据进入 `urn:graph:source`，原始文件保存在 Library。跨语言首轮缺证时只允许保持原含义再补查一次，不维护硬编码制造业翻译表。
- Data Formulator 只消费最终答案、provenance trace 和 explain 事件类型归一化出的有限状态，不展示或依赖 TrustGraph Agent 的隐藏思考链。只有官方响应明确返回的文档 URI 才进入 `source`；Agent provenance URI 进入 `trace`，实体/谓词 IRI 不是来源。前端按真实轮次更新“业务知识检索”步骤，但不转发 Thought、Observation 正文、工具参数、原始 triples 或 token 级答案。
- TrustGraph UI 不进入 Data Formulator：官方 `trustgraph-ui`/`@trustgraph/trustkit` 已覆盖图谱浏览、Ontology、SPARQL、GraphQL 和摄取工作流。`trustkit@2.0.3` 已发布但要求 React 19，完整 `AgentWithTimelineView` 还拥有自己的 Agent/session/state 链；Data Formulator 只借鉴 ExplainTimeline 的紧凑交互，不安装包、不复制源码、不升级 React，完整 UI 独立使用。
- A14 继续使用现有服务器目标、reader bearer 和 `/analyst-streaming` NDJSON。TrustGraph WebSocket 只存在于后端；同一 `api_base` 必须支持 `/api/v1/socket` WSS Upgrade，不为当前本机代理问题增加第二套 endpoint 配置。
- 官方 MCP server 暴露了大量查询和管理工具，但产品后端不再叠加 MCP 客户端；MCP 只作为外部自动化兼容面。`2.8.14` 生成部署中 MCP 默认 gateway 端口与实际 API Gateway 存在 `8888/8088` 差异，且 flow 镜像的出站 `mcp-tool` 仍使用已失效的 `headers=` 客户端签名；启用时必须由 TrustGraph 上游修复/升级后单独验收，不能在本项目局部打补丁。
- TrustGraph 请求体中的 `workspace` 只用于路由，bearer token 仍是目标 workspace 的授权边界；Data Formulator workspace 必须先经过服务端允许目标映射，不能由前端直接指定 Flow、collection、Agent group 或 token。
- LiteLLM `1.91.3` 已包含 `github_copilot/*` 的 chat、streaming、tools 和短期 Copilot token 刷新代码，但其内置 Authenticator 会在进程用户目录保存 token，并在普通模型调用中同步执行 device flow；它不能直接作为多 identity 的 Data Formulator 凭据层。
- Copilot device flow 由 Data Formulator endpoint 驱动，长期 GitHub access token 只进入现有 identity-scoped encrypted credential vault；轮询必须遵守 GitHub 返回的 `interval`、`expires_in` 和 `slow_down`，不能在普通模型请求中固定休眠等待。
- A4 实际只使用现有 encrypted credential vault 保存长期 GitHub token；Flask Session 不保存 device code 或 token。未完成 transaction 是有上限的进程内状态，服务重启后需重新开始，完成后的 identity-scoped 连接可从 vault 恢复。
- 生产 device/token URL 固定为 GitHub 官方 endpoint；`GITHUB_COPILOT_CLIENT_ID` 仅作为非 secret 可选覆盖，默认复用锁定 LiteLLM `1.91.3` 的公开 client id。前端不能传 base URL、client id、scope、device code 或 token。
- Copilot API 仅在 `GITHUB_COPILOT_ENABLED=true` 时注册；app config 只暴露布尔 capability。UI 只接受精确的 `https://github.com/login/device` 链接并使用隔离新标签。
- `disconnect` 表示删除 Data Formulator 本地 vault 凭据，不等价于 GitHub 账户侧 revoke；需要完全撤销时由用户在 GitHub 授权设置中完成。
- LiteLLM `1.91.3` 的 Copilot provider 会主动调用内部 Authenticator，不能仅靠传入 `api_key` 绕过共享文件存储。A5 必须证明一个带版本保护的请求局部 Authenticator 适配层，每次模型调用只暴露当前 identity 的短期 Copilot token；禁止切换进程级环境变量或共享 token 目录。
- `ping()` 只说明文本调用成功。capability probe 是配置和可选模型准入检查，不替代现有 runtime degradation，也不按模型名称猜测能力。
- 现有 `AnalystAgent` 使用 Chat Completions；LiteLLM 标记为 Responses-only 的 Copilot 模型第一版不注册，不能只因模型出现在 catalog 中就宣称可用。
- Copilot 候选只从 `GITHUB_COPILOT_MODELS` 显式读取，不接受通用 `{PROVIDER}_API_KEY`/`API_BASE` 路径；静态模式预筛直接读取 LiteLLM `model_cost`，禁止调用会实例化交互式 Authenticator 的 `get_model_info()`。
- A5 适配器只在 `Client` 已收到当前 identity 的 vault token 时安装；精确匹配 LiteLLM 版本和两段源码 SHA-256，升级或合同漂移时失败关闭。长期/短期 token 不进入 `Client.params`，惰性 stream 每次 `next()` 也在独立 `ContextVar` scope 中解析，yield 前即清除。
- capability cache 是有上限的 identity/model 进程内布尔结果，不保存 token、prompt 或原始错误；连接完成、断开或凭据缺失会按 identity 清除。普通请求与 UI 都要求当前 identity 已通过 buffered chat、streaming 和 streamed tool-call 三项探针，不能通过手工 payload 绕过；模型对话框优先复用已有结果，只在缓存缺失、连接变化或用户显式复测时重新访问网络。
- `TRUSTGRAPH_ENABLED` 不能只隐藏前端：关闭时 Skill 不得进入可调用工具集合。`GITHUB_COPILOT_ENABLED` 关闭时模型注册表不得发现或实例化 Copilot endpoint。
- GitHub 官方 npm CLI/SDK 仅用于仓库外真实账号探针；产品仍通过锁定的 LiteLLM provider 和现有 `AnalystAgent`，不把 SDK 引入运行时或仓库依赖。

## 未决与风险

- LiteLLM Copilot provider 使用 `copilot_internal/v2/token`、固定 IDE 标识头和内部 Authenticator 扩展点；应用适配层必须有锁定版本的合同测试，并在 LiteLLM 版本不匹配时失败关闭。
- Copilot 真实 device flow、chat、streaming、tools、短期 token 缓存和刷新窗口内重新交换已验证；长期 GitHub OAuth token 的自然过期、账号侧 revoke 和重新连接仍需后续生命周期验证，不能破坏性模拟为已完成。
- 官方 SDK 返回的当前账号模型目录与 LiteLLM `1.91.3` 静态目录存在版本漂移；本分支只允许显式候选且以三项实测准入，新增模型需先升级并重新审计 LiteLLM 合同，不能把 SDK 变成第二条产品模型路径。
- 本机官方 Copilot CLI 的内置 `login --device-code` 网络运行时未能访问 GitHub device endpoint，但同端点经 curl、Node、Python 和 Data Formulator device flow 均返回成功；CLI 使用本次 OAuth token 的进程级环境注入后真实调用通过，因此该问题记录为本机 CLI 登录兼容性，不影响产品路径。
- TrustGraph 真实 bearer、workspace、Flow、项目 HTTPS 错误边界、bound ontology、knowledge/provenance graph、图实体上下文与只读 SPARQL 已验证。验收 collection 已能由 GraphRAG 返回 ontology 定义和关系；生产 collection 仍必须由部署方完成同样的知识准备和语义确认，产品不能从 ontology 配置或字段标签猜测答案。
- TrustGraph 官方 `2.8` 本地服务位于仓库外专用 WSL2 环境，只是用户明确授权的外部验收实验室；它不改变仓库默认的无容器开发方案，不新增镜像、Compose 配置或产品运行依赖，也不作为普通回归的前置条件。模型路径只使用 OpenAI 兼容接口，不引入 Ollama。
- A3 已完成通用引用绑定、持久化和安全展示；TrustGraph 结构化结果会从合法 URI 产生 provider-neutral `ContextItem`，真实图中的引用覆盖度仍需外部数据验证。
- 上游 `dev` 已改动 `src/components/ComponentType.tsx`、Redux 和 `App.tsx`，但远端 `main` 仍停在固定基线；本分支不合并移动的 `dev`，未来升级时需单独处理引用类型冲突。
- Vite `7.3.3` 要求 Node `^20.19.0 || >=22.12.0`；本机默认 Node `20.15.1` 不满足要求，历史门禁使用隔离的 Linux Node `22.14.0`，本次分支收口使用 Codex 内置 Node `24.19.0`。
- A8/A9 的底层接口测试和真实数据只保留为历史技术证据；A12 产品运行时不再注册或直接调用这些接口。最终语义验收以单个 `query_business_context` → TrustGraph 原生 Agent 链路为准。
- 本机 TrustGraph 文本补全和 control 已按用户明确要求完成重载，Qwen 原生 Agent 成功场景已重跑。剩余部署风险是生产环境是否已把受治理的 ontology/术语、定义和关系作为可查询知识导入目标 collection，而不是模型或传输链路。
- A13 主路径和 A15 IOF 公共制造业知识已在当前外部环境重跑；剩余外部风险不是公共本体是否可检索，而是生产环境是否已准备组织自己的受治理术语、编码、规则、来源、reader、collection 与只读工具组。IOF Production Planning 上游仍是 provisional，不能替代企业语义确认。
- A14 的真实 `agent_explain` 已通过同一个 allowlisted 9443 HTTPS/WSS 入口验证；本机代理透传 Upgrade，并以组合 CA bundle 同时信任公共模型端点和本地 TrustGraph 证书。没有浏览器直连、关闭 TLS 校验或第二套目标配置。
- 锁定版本的真实工具调用事件会同时声明 `Analysis`、`ToolUse`、`Reflection` 和 `Thought`，但 SDK 优先解析为 `Reflection`。适配器只精确识别该事件自身的官方 `tg:Analysis` 类型来启动通用进度，不读取 action、hidden thought、参数或原始 triples；UI 只承诺“第 N 次业务知识检索”。
- 锁定版本的直接 GraphRAG 返回文档来源，但高层 `AgentAnswer` 不透传内部 source 列表。Data Formulator 当前只显示 session trace，不通过第二条查询或答案 URL 猜 citation；这属于 TrustGraph Agent 协议边界。
- 当前 active group 的业务术语工具绑定干净的 `dfm-business-glossary-v3`，制造业本体工具绑定 `dfm-iof-release-202602-v2`；`structured_query` 仍绑定历史结构化验证集合并保留待验收。这些集合证明按域路由和版本发布机制，不是组织自己的生产候选知识。
- 分域 group 的父 Agent trace 可以固定写入 `trace_collection`，但锁定协议不保证把每个 collection-bound 子查询的文档来源完整透传到父 `AgentAnswer`。A16 先真实验证单域选择、跨域多轮和 session trace；协议缺口只如实记录，不在 Data Formulator 增加低层二次查询或自制 trace 聚合器。
- 锁定 SDK 的 `timeout` 只覆盖认证/连通探针，不是 `agent_explain` 整体 deadline；客户端中止也不会取消已经进入 TrustGraph RabbitMQ 的服务端工作。本次中止请求曾使文本补全处理组积压，精确重载该组后恢复。当前不在 Data Formulator 用线程超时制造更多孤儿任务；生产部署需监控队列和消费者，并在 TrustGraph 提供正式取消/总 deadline 合同后再接入。

## 合并前检查

- [x] M0-A 离线 TrustGraph 合同有可重复测试和明确结论。
- [x] M0-B 使用真实 Copilot 账号完成 device flow、chat、streaming、tools 和短期 token 刷新探针。
- [x] M0-B 使用真实本机 TrustGraph 服务完成 bearer、workspace、`default` Flow 和项目 HTTPS 基础探针。
- [x] M0-B 用官方 SDK/项目客户端验证真实 bound ontology、knowledge/provenance triples 与只读 SPARQL；空图已如实记录，未以 LLM 生成结果作为前置条件。
- [x] 两个 feature flag 默认关闭。
- [x] 关闭 TrustGraph 不影响本地知识。
- [x] 关闭 Copilot 不影响现有 provider。
- [x] Secret 和来源内容没有泄露到日志（离线替身、稳定错误、真实 Copilot 长/短 token、隔离状态目录、vault 明文与 diff 均已复核）。
- [x] `uv run pytest`、`yarn test`、`yarn build` 通过（Windows 符号链接权限项按工程记录排除）。
- [x] A8 知识目录和图实体语义检索合同、Provider、Skill 聚焦测试通过。
- [x] A9 TrustGraph GraphQL rows 只读合同、Provider 和 Skill 测试通过，且没有 table/Workspace 写入路径。
- [x] A10 已按产品决策取消；行语义搜索、文档 processing 与 Context Core 管理均不进入 Data Formulator。
- [x] A11 已完成空环境六工具非破坏性冒烟，并准确区分成功、未配置与真实故障。
- [x] A11 已完成空环境及合成通用知识的真实端到端验收；生产业务语义仍由部署方确认，MCP 保持按需外部兼容且未修改 Data Formulator 前端。
- [x] A12 关闭六工具产品面，完成单工具、最小上下文、scope/target 绑定、原生 Agent 请求、错误清洗和 trace 引用的离线合同。
- [x] A12 真实环境完成 reader bearer、目标 collection、专用只读工具组、Qwen Flow 与 non-thinking 部署配置；未执行 Docker 命令。
- [x] 仓库外 TrustGraph 已重载并完成原生 Agent 一轮、自动两轮和中文输入的真实成功场景；ontology/图谱统一检索生效且无行级语义匹配工具。
- [x] A13 完成 `default` 目标后备、请求时就绪过滤和 tool-only Skill registry，并从完整用户输入验证自动查、跳过和证据不足三类路径。
- [x] A13 为当前 Workspace 提供不访问 TrustGraph 网络的“已配置/未配置”状态，并验证精确目标和默认目标均可解析。
- [x] A13 完成单一业务知识进度、`source`/`trace` 分组和有界 `resume_text`，旧会话保持兼容。
- [x] A14 后端通过官方 `agent_explain` 聚合最终答案并把真实一轮/两轮 provenance 压缩为有限 `tool_progress`；Thought、Observation 正文、参数、triples 和 answer token 不进入 NDJSON。
- [x] A14 前端复用现有运行步骤实时更新轮次/阶段，成功 trace 显示实际查询轮数；不安装 TrustKit 或新增前端状态栈。
- [x] 当前 allowlisted TrustGraph HTTPS 入口支持 `/api/v1/socket` WSS Upgrade，并完成真实 Data Formulator 全链路验收。
- [x] 固定版本 IOF Core/Production Planning 已按来源清单导入，精确查询、语义检索、GraphRAG 和真实中文数据清洗的自动两轮路径均通过。
- [x] A16 已完成 Collection/Profile 架构设计并同步事实文档；明确按治理域配置 collection-bound 工具、由 Agent 查询时路由，以及 `trace_collection` 语义。
- [x] A16 完成 `trace_collection` 字段硬切并拒绝 `collection`、通用工具提示、无 action 名硬编码的通用进度，以及单知识域、双知识域 A-only/B-only/A+B 路由和稳定工具 collection 版本切换/回滚的真实验收。
- [ ] 使用生产候选知识完成定义、关系和多部分问题验收；确认只读组不含 row embeddings、写操作或管理工具，并为已保留的 `structured_query` 补充一个真实受治理结构化记录场景。
- [x] Copilot 模型对话框复用现有 capability 结果，并保留显式复测入口。
