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
  → 服务端绑定的 TrustGraph Flow + collection + 只读 Agent 工具组
  → TrustGraph 原生 Agent 按需多轮调用 knowledge-query / structured-query
  → 最终业务上下文答案 + 真实检索轨迹标识
  → AnalystAgent 结合本地数据继续执行或请求澄清
```

Data Formulator 发给外部提供者的载荷保持简单：

- `question`：一个可独立回答的聚焦业务问题，例如某个状态、分类、口径、映射、单位、时间边界或关系应如何解释；
- `context`（可选）：只包含该答案会影响的当前操作、相关数据源或表在任务中的角色、字段名和类型、少量非敏感代表值或脱敏后的值模式，以及用户已经明确的约束。

不发送整表、无关行、原始敏感值、完整聊天历史、代码、文件路径、identity、Data Formulator workspace id、目标 URL、Flow、collection、工具组或凭据。外层模型不负责选择 TrustGraph 内部查询策略，也不生成 SPARQL/GraphQL；一次高层调用通常应由 TrustGraph Agent 自行完成必要的多轮检索。只有出现另一个独立的语义缺口，或返回明确指出缺少某项上下文时，外层才再次调用。

TrustGraph 目标由服务端把 Data Formulator workspace 显式映射到 HTTPS API base、Flow、collection、单个只读 Agent 工具组、TrustGraph workspace、credential reference、超时和响应大小上限。模型和前端不能覆盖这些值。生产工具组只配置需要的只读 `knowledge-query`、`structured-query`；不配置 row embeddings/行级语义匹配、通用文本补全、写操作、摄取或管理工具。

服务器工具合同使用稳定名称 `knowledge_query` 和 `structured_query`。Data Formulator 的固定任务帧只负责告诉原生 Agent：业务定义、编码、分类、状态、范围、单位、时间边界、规则或关系优先使用 `knowledge_query`；只有确需受治理的结构化记录事实时才使用 `structured_query`；只能调用本轮明确列出的工具，不能发明通用 `search`/`browse`。若第一次 observation 未覆盖多部分问题的实质缺口，原生 Agent 可缩窄问题继续调用，外层不复制这套循环。

TrustGraph 的 ontology 配置是给摄取流程使用的规则，用来约束可抽取的类型、属性和关系；`knowledge_query` 搜索的则是目标 collection 中已经导入的知识。需要在分析和清洗中自动核对的类定义、属性、domain/range 和业务关系，应由部署方连同来源实际导入同一 collection，并建立可检索的图实体上下文；随后统一由 `knowledge_query`/GraphRAG 检索。Data Formulator 不直读 ontology 配置，也不为此增加 SPARQL 或 triples 产品工具。

产品内部继续使用锁定的官方 Python SDK，调用原生 `service/agent`；因为 `2.8.14` 的 REST 高层方法没有暴露 collection 和 session id，适配器只在同一官方 `FlowInstance.request()` 上补齐这两个服务器控制字段，不实现自己的搜索、查询规划或 Agent loop。该版本 HTTP gateway 实际返回终态 `AgentResponse`（`message_type=answer`、`content`、两个完成标志），而同步 SDK 文档仍描述聚合 `answer`；适配器只在协议边界兼容这两种官方形状，并严格拒绝 thought、observation 和未完成的 answer chunk。MCP 只作为独立外部互操作入口；锁定镜像的出站 `mcp-tool` 与其 MCP 客户端签名不兼容，内部 Agent 不依赖该路径。

TrustGraph 返回内容按不可信证据处理。Data Formulator 只消费最终答案，不回传或展示 TrustGraph 的隐藏思考链。每次请求由 Data Formulator 生成 session id，并用官方 Agent provenance URI 形成真实轨迹引用；只有 TrustGraph 官方响应明确给出的文档来源才作为文档 citation，禁止递归收集任意 RDF/RDFS/实体 IRI 冒充来源。若无答案、认证失败、超时、服务错误或协议漂移，查询失败关闭；若答案本身说明证据不足，`AnalystAgent` 不得据此执行会改变语义的数据操作。

TrustGraph 自身 LLM 配置与 Data Formulator LiteLLM 配置相互独立。当前部署使用 OpenAI-compatible Qwen variant，把模型设为 `Qwen/Qwen3.5-27B`，`thinking=off`；API token 和 base URL只存在 TrustGraph 部署环境。官方 `trustgraph-ui` 继续承担工具组、collection、摄取、Context Core、Ontology/SPARQL/GraphQL 和完整图谱管理，Data Formulator 不复制这些页面。

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
