# Analysis Integrations 工程记录

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 分支 | `feat/analysis-integrations` |
| Worktree | `D:\projects\dfm-wt-analysis` |
| 本机实例 | `analysis`：后端 5568、Vite 5174、数据目录 `D:\projects\dfm-runtime\analysis` |
| 基线 | 共享文档提交，父提交为 Data Formulator `5477f0e` |
| 当前阶段 | A0-A9 已完成并提交为 `acdfb3c5`；A11 空环境六工具冒烟已完成，真实业务 ontology、rows schema 和实体数据验收待部署方提供；行语义搜索、A10 知识准备和 Data Formulator 内 TrustGraph UI 均已取消 |

## 目标

在现有 `AnalystAgent` 和 Data Formulator 数据工作区中增加可发现、可查询的 TrustGraph 本体/RDF 知识图谱能力和可选 Copilot 模型，不创建第二个 Agent runtime。

## 范围

- 通用结果、结构化引用和稳定错误契约。
- TrustGraph Flow/collection/document/processing/Knowledge Core 目录。
- TrustGraph 图实体语义检索、本体、knowledge/provenance 三元组与只读 SPARQL Skill。
- TrustGraph GraphQL rows 只读查询；不导入 Data Formulator 表，不写 Workspace，不做同步。
- TrustGraph 管理和完整可视化复用官方 `trustgraph-ui`；Data Formulator 不实现行语义搜索、文档摄取或 Context Core 写操作。
- `SkillContext` identity/workspace 与 `ToolResult` citation 契约。
- Citation 在 Data Thread 中的持久化展示。
- LiteLLM Copilot `oauth_device`、provider 解析和能力探测。
- `TRUSTGRAPH_ENABLED`、`GITHUB_COPILOT_ENABLED`。

不包含 Recipe、Schedule、Run 或 Worker。

详细契约、切片、测试矩阵与停止线见 [Analysis Integrations 实施方案](implementation-plan.md)。

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
12. **A11 真实业务验收与 MCP 兼容（进行中）**：TrustGraph UI 独立使用，不改 Data Formulator 前端；空环境非破坏性冒烟已完成，真实业务 collection 的结果语义仍待验收。MCP 仍仅作可选外部兼容。

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

## 已确认决策

- TrustGraph 是 Skill，不是 Agent。
- Copilot 继续经过 LiteLLM，不接 Copilot SDK。
- Copilot M0-B 以目标 Linux Node/npm 环境中的官方 CLI/SDK 真实账号请求和产品自身 device flow → Vault → LiteLLM 链路为证；Linux 前端测试与构建只属于 A7 普通回归。
- 引用通道是通用 Skill 契约，不在 Agent 中硬编码 TrustGraph。
- Skill 授权上下文只能由已认证路由注入，并与自由 payload 分离；迁移期无授权的本地 Skill 仍兼容，需要外部服务的 Skill 必须失败关闭。
- 引用 URI 只接受 `http`、`https` 和 `urn`，Agent router 再校验、按 URI 去重并限制每个工具事件最多 50 项；Reasoning log 只记录数量和 provider。
- `ToolResult.public_summary` 是外部工具正文的可选安全替代，只用于前端工具事件和运维摘要，完整正文仍只作为模型观察。
- Skill frontmatter 的通用 `enabled_if` 是后端 availability 门；flag 关闭时对应 Skill 不进入 registry，Python 模块也不导入。
- TrustGraph 使用 `TRUSTGRAPH_TARGETS_JSON` 将 Data Formulator workspace 精确映射到非 secret 目标；`credential_ref` 必须在独立 `trustgraph:` namespace 中，并通过现有 identity-scoped vault 解析 `bearer_token`。
- 浏览器需要接收可恢复 trajectory 时，带 `public_summary` 的工具正文会被替换为摘要；模型当前内存中的完整观察不变，恢复后可按需重新查询。
- 前端引用字段只做可选增量，不提升 Session schema 版本；旧 Session 缺字段时保持原对象形状和 UI，现有自动保存、恢复以及 ZIP 导出/导入会原样保留结构化引用。
- 来源在前端再次规范化、按 URI 去重并限制 50 项；只有无 userinfo 的 HTTP(S) 生成 `target="_blank"`、`rel="noopener noreferrer"` 链接，URN 保留为不可点击标识。
- 外部上下文作为不可信数据处理。
- capability probe 至少覆盖 chat、streaming 和 tools。
- TrustGraph 产品内部查询主通道固定使用官方 `trustgraph-base==2.8.14`；只接入目录、graph embeddings、ontology/triples/SPARQL 和显式 GraphQL rows。不接 `row_embeddings_query()`、Library 写操作或 Knowledge/Context Core 写操作，不调用 Graph RAG，也不让 TrustGraph 生成自然语言答案。
- TrustGraph UI 不进入 Data Formulator：官方 `trustgraph-ui`/`@trustgraph/trustkit` 已覆盖图谱浏览、Ontology、SPARQL、GraphQL 和摄取工作流。`trustkit@2.0.3` 已发布但要求 React 19，Data Formulator React 18 不直接嵌入、不升级；完整 UI 独立使用。
- 官方 MCP server 暴露了大量查询和管理工具，但产品后端不再叠加 MCP 客户端；MCP 只作为外部自动化兼容面。`2.8.14` 生成部署中 MCP 默认 gateway 端口与实际 API Gateway 存在 `8888/8088` 差异，启用时必须显式校正并单独验收。
- 图实体语义检索复用官方 embedding 与 graph-embeddings 服务；由于 SDK `2.8.14` 同步 `graph_embeddings_query()` 对 `embeddings()` 返回形状处理错误，实现只用同一官方 `FlowInstance.request()` 拆成两次官方服务调用，不实现自有 embedding 或向量检索。
- A9 只调用官方 `rows_query()` 执行显式 GraphQL；不调用会把自然语言转为 GraphQL 的 `structured_query()`/`nlp_query()`，不创建 Data Formulator 表，不写 Workspace，也不实现同步或刷新。
- `trustgraph-base` 高层 triples 方法缺少 named graph 参数，所以仅 triples 使用官方 `FlowInstance.request()` 补 `g`；SPARQL 直接使用高层 SDK。真实 `2.8.14` 部署验证 `service/sparql` 可用而在线 REST 的 `service/sparql-query` 返回 404，不实现双路径猜测 fallback。
- TrustGraph 请求体中的 `workspace` 只用于路由，bearer token 仍是目标 workspace 的授权边界；Data Formulator workspace 必须先经过服务端允许目标映射，不能由前端直接指定 flow、collection、ontology 或 token。
- 本体、RDF 结果和 SPARQL binding 都是不可信证据；SPARQL 仅允许 `SELECT`/`ASK`/`CONSTRUCT`/`DESCRIBE`，本地解析并拒绝更新与 `SERVICE`。
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
- capability cache 是有上限的 identity/model 进程内布尔结果，不保存 token、prompt 或原始错误；连接完成、断开或凭据缺失会按 identity 清除。普通请求与 UI 都要求当前 identity 已通过 buffered chat、streaming 和 streamed tool-call 三项探针，不能通过手工 payload 绕过。
- `TRUSTGRAPH_ENABLED` 不能只隐藏前端：关闭时 Skill 不得进入可调用工具集合。`GITHUB_COPILOT_ENABLED` 关闭时模型注册表不得发现或实例化 Copilot endpoint。
- GitHub 官方 npm CLI/SDK 仅用于仓库外真实账号探针；产品仍通过锁定的 LiteLLM provider 和现有 `AnalystAgent`，不把 SDK 引入运行时或仓库依赖。

