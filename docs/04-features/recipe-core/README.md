# Recipe Core 工程记录

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 分支 | `feat/recipe-core` |
| Worktree | `D:\projects\dfm-wt-recipe` |
| 本机实例 | `recipe`：后端 5569、Vite 5175、数据目录 `D:\projects\dfm-runtime\recipe` |
| 基线 | 共享文档提交，父提交为 Data Formulator `5477f0e` |
| 当前阶段 | M2-D 合并前最小收口已实现并提交；Recipe Core 功能范围和分支级验证已关闭，待合并审查 |

## 目标

从真实后端 Artifact Lineage 编译不可变 RecipeVersion，并支持 dry run、发布和手动确定性运行。

## 范围

- ArtifactNode 模型、ledger 和 load/transform/chart 记录点。
- canonical JSON、SHA-256、RecipeSpec v1 和稳定 Compiler。
- typed parameter binding 与输入可刷新性。
- durable artifact store。
- request-independent workspace opener。
- Recipe repository、dry run、publish 和 manual run。
- Save as Recipe 与 Recipes 页面。

不包含 Scheduler、lease Worker 和 Runs Inbox。

v1 也不增加 report 记录点或通用参数编辑器：现有报告缺少后端持久化保存点，正常 Save as Recipe 先生成固定 Recipe。底层保留 `ArtifactType.REPORT` 与 typed binding 契约，但未实现的能力不得在 UI 或完成状态中冒充可用。

## 实施顺序

1. M0-A：定义 canonical JSON、ArtifactNode、scope 和本地 durable ledger 的最小契约，先覆盖不可变、幂等、篡改和跨 workspace 拒绝测试。
2. M0-B：在 `DataOperationExecutor` 成功写表后记录 `load` 节点；节点复制完整选定 step，不依赖 scratch 中的 DataOperation 或前端摘要。
3. M0-C：让 `visualize` 的声明输入成为后端校验契约，在 Sandbox 成功、代码签名完成后原子记录 `transform` 与 `chart` 节点，并把 artifact id 随结果事件返回。
4. M0-D：用数据库 loader 测试替身完成 load → transform → chart → 向上遍历 → 稳定编译探针；有现成外部数据库时再补真实端点验证，不启动容器。
5. M2-A：实现 RecipeSpec v1、typed binding、Compiler、稳定拓扑排序和失败关闭规则。
6. M2-B：补 durable recipe artifact store、request-independent workspace/connector opener、dry run、发布和 manual run。
7. M2-C：最后注册最小 API、Save as Recipe 和 Recipes 页面，避免过早修改 `app.py`、`App.tsx` 和 Redux 冲突热点。
8. M2-D：只关闭签名/血缘/路径完整性、请求边界和现有 Recipes 页面可靠性，不引入 Automation Workbench 范围。

单元契约不等待共享启动脚本；并行交互验证前，先从 `main` 集成 `DF_INSTANCE_ID` Cookie 命名和固定实例启动入口。

## 当前源码核对

2026-08-18 对固定基线 `5477f0e2` 和共享准备提交 `b08069bc` 的核对结论：

| 链路 | 当前事实 | 对 M0 的直接影响 |
| --- | --- | --- |
| Load | `DataOperationPlan` 已有 canonical SHA-256；执行成功后只把 operation id、plan hash、step index、source id 和 table key 写入 `workspace.yaml`。完整 DataOperation 位于可淘汰的 `scratch/data_operations` | load artifact 必须在成功写表后复制完整选定 step；Compiler 不能回读 scratch 补全 |
| 表指纹 | Workspace 的 `content_hash` 是抽样数据的 MD5，Arrow 与 DataFrame 还有两套实现 | 可继续用于交互刷新去重，但不能直接冒充 Artifact/Recipe 完整性 hash；M0 另定义带算法标识的 SHA-256 和独立 schema fingerprint |
| Transform | Analyst `visualize` 成功后写入 parquet，但没有 `source_info`；父表主要由前端根据 action 的 `input_tables` 解析。`Derivation` 类型已定义但当前没有持久化调用点 | 后端必须校验声明父表并记录其 artifact id；缺失父 artifact 时保留交互结果但禁止编译/发布 |
| Chart | 后端生成 chart id 并在当次 run 内保存 spec，前端随后转换为 `Chart` 并随 Redux session 保存 | 初始 M0 只覆盖后端 `visualize` 产生的 chart；手工新建或编辑 chart 在发布前需要独立的后端持久化入口 |
| Workspace | `get_workspace()` 从 Flask 请求头读取 workspace id；local Workspace 持久化，ephemeral 会淘汰，Azure 的 `confined_root` 实际指向本地 scratch | 首版 ledger 明确只支持 local durable Workspace；ephemeral/Azure 失败关闭，Azure 等正式 artifact API 后再接入 |
| Connector | `resolve_live_loader()` 从当前 Flask identity 解析连接和凭据 | manual/background executor 不能复用该请求路径；需要显式 `identity_id + source_id` opener，且只允许可恢复凭据的输入进入 published Recipe |

