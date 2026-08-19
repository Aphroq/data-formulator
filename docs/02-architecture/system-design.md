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
- `report`：v1 暂不记录。现有报告只保存在前端会话状态，没有可复用的后端持久化保存点；后续若补齐，只允许作为引用 chart artifact 的只读输出包装，不能成为 Recipe 执行步骤。

现有 HMAC `codeSignature` 用于验证代码未被篡改。Recipe 另外保存稳定 SHA-256，用于版本和可重复性比较。原有交互式 Web 分析为保持向后兼容，可以继续从当前 Flask `app.secret_key` 派生进程内签名；未显式配置 `FLASK_SECRET_KEY` 时，这类签名不保证跨重启有效，但不得因此让 `AUTOMATION_ENABLED=false` 的原有 `visualize` 路径失效。

Recipe 与后台执行使用更严格的边界：compile、dry run、publish、Recipe manual run 和 Worker 启动前都必须显式验证存在可跨进程复用的 `DF_CODE_SIGNING_SECRET` 或 `FLASK_SECRET_KEY`。Web 与 Worker 必须解析到同一份稳定材料；缺失时返回安全的 `SERVICE_UNAVAILABLE` 或拒绝启动，不得使用开发密钥、进程内随机 Flask secret，也不得把配置异常泄露给客户端。

Artifact 在成为 transform/chart 父节点前，必须重新读取当前物化表并比对完整 content hash 与 schema fingerprint。metadata 中的 `artifact_id` 只是定位加速器，不能替代完整性校验。

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

v1 的正常产品入口只编译固定 Recipe，不提供参数定义表单。`parameters` 与 `bindings` 继续保留为机器规范和 Executor 的安全边界，供受控编译路径扩展；Automation 不得自行创建、猜测或修改参数定义。

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

schema v4 已由 `data_formulator.automation.db.AutomationDatabase` 统一拥有；`RecipeRepository` 和 `AutomationRepository` 都通过它解析绝对路径、打开 WAL/foreign keys/`busy_timeout` 连接并执行 v1 → v2 → v3 → v4 顺序 migration。v3 引入 Schedule/Run，v4 为 Run 增加 `active_attempt_run_id` 与 `cleanup_attempt_run_id`。v2 原地升级、重复打开、事务回滚和未知未来版本失败关闭都有合同测试，任何 repository 都不得重新维护自己的 schema version 或 migration 分支。

Schedule v1 持久化规范化的五段 Cron 表达式和 IANA timezone；“每日”只是 UI 对 Cron 的受控简化。v1 Cron 只接受数值、列表、升序范围和步长，day-of-month/day-of-week 使用标准 union 语义；春季跳时中不存在的墙上分钟跳过，秋季回拨的重复墙上分钟只执行一次。`version_id` 创建后不可修改，切换 RecipeVersion 必须新建 Schedule。存在 enabled Schedule 时归档其 RecipeVersion 必须失败关闭，用户需先显式停用 Schedule；已绑定 archived version 的 Schedule 不允许重新启用。归档不删除不可变版本字节，归档前已经入队并固定该版本的 Run 仍可完成，避免管理动作静默改写既有执行计划。`next_run_at` 统一按 UTC 持久化，解析和展示时才使用 Schedule timezone；重新启用时从启用时刻之后重算，不补跑显式停用期间的周期。

持久化 Run 使用独立的队列状态，不复用 Recipe Core 的终态制品枚举。Run 至少保存明确 scope、固定 version、触发类型、`scheduled_for`、尝试次数、下一次可领取时间、lease owner/token/expiry、取消请求、内部 active/cleanup attempt id、最终安全错误和可校验 artifact reference。逻辑 `run_id` 与每次 Executor 尝试的 artifact run id 分开，避免崩溃恢复或重试与已有的不完整/不可变运行目录冲突；active/cleanup id 不进入公共 API。SQLite 不保存参数值、连接参数、凭据或绝对 artifact 路径；v1 Schedule 和持久化 manual Run 都只运行固定 Recipe/default binding。

