# 系统设计

## 设计目标

在不改变 Data Formulator 核心交互模型的前提下，增加可信上下文、确定性 Recipe 和轻量后台运行。

系统只保留一个 `AnalystAgent`。TrustGraph 是只读 Skill，GitHub Copilot 是 LiteLLM provider；两者只参与交互分析，不进入正常 Recipe Run。

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
  ├─ TrustGraph Skill（只读、带引用）
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

### TrustGraph 业务上下文

业务上下文作为现有 AnalystAgent 的可选 Skill。Skill 使用通用 `BusinessContextProvider`，第一版包含本地知识和 TrustGraph 两个实现。

TrustGraph 配置至少包含：

- API base URL。
- flow id。
- collection。
- credential reference。
- Data Formulator workspace 到允许目标的显式映射。
- connect/read/total timeout。
- 最大文本长度和最大来源数量。

Graph RAG 是 flow-scoped，真实 TrustGraph workspace 由 bearer token 决定，不能只靠请求体中的 collection 或 Data Formulator workspace id 实现租户隔离。

响应适配器统一处理：

- `end_of_stream` 与示例中可能出现的 `end-of-stream`。
- 最终消息中的 `sources`。
- `uri` 必填、`title` 可空。
- 来源去重、数量限制、超时和不可用告警。

外部上下文始终作为不可信数据处理：限制大小、标注来源，不能覆盖系统指令。

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

当前代码没有独立通用 Sidebar；路由和导航修改落在真实的 `src/app/App.tsx` 等现有入口。

## Feature flags 与安全

独立且默认关闭：

- `TRUSTGRAPH_ENABLED=false`
- `GITHUB_COPILOT_ENABLED=false`
- `AUTOMATION_ENABLED=false`

Automation 关闭时不启动 Scheduler/Worker，API 和 UI 都不可用。

安全要求：

- Secret 只保存引用或进入现有 credential vault。
- TrustGraph base URL 使用 allowlist/SSRF 防护和 TLS 校验。
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