## 本机验证基线

- Recipe Worktree 已建立独立 `.venv` 与 `node_modules`；Yarn 下载缓存使用 `D:\projects\dfm-runtime\recipe\yarn-cache`，避免 Windows 全局缓存锁争用。
- 系统 Node `20.15.1` 低于 Vite 7.3.3 的最低要求；验证使用工作区运行时 Node `24.19.0`。后续固定启动入口必须显式选择兼容 Node，不能靠当前系统 PATH。
- 已提交基线：Recipe 82 passed；全量后端 2220 passed、13 skipped、1 xfailed、1 deselected；前端 48 files、396 tests passed；Vite 生产构建成功。
- 2026-08-18 M2-D 聚焦验证：Recipe、签名和 Agent 血缘后端 116 passed、2 skipped；Recipes 页面 4 passed；Recipes ESLint 通过。最终全量后端 2239 passed、16 skipped、1 xfailed；前端全量 48 files / 399 tests passed，生产构建成功。后端按 `PYTHONUTF8=1` 和兼容终端环境执行；本机无 Windows 符号链接权限的测试准备按同类用例显式 skip，不把权限不足误报为产品失败。
- 系统 Node `20.15.1` 仍低于 Vite 7.3.3 的最低要求，验证继续使用工作区运行时 Node `24.19.0`；不在 Recipe Core 内另造工具链管理器。

## M0 首个开发节点（已完成）

首个提交只落最小后端契约，不注册路由或 UI：

1. 新增 `tests/backend/recipes/`，先写 canonical hash、ArtifactNode、ledger 幂等/冲突、缺失父节点和 scope 隔离失败测试。
2. 新增 `py-src/data_formulator/recipes/` 中与上述测试一一对应的模型与 repository；存储使用 workspace 内 durable `artifacts/`，禁止写入 `confined_scratch`。
3. 为 Workspace 暴露明确的只读 identity/workspace/backend capability，不从目录名反推授权上下文。
4. 聚焦验证通过后再接 `DataOperationExecutor`，避免一开始同时改 Agent、路由和前端。

该节点完成标准：相同规范得到相同 hash；同一 origin 重试幂等；同 id 不同内容、跨 identity/workspace、缺失父节点、非持久化 Workspace 全部失败关闭。

实施结果：

- canonical 层直接使用标准库 `json` 与 `hashlib`，只接受具备明确 JSON wire form 的值，不引入额外序列化依赖。
- `ArtifactNode` 使用 frozen dataclass、显式 `sha256:` digest、深层只读 execution payload，并在反序列化时重新计算 `artifact_id` 拒绝篡改。
- ledger 复用现有跨平台 `WorkspaceLock`，沿用仓库已有的临时文件 + `os.replace` 原子写入方式；批量记录、并发记录、origin 冲突和父节点校验都在持锁后从磁盘重读，避免 lost update。
- Workspace 现在显式暴露 identity、workspace id 与 storage capability；首版只允许 durable local backend 写 `artifacts/lineage/lineage.json`，ephemeral 与尚无正式 artifact API 的 Azure 均失败关闭。
- M0-A 聚焦测试 30 passed；相关 Workspace 回归 77 passed；全量后端 2160 passed、13 skipped、1 xfailed、1 deselected。deselect 仍是 Windows 当前终端没有 symlink 创建权限的既有测试。

## M0-B Load 记录点（已完成）

- `DataOperationExecutor` 只在 parquet 成功落盘后创建 `load` Artifact，origin 固定为 operation + plan hash + step index。
- Artifact execution payload 复制完整 `ConnectorQueryStep`、plan hash 和 materialized output，不需要回读可淘汰的 `scratch/data_operations`。
- content hash 对实际 parquet 文件做分块全量 SHA-256；schema fingerprint 直接使用 PyArrow 已持久化 schema 的序列化 bytes，未复用 workspace 中的抽样 MD5。
- `workspace.yaml` 的 data-operation provenance 同步保存完整 step 与 artifact id；进程若在写表后、写 lineage 前失败，重试会从已发布表补记 Artifact，不重新查询 connector。
- 同一 origin 对应的 parquet 内容或 step 快照被改写时，重试返回 `artifact_lineage_error`，不会把变化后的内容静默绑定到旧血缘。
- ephemeral 与尚无正式 artifact API 的 backend 继续允许交互式 load，但不创建 durable Artifact，因此后续 Compiler/Publish 会按缺失血缘失败关闭。
- M0-B 聚焦链路 63 passed；全量后端 2165 passed、13 skipped、1 xfailed、1 deselected。

## M0-C Transform / Chart 记录点（已完成）