## 未决与风险

- LiteLLM Copilot provider 使用 `copilot_internal/v2/token`、固定 IDE 标识头和内部 Authenticator 扩展点；应用适配层必须有锁定版本的合同测试，并在 LiteLLM 版本不匹配时失败关闭。
- Copilot 真实 device flow、chat、streaming、tools、短期 token 缓存和刷新窗口内重新交换已验证；长期 GitHub OAuth token 的自然过期、账号侧 revoke 和重新连接仍需后续生命周期验证，不能破坏性模拟为已完成。
- 官方 SDK 返回的当前账号模型目录与 LiteLLM `1.91.3` 静态目录存在版本漂移；本分支只允许显式候选且以三项实测准入，新增模型需先升级并重新审计 LiteLLM 合同，不能把 SDK 变成第二条产品模型路径。
- 本机官方 Copilot CLI 的内置 `login --device-code` 网络运行时未能访问 GitHub device endpoint，但同端点经 curl、Node、Python 和 Data Formulator device flow 均返回成功；CLI 使用本次 OAuth token 的进程级环境注入后真实调用通过，因此该问题记录为本机 CLI 登录兼容性，不影响产品路径。
- TrustGraph 真实 bearer、workspace、Flow、项目 HTTPS 错误边界、bound ontology、knowledge/provenance graph 与只读 SPARQL 已验证；当前默认图的三元组端点为空而 SPARQL 有数据，说明真实业务 collection/graph 绑定仍需部署时按数据语义确认，不能在产品中猜测切换。
- TrustGraph 官方 `2.8` 本地服务位于仓库外专用 WSL2 环境，只是用户明确授权的外部验收实验室；它不改变仓库默认的无容器开发方案，不新增镜像、Compose 配置或产品运行依赖，也不作为普通回归的前置条件。模型路径只使用 OpenAI 兼容接口，不引入 Ollama。
- A3 已完成通用引用绑定、持久化和安全展示；TrustGraph 结构化结果会从合法 URI 产生 provider-neutral `ContextItem`，真实图中的引用覆盖度仍需外部数据验证。
- 上游 `dev` 已改动 `src/components/ComponentType.tsx`、Redux 和 `App.tsx`，但远端 `main` 仍停在固定基线；本分支不合并移动的 `dev`，未来升级时需单独处理引用类型冲突。
- Vite `7.3.3` 要求 Node `^20.19.0 || >=22.12.0`；本机默认 Node `20.15.1` 不满足要求，历史门禁使用隔离的 Linux Node `22.14.0`，本次分支收口使用 Codex 内置 Node `24.19.0`。
- TrustGraph A8/A9 需要真实业务 collection 才能做最终语义验收；离线合同先用 SDK 替身锁定请求与响应，不能把空默认图误报成产品能力完成。
- TrustGraph rows service 在 workspace 未装载 GraphQL schema 时以 HTTP 200 返回 `rows-query-error`；该特定官方状态映射为 `not_configured`，而不是服务故障。其他 rows service 错误不做宽泛猜测。

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
- [ ] A11 只保留真实业务知识数据端到端验收与按需 MCP 外部兼容说明，不修改 Data Formulator 前端。
