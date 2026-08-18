# Recipe Core 工程记录

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 分支 | `feat/recipe-core` |
| Worktree | `D:\projects\dfm-wt-recipe` |
| 本机实例 | `recipe`：后端 5569、Vite 5175、数据目录 `D:\projects\dfm-runtime\recipe` |
| 基线 | 共享文档提交，父提交为 Data Formulator `5477f0e` |
| 当前阶段 | M0-D / M2-A 已完成：真实三步血缘可稳定编译为 RecipeSpec v1；下一步做 durable repository、独立 opener、dry run、发布和 manual run |

## 目标

从真实后端 Artifact Lineage 编译不可变 RecipeVersion，并支持 dry run、发布和手动确定性运行。

## 范围

- ArtifactNode 模型、ledger 和 load/transform/chart/report 记录点。
- canonical JSON、SHA-256、RecipeSpec v1 和稳定 Compiler。
- typed parameter binding 与输入可刷新性。
- durable artifact store。
- request-independent workspace opener。
- Recipe repository、dry run、publish 和 manual run。
- Save as Recipe 与 Recipes 页面。

不包含 Scheduler、lease Worker 和 Runs Inbox。

## 实施顺序

1. M0-A：定义 canonical JSON、ArtifactNode、scope 和本地 durable ledger 的最小契约，先覆盖不可变、幂等、篡改和跨 workspace 拒绝测试。
2. M0-B：在 `DataOperationExecutor` 成功写表后记录 `load` 节点；节点复制完整选定 step，不依赖 scratch 中的 DataOperation 或前端摘要。
3. M0-C：让 `visualize` 的声明输入成为后端校验契约，在 Sandbox 成功、代码签名完成后原子记录 `transform` 与 `chart` 节点，并把 artifact id 随结果事件返回。
4. M0-D：用数据库 loader 测试替身完成 load → transform → chart → 向上遍历 → 稳定编译探针；有现成外部数据库时再补真实端点验证，不启动容器。
5. M2-A：实现 RecipeSpec v1、typed binding、Compiler、稳定拓扑排序和失败关闭规则。
6. M2-B：补 durable recipe artifact store、request-independent workspace/connector opener、dry run、发布和 manual run。
7. M2-C：最后注册最小 API、Save as Recipe 和 Recipes 页面，避免过早修改 `app.py`、`App.tsx` 和 Redux 冲突热点。

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
- 聚焦 Recipe 契约：49 passed；包含 sandbox 的纵向切片与 Recipe 契约合计 51 passed。
- 全量后端：2187 passed、13 skipped、1 xfailed、1 deselected。deselect 项是 Windows 未启用符号链接权限时无法创建 symlink 的安全测试；Codex 终端另需 `PYTHONUTF8=1` 和非 `dumb` TERM，分别避免 GBK 测试夹具与 spinner 环境误报。
- 全量前端：45 files、391 tests passed；Vite 生产构建成功。构建仅有既有 eval、动态/静态混合导入和大 chunk 警告。

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
- recorder 从每个声明输入的 workspace metadata/ledger 解析并复核父 Artifact；对 derived 表实际 parquet 和持久化 Arrow schema 生成 transform hash，再以完整 chart spec 生成 chart hash。
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
- `refreshable` 当前只表示 Artifact 中有稳定 `source_id` 和逻辑 credential reference；它不证明后台能够恢复凭据。M2-B 必须由 request-independent opener 验证连接并完成 dry run，才可进入 `validated` 或 `published`。
- 使用数据库 loader 替身的纵向测试现已覆盖 load → sandbox transform → signed code → chart → ancestry → 两次稳定编译；Recipe 聚焦 49 passed，Agent/路由回归 714 passed，全量后端 2187 passed、13 skipped、1 xfailed、1 deselected；前端 391 passed，生产构建成功。

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

## 已确认决策

- Compiler 只接受持久化 artifact id，不读取聊天文本或 Redux 临时状态。
- Recipe 执行步骤只有 `load`、`transform`、`chart`。
- Workflow Markdown 供人阅读，不反向驱动执行。
- HMAC 验证完整性，SHA-256 负责稳定版本比较。
- 无血缘、输入 unresolved 或 dry run 失败时不得发布。

## 未决与风险

- 手工创建或编辑后的 Chart 目前只有 Redux/session_state，不能直接作为机器 Recipe 输入。
- 现有 Workspace `content_hash` 是抽样 MD5；Artifact 完整性与 schema fingerprint 必须使用独立、明确版本的算法。
- Azure Blob 首发支持取决于正式 artifact store 接口；不能使用 scratch。
- 数据库纵向切片使用已有环境或测试替身，不建立 Docker 测试依赖。
- Worker 所需 workspace opener 应从 Flask 请求依赖中解耦，但本分支只提供基础能力。
- Recipe Core 的文件型 artifact store 与 Automation 的 SQLite 元数据边界须在 publish repository 落地前固定，避免出现两套 Recipe 事实来源。
- 当前 sandbox 的文件访问边界仍是整个 workspace；M0-C 将声明输入作为可验证的 provenance/Compiler 契约，但不声称已动态追踪 Python 的每次文件读取。若发布威胁模型要求抵御恶意已签名代码，需增加只挂载声明文件的 sandbox view。
- M2-A 的 credential reference 仍是逻辑引用；在 M2-B 的显式 identity/workspace opener 和凭据恢复探针完成前，不得据此宣称 Recipe 可发布或后台运行。

## 合并前检查

- [x] 相同 artifact 集合产生相同 Recipe hash。
- [x] 缺失或篡改血缘会失败关闭。
- [x] typed binding 拒绝字符串注入。
- [ ] dry run 成功后才能发布。
- [ ] Published RecipeVersion 不可修改。
- [ ] 正常 manual run 不调用 LLM/TrustGraph。
- [ ] `uv run pytest`、`yarn test`、`yarn build` 通过。