- `visualize.input_tables` 现在是工具 schema 必填字段；CoreSkill 与 Analyst runtime 都校验列表非空、唯一且表真实存在，失败时不进入 sandbox。
- sandbox 成功写出 derived parquet 后，CoreSkill 先对最终（可能已自动补 output variable 的）代码做 HMAC 签名，再调用 lineage recorder。
- recorder 从每个声明输入的 workspace metadata/ledger 解析父 Artifact，并在接受 metadata link 或 ledger fallback 前重算父表 parquet content hash 与 Arrow schema fingerprint；对 derived 表实际 parquet 和持久化 Arrow schema 生成 transform hash，再以完整 chart spec 生成 chart hash。
- transform 与 chart 先全部构造、校验签名，再通过 `record_many` 一次持锁原子提交；chart 的唯一父节点是本次 transform，transform 的父节点顺序与声明输入一致。
- 成功结果事件与 same-run chart registry 都携带 `transform_artifact_id` / `chart_artifact_id`。缺失父 Artifact、非 durable backend 或持久化失败时仍返回交互图表，但标记 `lineage.status=unavailable`，因此不能进入 Compiler/Publish。
- derived table metadata 保存通用 `artifact_id` 和 visualize binding；metadata 链接失败时 ledger 仍是事实来源，后续父解析可按唯一 output table 回查。
- 使用 loader 替身的真实纵向切片已覆盖 load → sandbox transform → signed code → chart 三节点及父链；M0-C 聚焦 Recipe/Agent 测试 53 passed，agent/route 相关回归 781 passed，全量后端 2176 passed、13 skipped、1 xfailed、1 deselected。

## M0-D / M2-A 稳定 Compiler（已完成）

- ledger 新增从一个或多个目标 Artifact 向上收集祖先的稳定 Kahn 拓扑遍历；可达根和同层节点以 Artifact id 排序，因此不受目标顺序或 ledger JSON 中节点顺序影响。
- `RecipeSpec` v1 使用 frozen dataclass 和既有 canonical JSON/SHA-256 原语，包含 scope、目标、显式依赖、load 输入模式、credential reference、typed parameters/bindings、每步执行快照与 hash/schema、最终输出和 compiler version；反序列化会重算 step/recipe hash 并拒绝未知字段或类型强制转换。
- Compiler 复用既有 `ConnectorQueryStep` 解析 load 快照；重新读取实际 parquet 与 Arrow schema，校验 transform HMAC、声明父表和 chart 父表/content hash，缺失、篡改、schema 变化或 v1 不支持的 Artifact 类型全部失败关闭。
- 相同目标集生成字节级一致的 Recipe JSON、`recipe_hash`、`version_id` 和 Workflow Markdown；Markdown 只由机器规范派生，不参与执行。
- 首批参数 slot 只开放 load filter value 与正整数 limit。绑定先按 `string`、`integer`、`number`、`boolean`、`date`、`datetime` 校验，再修改已验证的 JSON 结构；不做 Python/SQL 字符串替换。新增 slot 必须显式扩展 enum 和结构校验。
- 当前产品编译入口不接收参数定义，因此 Save as Recipe 生成固定 Recipe；M2-D 不增加参数编辑 UI。底层 slot/binding 继续保留并接受契约测试，供后续受控入口复用。
- `refreshable` 当前只表示 Artifact 中有稳定 `source_id` 和逻辑 credential reference；它不证明后台能够恢复凭据。M2-B 必须由 request-independent opener 验证连接并完成 dry run，才可进入 `validated` 或 `published`。
- 使用数据库 loader 替身的纵向测试现已覆盖 load → sandbox transform → signed code → chart → ancestry → 两次稳定编译；Recipe 聚焦 49 passed，Agent/路由回归 714 passed，全量后端 2187 passed、13 skipped、1 xfailed、1 deselected；前端 391 passed，生产构建成功。

## M2-B 持久化与确定性执行计划（后端核心已完成）

### 事实来源边界

- `DATA_FORMULATOR_HOME/automation/automation.db` 是 Recipe 目录和生命周期状态的事实来源。Recipe Core 先创建 `recipes` / `recipe_versions` 及顺序 migration；Automation Workbench 从该基础继续增加 `schedules` / `runs`，不建立第二个数据库或第二套 Recipe catalog。
- Workspace 的 `artifacts/recipes/` 是不可变内容的事实来源，保存 canonical `recipe.json`、派生 `workflow.md` 和逐文件 SHA-256 manifest。SQLite 只保存 scope、状态、hash 和相对 artifact 路径，不复制可执行 JSON 或代码。
- Workspace 的 `artifacts/recipe-runs/` 保存 dry run / manual run 的 `events.jsonl`、最终 `manifest.json` 和隔离执行 Workspace。正常 Run 不修改交互式 `data/` 表，也不向 lineage ledger 伪造新分析 Artifact。
- 持久化顺序固定为“先发布 content-addressed 文件目录，再提交 SQLite 引用”。进程若在两步之间退出，只会留下可安全回收的孤立不可变目录；绝不允许 SQLite 指向尚未完整发布的目录。