当前 repository 已支持 Schedule 创建、查询、列表、编辑、启停和按 `(schedule_id, scheduled_for)` 幂等创建 queued Run；单次 Scheduler tick 会在一个 `BEGIN IMMEDIATE` 事务中完成到期扫描、最多一个停机补偿 Run 入队和 `next_run_at` 推进，任一 Schedule 计算失败时整批回滚。Run repository 已实现 scoped list/get、每次调用生成独立逻辑 Run 的持久化 manual enqueue、合法状态转换、claim/renew/fencing、运行中取消请求、最多 3 次总尝试、过期 lease 恢复和精确 attempt cleanup 门禁；`AutomationWorker.run_once()` 把恢复、清理、claim、明确 scope 打开、固定版本验证、确定性执行和终态写回接成闭环，`AutomationRuntime` 与 `data_formulator_worker` 则负责正式的常驻本机进程生命周期。

### Scheduler 与 Worker

- Scheduler 以可注入时钟执行单次 tick，扫描到期 Schedule，并在同一事务中创建 queued Run、推进 `next_run_at`。服务停机跨过多个周期时，每个 Schedule 最多合并为一个补偿 Run，再推进到严格晚于当前时刻的下一次，避免重启后无界补跑。
- Run repository 通过带随机 fencing token 的 lease 领取和续租 Run；Worker 在创建物理目录前以同一 fencing token 登记 active attempt id。过期恢复把 active id 原子移动为 cleanup id，带 cleanup id 的 queued Run 不能重领。Worker 只打开该行声明的 identity/Workspace 并定点处置：无 manifest 目录先改名隔离、写 retired tombstone 后删除，目录尚不存在时也写 tombstone，因而旧进程不能迟到创建同一 id；已有 manifest 的 attempt 原样保留且不挂接到逻辑 Run。清理完成以 compare-and-set 清除同一 cleanup id，之后才允许下一次 claim。
- 旧 Worker 失去 token 后不得覆盖新尝试的完成状态。Worker 在开始、成功和失败步骤边界同步续租并检查取消，每个已领取 attempt 另有定时 heartbeat 覆盖同步长步骤；即使 heartbeat 已观察到取消，也继续续租到 Executor 到达下一个安全边界。步骤期间观察到 heartbeat/fencing 失败时 Executor 不写终态 manifest；任何 heartbeat 失败、续租异常或无法安全停止都禁止旧 Worker 写逻辑 Run 终态。若失败发生在 Executor 已原子完成 artifact 之后，该 artifact 可能成为保留的未引用 attempt，但不能被误接为新尝试结果。
- `AutomationRuntime` 每个周期严格按 `Scheduler.tick()` → `Worker.run_once()` 执行，当前并发固定为 1；未来若开放显式并发配置，上限仍为 2，并且必须先补同 Workspace 写入竞争验证。
- `data_formulator_worker` 是 wheel 中的正式 console script。默认常驻，也支持 `--once` 做一个确定性运维周期；默认 poll/lease/heartbeat 分别为 1/30/10 秒，heartbeat 必须短于 lease。常驻循环只对白名单 SQLite locked/busy 延后重试，其他意外错误让进程安全退出。
- Worker CLI 与 Web 加载同一组仓库/包内 `.env`，但仍要求进程启动前解析到相同的绝对 `DATA_FORMULATOR_HOME`。它在任何数据库、Workspace 或 connector 初始化前验证 feature flag、稳定签名和 `WORKSPACE_BACKEND=local`；配置错误只输出固定安全信息。SIGINT/SIGTERM 只请求优雅停止，当前同步 Run 完成前 heartbeat 继续工作。
- Repository 只接受调用方给出的显式 retryable 决定并强制最多 2 次重试；Worker 只把现有 connector classifier 标记 `retry=true` 的网络/超时失败和明确识别的 SQLite locked/busy 映射为 retryable。schema drift、签名、scope、参数、代码和输出校验错误永不重试；connector 原始异常和 classifier detail 不进入 Run 行或 artifact。
- queued Run 可直接取消；running Run 记录取消请求，Worker 在步骤边界响应。终态不可重新打开。
- Worker 在 claim 前检查 `AUTOMATION_ENABLED` 和稳定签名配置，使用 request-independent opener 打开明确 identity/workspace，不伪造 Flask 请求；Runtime factory 从一个解析后的 `DATA_FORMULATOR_HOME` 同时构造 Scheduler repository、Worker repository 和 Workspace opener，并拒绝 repository 数据库路径不一致。Web/桌面应用当前不负责拉起或监督 Worker 进程。

