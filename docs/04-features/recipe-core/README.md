# Recipe Core 工程记录

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 分支 | `feat/recipe-core` |
| Worktree | `D:\projects\dfm-wt-recipe` |
| 本机实例 | `recipe`：后端 5569、Vite 5175、数据目录 `D:\projects\dfm-runtime\recipe` |
| 基线 | 共享文档提交，父提交为 Data Formulator `5477f0e` |
| 当前阶段 | M0-A 已完成：Artifact 不可变模型、canonical hash、durable local ledger 与 Workspace capability 已落地；下一步接 load 记录点 |

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
- 聚焦后端契约：30 passed。
- 全量后端：2130 passed、13 skipped、1 xfailed、1 deselected。deselect 项是 Windows 未启用符号链接权限时无法创建 symlink 的安全测试；Codex 终端另需 `PYTHONUTF8=1` 和非 `dumb` TERM，分别避免 GBK 测试夹具与 spinner 环境误报。
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

## 已确认决策

- Compiler 只接受持久化 artifact id，不读取聊天文本或 Redux 临时状态。
- Recipe 执行步骤只有 `load`、`transform`、`chart`。
- Workflow Markdown 供人阅读，不反向驱动执行。
- HMAC 验证完整性，SHA-256 负责稳定版本比较。
- 无血缘、输入 unresolved 或 dry run 失败时不得发布。

## 未决与风险

- Chart spec 的后端持久化记录点需通过真实纵向切片确认。
- 手工创建或编辑后的 Chart 目前只有 Redux/session_state，不能直接作为机器 Recipe 输入。
- 现有 Workspace `content_hash` 是抽样 MD5；Artifact 完整性与 schema fingerprint 必须使用独立、明确版本的算法。
- Azure Blob 首发支持取决于正式 artifact store 接口；不能使用 scratch。
- 数据库纵向切片使用已有环境或测试替身，不建立 Docker 测试依赖。
- Worker 所需 workspace opener 应从 Flask 请求依赖中解耦，但本分支只提供基础能力。
- Recipe Core 的文件型 artifact store 与 Automation 的 SQLite 元数据边界须在 publish repository 落地前固定，避免出现两套 Recipe 事实来源。

## 合并前检查

- [ ] 相同 artifact 集合产生相同 Recipe hash。
- [ ] 缺失或篡改血缘会失败关闭。
- [ ] typed binding 拒绝字符串注入。
- [ ] dry run 成功后才能发布。
- [ ] Published RecipeVersion 不可修改。
- [ ] 正常 manual run 不调用 LLM/TrustGraph。
- [ ] `uv run pytest`、`yarn test`、`yarn build` 通过。