### Repository 与生命周期

1. `save_draft` 复核 identity/workspace、Recipe hash 和 artifact manifest，幂等插入 draft RecipeVersion；同 version id 的不同 bytes 或跨 scope 访问全部拒绝。
2. dry run 使用保存后的精确版本和绑定值执行；只有 succeeded、无 unresolved input、每步 schema/hash/signature 校验通过的证据才能把 `draft` 转为 `validated`。
3. `publish` 只接受 validated 版本，状态转为 `published` 后规范和验证引用不可修改；后续内容变化必须产生新 `version_id`。`archived` 是 published 的单向终态。
4. SQLite 连接统一启用 WAL、foreign keys、`busy_timeout` 和显式事务；所有读写查询同时带 identity、workspace 和 recipe/version id，不能只凭全局 id 授权。

M2-B1 实施结果：

- `RecipeArtifactStore` 在 `artifacts/recipes/<recipe>/versions/<version>/` 先写同目录临时目录，再以 `os.replace` 原子发布；重复保存会逐字节验证并幂等返回，同 version 的不同 Workflow 或损坏文件拒绝覆盖。
- manifest 固定记录 scope、Recipe hash 及 `recipe.json` / `workflow.md` 的完整 SHA-256 和长度；读取同时复核 SQLite 保存的 manifest hash、逐文件 hash、RecipeSpec 自校验 hash 和路径 scope，且拒绝 symlink 文件或越界路径。
- `RecipeRepository` 使用标准库 `sqlite3` 和顺序 migration v1，创建共享 `recipes` / `recipe_versions` 表；draft 保存先发布不可变目录、再用 `BEGIN IMMEDIATE` 提交引用，支持进程退出后幂等补偿。
- SQLite 不保存 `recipe_json`、代码或 Workflow；跨 identity/workspace 查询表现为 not found，跨 scope 写入和 DB/artifact 分歧失败关闭；旧版本的幂等重试不会回滚 Recipe catalog 的新名称/说明。Recipe + Workspace + vault 相关聚焦回归 120 passed。

### Request-independent opener

- Workspace opener 显式接收 `identity_id + workspace_id + backend config`；首版只允许 durable local，且要求目录已经存在，不执行 Web 路径的 lazy create。
- Connector opener 显式接收 `identity_id + source_id`，复用现有 `DataConnector`、用户 connector spec、credential vault 和 ambient/no-auth 恢复路径；后台路径不读取 request header、session、SSO request token，也不伪造 Flask context。
- 编译时的逻辑 credential reference 只有在 opener 实际恢复 loader 并完成连接/取数探针后才算 resolved；仅有 `source_id` 不能把版本提升为 validated。

M2-B2 实施结果：

- `LocalWorkspaceOpener` 固定 `data_home + identity_id + workspace_id`，只打开已存在且未通过 symlink 越界的 durable local Workspace；无 Web 路径的 lazy create，也不读取 `X-Workspace-Id`。
- Data Connector 初始化已拆成不注册 Flask blueprint 的 `initialize_data_connectors()` 和 Web `register_data_connectors()`；独立进程可从相同 admin 环境/YAML、用户 connector JSON 和 loader registry 恢复配置。
- `resolve_loader_for_identity()` 只解析显式 identity 可见的 admin/user connector。后台 opener 强制从 no-auth、vault 或 ambient 配置重新构造 loader，不把 Web 进程中的 session-only 内存缓存当成可恢复凭据，也不访问 request identity、TokenStore/SSO request token。
- 后台凭据探针失败只返回不可恢复，不主动删除 vault 中可能暂时失效的凭据；原 Web 自动重连仍保留既有的重试后清理语义。Connector + DataOperation + Recipe 聚焦回归 139 passed；全量后端 2201 passed、13 skipped、1 xfailed、1 deselected。

### 单一确定性 Executor

- dry run 与 manual run 共享一个 `RecipeExecutor`，差别只在 run kind 和成功后的 lifecycle 动作；Executor 只接受已持久化 `RecipeSpec` 与 typed-bound execution，不接受聊天、Redux 或任意代码覆盖。
- `load` 将保存的 `ConnectorQueryStep` 交给既有 `DataOperationExecutor` 和显式 loader resolver；`transform` 先校验 step hash 与 HMAC，再交给现有 Sandbox；`chart` 原样发布保存的规范，不重新调用 Agent。
- 每步在隔离 Run Workspace 中物化，记录实际 parquet SHA-256、schema fingerprint、耗时与状态。refreshable 数据允许 content hash 相对编译基线变化，但 schema drift、签名/step hash 不一致、输出缺失或 unresolved input 必须失败关闭；需要重新分析的 schema drift 返回 `needs_review`。
- 事件和错误不记录 credential、连接参数、数据行或原始外部异常文本；失败 manifest 只保存稳定 error code、异常类型和经清洗的用户消息。