队列 Run 状态：

```text
queued | running | succeeded | failed | needs_review | cancelled
```

允许的状态迁移只有：`queued → running / cancelled`，`running → succeeded / failed / needs_review / cancelled`，以及 retryable failure 或过期 lease 下受尝试上限约束的 `running → queued`。Recipe Run artifact 只记录 `succeeded / failed / needs_review / cancelled` 等终态，不承载 queued/running。

## 持久化边界

Recipe spec、代码、Workflow Markdown、Run events 和 manifest 必须进入 durable artifact store，不能写入 `confined_scratch`。

Recipe 和 Run 的所有持久化路径都通过现有 `ConfinedDir` 解析；不在各模块重复实现 `resolve()`、父目录判断或 symlink 防护。

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

这些 API 已在 `1f5f181d` 落地。`AUTOMATION_ENABLED=false` 时在存储初始化前失败关闭；所有资源访问都由当前 identity 和 durable local Workspace 限定。Schedule 首次排期、重新启用排期和 manual Run 时间由服务端计算，写请求严格拒绝客户端提供的 `next_run_at`、`scheduled_for`、参数、凭据或 Run id。创建 Schedule、启用 Schedule 和 manual enqueue 要求稳定代码签名及 Published RecipeVersion 的完整 default binding；读取、停用和取消不会被不必要地扩大为签名写入边界。Run 公共表示不返回 lease owner、fencing token 或 lease expiry。manifest/events 端点从逻辑 Run 解析 attempt reference，并在返回内容前校验 Workspace scope、安全相对路径、manifest hash、descriptor 和全部文件 hash；活动 Run 或损坏制品失败关闭。

三个新增产品触点：

1. Data Thread 中统一的 Artifact action：`Save as Recipe`。
2. 单一 `/automation` 页面中的 Recipes 区域：版本、输入、步骤、dry run、发布、持久化手动入队，以及 dry run 的本次结果摘要。
3. 同一页面中的 Schedule 与 Runs Inbox 区域：调度设置、状态、Needs Review、错误、日志和输出链接。

M3-D 页面已经实现每日时间到规范化 Cron 的受控转换、原始 Cron/IANA timezone 编辑、固定版本 Schedule 启停，以及按状态筛选的持久化 Runs Inbox。queued/running Run 可请求取消；有最终制品的 Run 可查看已校验的 manifest/events；Needs Review 可返回产生该 Run 的不可变 RecipeVersion。Workspace 或版本快速切换时，旧请求结果不会覆盖新作用域。

最终导航只保留现有工作区 rail 上的 `Automation` 入口；`/recipes` 仅作为保留 query/hash 的兼容重定向。不要恢复独立 Recipes 导航，不新增“应用 → 自动化”包装层，也不改变原有项目/Workspace 概念。Recipe Core 提供的生命周期视图在 M3 中被纳入该统一页面，但仍不负责 Schedule repository、Worker 或持久化 Run 历史。

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
    models.py
    repository.py
    scheduler.py
    worker.py
    cli.py
  routes/
    recipes.py
    schedules.py
    runs.py

src/
  app/recipeApi.ts
  app/automationApi.ts
  components/ArtifactActionsMenu.tsx
  views/Recipes.tsx
  views/RunsInbox.tsx
```

这是职责边界，不要求预先创建全部空文件。每个文件应随契约或测试一起出现。