M2-B3 实施结果：

- `RecipeRunArtifactStore` 为每次执行原子占用 `artifacts/recipe-runs/<run_id>/`，在隔离 `Workspace` 中物化表和 chart；最终以原子 `manifest.json` 作为完成标记，并逐文件记录 SHA-256 与长度。读取会复核 scope、run/RecipeVersion/binding hash、descriptor、事件序列和全部输出，新增、删除、替换或 symlink 篡改均失败关闭。
- `RecipeExecutor` 只编排 v1 的 `load`、`transform`、`chart`：load 复用 `DataOperationExecutor`，transform 复用 `LocalSandbox` 与 HMAC，chart 直接保存已校验 lineage 编译出的规范。交互 Workspace 不被修改；每步记录实际 content/schema hash 与耗时，schema drift 转为 `needs_review`。
- typed 参数只进入内存中的结构化绑定；run descriptor 和 SQLite 只保存 `binding_hash`。DataOperation 临时写入的 bound connector metadata 会在提交前清洗，外部异常也只映射成稳定错误，因此参数值、loader params、credential 和原始异常文本不会落入运行事件或 manifest。
- automation SQLite migration v2 补充 validation artifact path 与 binding hash；`draft → validated → published → archived` 为单向状态机。Repository 会重新打开不可变 Recipe 和成功 dry run，逐步核对 started/succeeded、schema 与输出 manifest，空成功 manifest、失败/needs-review run 或被篡改证据都不能发布。
- `RecipeService` 是 lifecycle-aware 入口：dry run 始终从 repository 重开保存版本，成功后固定 validation 证据；manual run 只接受 published 版本。两条路径共享同一 Executor，不调用 Agent、LLM、TrustGraph 或 Workflow Replay。
- Windows 下 Sandbox worker 会暂时把 Run Workspace 作为当前目录，因此运行目录不做完成时整体 rename；实现采用“锁内创建唯一目录 + 最终 manifest 同目录原子替换”的提交协议，避免依赖平台不支持的目录重命名语义。

## M2-C 最小 API 与 UI 计划（已实现）

### 接入边界与复用策略

1. API 只做现有 Compiler、Repository 和 `RecipeService` 的 workspace-scoped 适配，不复制状态机或执行逻辑；请求 identity 与 `X-Workspace-Id` 继续走现有认证和 Workspace factory。
2. 复用 Flask Blueprint、统一 `AppError/json_ok`、标准库 SQLite、既有 request-independent connector opener 和 `LocalSandbox`；不引入新 Web 框架、ORM、队列或表单状态库。
3. 前端复用 React Router、Redux 的现有 Workspace/server config selector、MUI、i18next 和统一 `apiRequest`。Recipe 目录状态只从后端读取，不再放入 Redux 或 session state 建立第二事实来源。
4. Save as Recipe 只提交后端生成的 durable `chart_artifact_id`。前端保存 artifact 产生时的稳定 chart 快照；后续 chart type、encoding、config、theme 或其他可复现状态变化会禁用保存，不能把编辑后的画面错误绑定到旧 Artifact。
5. `AUTOMATION_ENABLED` 默认关闭并同时控制 Blueprint before-request gate、app config、导航、Data Thread action 和画布 action；关闭时不会打开 Workspace 或调用 Recipe service。

### API 与页面契约

- `POST /api/recipes/compile` 从 1–20 个显式 artifact id 编译并保存 immutable draft；`GET /api/recipes` 和 `GET /api/recipes/versions/<id>` 返回当前 identity/workspace 内的目录、版本、输入和步骤。
- dry-run、publish、manual run、archive 分别调用同一后端生命周期服务；API 只返回经清洗的状态、run id、hash 和相对输出证据，不返回 credential、连接参数、数据行或绝对路径。
- Recipes 页面按后端状态只开放合法动作：draft 可 dry run、validated 可 publish、published 可 manual run/archive；typed parameter 控件在提交前把 number/integer/boolean/date/datetime 转成 JSON 类型，不做代码字符串替换。
- Data Thread 图表卡和聚焦画布复用同一个 Save as Recipe dialog。桌面线程卡使用 hover/focus action rail，触摸设备直接显示；保存后导航到刚创建的确切 RecipeVersion。

M2-C 实施结果：

- 新 Blueprint 全部路由先经过 default-off feature gate，再解析 request identity 和 durable local Workspace；repository 新增同时带 identity/workspace 条件的版本列表。纵向 route 测试已覆盖 compile → list/get → dry run → publish → manual run → archive，并证明 flag 关闭时连 Workspace 都不会打开。
- `chart_artifact_id` 随生成图表进入可持久化 Chart 描述；稳定递归 JSON 快照忽略图表 UI identity/read 标记，但会识别可复现状态变化。手工图表、缺 durable lineage 的图表和已编辑图表均不能静默保存旧 Recipe。
- 新 Recipes 页面展示版本状态、input mode、schema hash、步骤、typed parameters 与合法生命周期动作；前端 API 客户端对 version id 做 URL 编码，并始终把运行参数作为结构化 JSON object 发送。
- 新增中英文完整键集合、API/Artifact/UI 单元测试；Recipe 82 passed，全量后端 2220 passed、13 skipped、1 xfailed、1 deselected，前端 48 files / 396 tests passed，生产构建成功。

## M2-D 合并前最小收口（已完成）

### 目标和非目标

目标只有三类：关闭会破坏 Recipe 确定性的完整性缺口、收紧现有 API 边界、让现有 Recipes 页面不会串状态或误报运行结果。全部复用现有标准库、`ConfinedDir`、hash/schema helper、MUI、React Router 和 `apiRequest`。

本阶段不新增依赖、数据库表、路由层级、Redux slice、队列、DAG、report 执行步骤、参数编辑器、Schedule 或 Runs Inbox，也不修改原有项目/Workspace 和 Workflow Replay 概念。

### 实施切片

1. **完整性收口**
   - Web 与 request-independent Executor 从同一稳定配置源解析 HMAC 密钥；后台/生产缺少稳定密钥时失败关闭，并增加跨 Flask context 回归。
   - `_resolve_parent` 在接受 metadata link 或唯一 ledger fallback 前，复用既有 parquet SHA-256 与 Arrow schema helper 复核当前父表；不匹配时不写 transform/chart lineage。
   - `RecipeArtifactStore`、`RecipeRunArtifactStore` 与 opener 的持久化路径统一交给 `ConfinedDir`；覆盖正常路径、`../`、绝对路径、空值和 symlink escape，不增加另一套 path helper。
2. **API 与类型边界**
   - 可选空请求体与 malformed JSON 分开处理；后者始终返回 `INVALID_REQUEST`，不能按默认参数执行。
   - compile 边界验证精确 artifact id wire format；number/integer 分开做有限值和安全范围校验，极端整数返回稳定错误而不是 traceback。
3. **现有页面可靠性**
   - 以请求序号或取消信号忽略旧 Workspace/版本响应；URL `version` 变化触发同一加载路径。
   - manual run/dry run 的动作结果先固定，再单独刷新目录；刷新失败只显示同步警告，不能把已成功 Run 误报为失败或诱导重复运行。
   - 版本详情显示 immutable `spec.name/description`；用现有 Alert/Stack 增加本次 Run 的状态、run id、耗时和完成/失败步骤，不建设历史列表。
4. **验证和记录**
   - 先补上述失败测试，再做实现；聚焦测试通过后运行 `uv run pytest`、`yarn test`、`yarn build`。
   - 只更新本 Feature 工程记录。后端 Windows 编码/终端前置按既有约定配置，环境问题与 Recipe 回归分别记录。

### 完成标准

- 同一份 Web 签名代码可由无请求 Executor 验证；缺少稳定生产密钥时失败关闭。
- 父表内容或 schema、Recipe/Run 文件或路径发生篡改时，不产生新的可用 lineage/Recipe/Run。
- 非法 JSON、artifact id 和极端数值只返回稳定 4xx 错误，不开始执行。
- 快速切换 Workspace/版本不会显示旧详情；动作成功后的刷新失败不会触发重复运行误导；用户能看见本次运行摘要。
- report、参数编辑和 Automation 能力保持明确延期，文档、API 和 UI 不作超前承诺。

M2-D 实施结果：

- 代码签名按 `DF_CODE_SIGNING_SECRET`、`FLASK_SECRET_KEY`、显式开发模式的顺序解析；Web 使用稳定配置生成的签名可在无 Flask context 下验证，生产或后台缺少稳定配置时抛出配置错误，不再使用进程内随机密钥或无上下文测试 fallback。
- visualize 父节点在 metadata link 和 ledger fallback 两条路径上都重新计算当前 parquet content hash 与 schema fingerprint；任一不一致都在创建 transform/chart 节点前失败。Recipe/Run store 与 Workspace opener 的路径解析统一收口到 `ConfinedDir`，并覆盖空值、绝对路径、`..` 和可用环境下的 symlink escape。
- API 将空的可选 body 与 malformed JSON 分开；compile 只接受精确 `art_<64 hex>`，递归拒绝非有限数和超出 JavaScript 安全整数范围的整数值。Recipe typed binding 同步使用相同整数边界，极端值稳定返回校验错误。
- Recipes 页面以请求序号丢弃过期列表/详情响应，URL 版本变化走同一加载路径；生命周期动作先固定返回结果和版本状态，再独立刷新目录。刷新失败只显示同步警告，immutable 标题取自 `spec`，manual/dry run 使用既有组件显示即时状态、run id、总耗时和最后步骤。
- 未新增依赖、数据库 migration、Redux 状态、路由层级或 Automation 概念；report、参数编辑、Schedule、Worker、Runs Inbox 仍按既定分支延期。

## 开发记录

| 日期 | 阶段 | 实质变更 | 验证 | 提交 |
| --- | --- | --- | --- | --- |
| 2026-08-18 | 准备 | 核对 DataOperation plan hash、Sandbox、HMAC、Workspace 和前端刷新边界，建立共享文档与独立 Worktree | 固定源码审查、文档检查 | `docs: establish project plan` |
| 2026-08-18 | 准备 | 增加仓库级 Agent 指南并配置 fork remote | 文档链接、范围和 Git remote 核对 | `docs: add repository agent guide` |
| 2026-08-18 | 准备 | Agent 指南中文化，工程记录迁入 Feature 独立目录 | 文档链接、目录和旧路径检查 | `docs: localize agent guide and organize feature records` |
| 2026-08-18 | 准备 | 补充上游文档检索规则和无 Docker 开发约束 | 上游指南入口、文档链接和范围检查 | `docs: preserve upstream guidance and prohibit docker` |
| 2026-08-18 | 准备 | 固定多 Worktree 本机实例和资源隔离约定 | 端口、数据目录、浏览器状态和文档链接检查 | `docs: define multi-worktree runtime isolation` |
| 2026-08-18 | M0 审计 | 刷新 origin/upstream 引用，核对 load/transform/chart、Workspace、Sandbox、签名和 connector 的真实持久化边界，细化首个契约节点 | 聚焦后端 30 passed；全量后端 2130 passed；前端 391 passed；生产构建成功 | `docs: record recipe core M0 audit` |
| 2026-08-18 | M0-A | 新增 canonical JSON、不可变 ArtifactNode、workspace-scoped durable ledger 与显式 Workspace storage capability；ephemeral/Azure 无正式 artifact store 时失败关闭 | Recipe 契约 30 passed；全量后端 2160 passed、13 skipped、1 xfailed、1 deselected | `feat: add durable artifact lineage core` |
| 2026-08-18 | M0-B | DataOperation 成功写表后记录 load Artifact；完整复制 step，对实际 parquet 和 Arrow schema 生成独立 SHA-256，并支持写表后 lineage 补偿重试 | 聚焦链路 63 passed；全量后端 2165 passed、13 skipped、1 xfailed、1 deselected | `feat: record loaded tables as artifacts` |
| 2026-08-18 | M0-C | 将 visualize 声明输入升级为后端契约；签名后原子记录 transform/chart，回传 artifact ids，缺父时保留交互结果但禁用血缘 | 聚焦 53 passed；agent/route 781 passed；全量后端 2176 passed、13 skipped、1 xfailed、1 deselected | `feat: record visualize artifact lineage` |
| 2026-08-18 | M0-D / M2-A | 新增稳定祖先拓扑遍历、RecipeSpec v1、结构化 typed binding 和确定性 Compiler；对实际表、schema、签名和父表逐项失败关闭，并生成派生 Workflow Markdown | Recipe 49 passed；纵向切片 + Recipe 51 passed；agent/route 714 passed；全量后端 2187 passed、13 skipped、1 xfailed、1 deselected；前端 391 passed；生产构建成功 | `feat: compile artifact lineage into recipes` |
| 2026-08-18 | M2-B1 | 原子发布不可变 Recipe JSON/Workflow/manifest；以共享 automation SQLite 保存 scope、draft 生命周期和 artifact 引用，支持幂等恢复并拒绝篡改或跨 scope 访问 | Recipe + Workspace + vault 聚焦回归 120 passed | `feat: persist immutable recipe drafts` |
| 2026-08-18 | M2-B2 | 拆分无 Flask 的 connector registry 初始化；新增显式 scope Workspace/Connector opener，只认可重启后可恢复的 no-auth、vault 或 ambient 连接 | 聚焦 139 passed；全量后端 2201 passed、13 skipped、1 xfailed、1 deselected | `feat: add request-independent recipe openers` |
| 2026-08-18 | M2-B3 | 新增可校验 Run artifact、隔离确定性 Executor、dry-run validation 证据、SQLite v2 生命周期状态机和 lifecycle-aware manual run | Recipe 76 passed；相关回归 190 passed、8 skipped；全量后端 2214 passed、13 skipped、1 xfailed、1 deselected | `feat: execute and publish deterministic recipes` |
| 2026-08-18 | M2-C | 注册 default-off Recipe API；新增 Save as Recipe、artifact 编辑失效契约、Recipes 版本/输入/步骤与生命周期页面 | Recipe 82 passed；全量后端 2220 passed、13 skipped、1 xfailed、1 deselected；前端 48 files、396 tests；生产构建成功 | `feat: expose recipe lifecycle in the app` |
| 2026-08-18 | M2-D 规划 | 复核 Recipe 分支的完整性、API/UI 和分支边界；将 report/参数编辑明确延期，形成不增加依赖、表或状态系统的最小收口计划 | Recipe 聚焦后端 93 passed；聚焦前端 5 passed；前端全量与生产构建通过；全量后端环境差异已记录 | `fix: harden recipe core before integration` |
| 2026-08-18 | M2-D | 统一稳定签名密钥与父表新鲜度校验；用 `ConfinedDir` 收口 Recipe/Run/opener 路径；严格处理 JSON、artifact id 和安全数值边界；修复 Recipes 旧响应覆盖、动作结果误报并补即时 Run 摘要 | Recipe/签名/Agent 聚焦后端 116 passed、2 skipped；全量后端 2239 passed、16 skipped、1 xfailed；Recipes UI 4 passed；前端全量 48 files / 399 tests；生产构建和 Recipes ESLint 通过 | `fix: harden recipe core before integration` |

## 已确认决策

- Compiler 只接受持久化 artifact id，不读取聊天文本或 Redux 临时状态。
- Recipe 执行步骤只有 `load`、`transform`、`chart`。
- v1 只为 load/transform/chart 建立后端血缘；report 保留为现有会话产物，不是 Recipe target 或执行步骤。
- 正常 Save as Recipe 先生成固定 Recipe；Automation 不定义或猜测参数，typed binding 仅作为底层安全契约保留。
- Workflow Markdown 供人阅读，不反向驱动执行。
- HMAC 验证完整性，SHA-256 负责稳定版本比较。
- 无血缘、输入 unresolved 或 dry run 失败时不得发布。

## 未决与风险

- 手工创建 Chart 没有 durable artifact id，不能直接作为机器 Recipe 输入；后端生成 Chart 一旦在前端编辑，其保存动作会因 artifact 快照失效而禁用，重新持久化编辑结果仍需后续正式入口。
- 现有 Workspace `content_hash` 是抽样 MD5；Artifact 完整性与 schema fingerprint 必须使用独立、明确版本的算法。
- Azure Blob 首发支持取决于正式 artifact store 接口；不能使用 scratch。
- 数据库纵向切片使用已有环境或测试替身，不建立 Docker 测试依赖。
- Worker 调度、lease 与 Run catalog 属于 Automation Workbench；Recipe Core 已提供无 request opener 和确定性 service，但尚未接 Worker 生命周期。
- 生产 Web 和后续 Worker 必须显式共享 `DF_CODE_SIGNING_SECRET` 或 `FLASK_SECRET_KEY`；缺少稳定配置会按设计拒绝签名/验证，部署入口仍需在 Automation Workbench 集成时传递同一环境配置。
- Recipes 目前只显示本次请求返回的 Run 摘要；持久历史、筛选和处置仍归 Automation Workbench 的 Runs Inbox。
- Run 目录以最终 manifest 作为完成标记；进程崩溃留下的无 manifest 目录安全地不可读取，但自动回收策略留给 Automation Workbench 的维护任务。
- 当前 sandbox 的文件访问边界仍是整个 workspace；M0-C 将声明输入作为可验证的 provenance/Compiler 契约，但不声称已动态追踪 Python 的每次文件读取。若发布威胁模型要求抵御恶意已签名代码，需增加只挂载声明文件的 sandbox view。
- credential reference 仍是逻辑引用；只有 request-independent opener 能实际恢复连接且完整 dry run 成功时才会 validated/published。真实外部端点仍需在用户已有环境中补验，不建立 Docker 依赖。

## 合并前检查

- [x] 相同 artifact 集合产生相同 Recipe hash。
- [x] 缺失或篡改血缘会失败关闭。
- [x] typed binding 拒绝字符串注入。
- [x] dry run 成功后才能发布。
- [x] Published RecipeVersion 不可修改。
- [x] 正常 manual run 不调用 LLM/TrustGraph。
- [x] Web 与无请求 Executor 使用同一稳定签名密钥，缺失生产密钥时失败关闭。
- [x] 父 Artifact content/schema 在记录 transform/chart 前复核，篡改时不写 lineage。
- [x] Recipe/Run/opener 路径统一使用 `ConfinedDir` 并覆盖 symlink escape。
- [x] malformed JSON、非法 artifact id 和极端数值返回稳定 4xx。
- [x] Recipes 页面无旧响应覆盖、成功动作误报，并显示本次 Run 摘要。
- [x] M2-D 完成后重新执行 `uv run pytest`、`yarn test`、`yarn build`。
