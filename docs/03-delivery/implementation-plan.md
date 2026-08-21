# 实施计划

## 分支关系

```text
fixed upstream baseline
  └─ project main（共享准备文档）
       ├─ feat/analysis-integrations
       └─ feat/recipe-core
            └─ feat/automation-workbench
```

分析集成和 Recipe Core 从同一个共享文档提交独立开始。Automation 只在 Recipe 基础契约形成提交后，从 `feat/recipe-core` 创建。

## 分支职责

| 分支 | 负责 | 不负责 |
| --- | --- | --- |
| `feat/analysis-integrations` | TrustGraph 原生 Agent 的单一只读业务上下文 Skill、citation/trace、Copilot OAuth/capability | Recipe、Scheduler、Worker、TrustGraph UI、rows 入表/同步、知识摄取/Core 管理 |
| `feat/recipe-core` | Artifact ledger、Recipe、Compiler、dry run、manual run | Scheduler、Runs Inbox |
| `feat/automation-workbench` | SQLite、Schedule、Worker、Runs Inbox | Agent 和模型集成 |

`app.py`、`src/app/App.tsx`、Redux 类型和导航是冲突热点。各分支优先新增模块，最后用小型集成提交注册路由和入口。

## Feature 工程记录

三个功能分支各自维护一份记录：

| 分支 | 工程记录 |
| --- | --- |
| `feat/analysis-integrations` | `docs/04-features/analysis-integrations/README.md` |
| `feat/recipe-core` | `docs/04-features/recipe-core/README.md` |
| `feat/automation-workbench` | `docs/04-features/automation-workbench/README.md` |

每个 Feature 目录先只放一个 `README.md`，包含范围、实施顺序、工程记录、风险和检查项。以后只有确实产生独立设计或测试说明时，才在对应目录增加文件。记录只包含阶段、实质变更、验证、提交和未决问题，不写逐命令流水账。

## 里程碑

### M0：契约与风险验证

先完成四条可执行探针：

1. TrustGraph：固定 SDK、真实 Flow、trace collection、collection-bound 只读 Agent 工具组、bearer workspace、原生 Agent 多轮检索、provenance trace、超时和错误格式。
2. Copilot：LiteLLM `1.91.3` 下的 OAuth device、chat、stream、tool calling 和 token refresh。
3. Lineage：真实 database load → transform → chart，后端能完整遍历并稳定编译。
4. Runtime：Worker 无 Flask request 打开相同 Workspace，Web/Worker 共享同一 SQLite 和 artifact store。

探针失败时先修正契约或收缩功能，不继续堆 UI。

M0 不启动 Docker。数据库和 TrustGraph 合同验证使用已有可访问环境或测试替身；缺少真实端点时记录为外部条件，不以搭建容器作为解决方案。

### M1：可信交互分析

- 通用引用通道，以及 TrustGraph 原生 Agent 的单一只读业务上下文 Skill。
- identity/workspace/citation 契约及前端持久化显示。
- 知识 Profile 绑定 TrustGraph workspace、Flow、只读 Agent group、trace collection 和 credential reference，并支持“identity/workspace 精确覆盖 → 管理员服务器精确项或 `default` 后备”解析、请求时就绪判断和当前 Workspace 配置状态。轻量连接 UI 只管理非 secret 路由和 vault 中的 reader key，显式测试用官方 SDK 列出 Flow；不接入 collection/摄取管理。
- 聚焦问题 + 最小数据上下文的通用查询合同；workspace/bearer 负责授权和所有权隔离，同一 workspace 内的只读 group 按治理域提供一个或少量 collection-bound 查询工具，TrustGraph Agent 在问题到来后自行选择并按需多轮调用。Knowledge Core 只在同一知识域内复用/组合来源，不预先为未知问题制作跨域总集合，也不做跨 workspace 联邦查询。现有组继续保留 `structured-query`，但不作为 Data Formulator 第一版验收前置，后续以受治理结构化记录场景单独验收。
- 最终答案、文档来源、独立检索轨迹、由 `agent_explain` provenance 压缩出的实时查询轮次/阶段、会话续接和故障降级合同。
- TrustGraph 官方 UI 继续承担摄取、Context Core 管理和完整知识图谱工作台；Data Formulator 不复制这些能力。
- Copilot OAuth endpoint、顶部独立连接管理入口和能力探测；管理入口与模型对话框复用同一个 device-flow 面板。

### M2：Recipe Core

- Artifact ledger 和四个记录点。
- canonical hash、Recipe 模型、Compiler 和 repository。
- durable artifact store。
- dry run、publish、manual run。
- Save as Recipe 与 Recipes 页面。

### M3：Automation Workbench

- SQLite migration、Schedule/Run repository。
- Scheduler、lease Worker、取消和有限重试。
- Schedule 设置和 Runs Inbox。
- schema drift → Needs Review 闭环。

### M4：稳定化

- TrustGraph 原生 Agent 在真实业务上下文场景中的端到端产品收口；A13-A16 已覆盖自动路由、实时多轮步骤、IOF 制造业验收、分域路由和稳定工具 collection 版本切换/回滚。A17 提供当前 Workspace 的轻量连接 UI 和官方 Flow 枚举。企业自己的生产候选知识及保留的 `structured_query` 真实结构化记录场景仍须独立准备和验收；collection、工具、ontology、摄取和图谱管理继续打开官方 `trustgraph-ui`。
- Copilot 顶部入口管理 identity 连接状态，模型配置复用已取得的 capability 结果，只在连接变化、缓存缺失或显式复测时重新探测。
- 保留既有授权、引用、错误和大小边界的回归测试，不把它们继续拆成独立功能里程碑。
- 长时间运行、崩溃恢复、重复调度和重启测试。
- 中英文 UI、升级说明和发布检查。

## 第一条纵向切片

只使用一个数据库连接器、一个默认知识 Profile、一个包含少量当前可见知识域工具的 TrustGraph Agent group 和一个支持工具调用的模型：

1. 用户提出依赖未决业务含义的数据任务，Data Formulator 发送一个聚焦问题，以及当前操作、数据源/表角色、相关字段与类型、非敏感代表值或脱敏值模式和用户约束组成的最小上下文。
2. TrustGraph 原生 Agent 根据当前问题，从 group 中描述明确的 collection-bound 工具选择一个或多个并完成一轮或多轮检索；界面按真实 provenance 显示“第 N 次业务知识检索”的有限阶段，成功 trace 记录查询轮数，同时分别返回最终答案和官方明确文档来源；Data Formulator 据此继续本地分析。先通过单知识域路径，再验证一个跨两个当前可见知识域的真实问题。
3. 加载一张数据库表。
4. 生成一个 transform 和一个 chart。
5. 从 chart artifact 编译并 dry run Recipe。
6. 发布 RecipeVersion，创建每日 Schedule。
7. 成功运行一次。
8. 修改源 schema，再运行并进入 Needs Review。

通过后再扩展更多连接器、图表和调度能力。

## Git 初始化与 worktree

当前 `D:\projects\dfm-main` 已包含准备文档，因此原地初始化，不再向该目录执行 `git clone`：

```powershell
Set-Location D:\projects\dfm-main

git init
git remote add origin <你的-fork-url>
git remote add upstream https://github.com/microsoft/data-formulator.git
git fetch upstream main --tags
git checkout -B main 5477f0e236426dc8f74a498ec400414fba7fbc0f

git add docs
git commit -m "docs: establish project plan"

git worktree add -b feat/analysis-integrations D:\projects\dfm-wt-analysis main
git worktree add -b feat/recipe-core D:\projects\dfm-wt-recipe main
```

如果 fork 尚不存在，先省略 `origin`；不要把 Microsoft 上游配置成 `origin`。本地初始化、提交和 Worktree 不依赖 fork，获得 fork URL 后再执行 `git remote add origin <fork-url>`。

Recipe 基础契约提交后：

```powershell
git worktree add -b feat/automation-workbench D:\projects\dfm-wt-automation feat/recipe-core
```

让 `git worktree add` 创建目标目录，不预先放置文件。

多个 Worktree 在同一电脑并行运行时，必须按[本机多 Worktree 开发约定](./local-multi-worktree.md)使用固定实例槽位，隔离端口、`DATA_FORMULATOR_HOME`、浏览器状态和进程所有权。

## 测试门槛

基础命令：

```text
uv run pytest
yarn test
yarn build
```

测试过程中不启动 Docker，也不新增容器 fixture。上游明确依赖 `tests/database-dockers/` 的测试不作为本项目默认验收前置，需在工程记录中注明未执行原因。

必须覆盖：

- TrustGraph 单一高层查询的输入裁剪、scope、精确/默认知识 Profile 解析、请求时就绪判断、只读 Agent 工具组、必填 `trace_collection` 与非法 `collection` 字段拒绝、`agent_explain` WSS 请求、最终答案聚合、source/trace、续接、超时和故障降级。
- Collection 路由覆盖单知识域，以及同一 group 中两个任意合法名称、描述明确的 collection-bound 工具由原生 Agent 按当前问题选择/多轮调用；collection 按治理边界而非预测问题划分。领域工具保持稳定，切换其绑定的版本化 collection 后无需修改 Data Formulator。模型和前端不能提交 collection，Data Formulator 不枚举 workspace、不 fan-out 或自行合并排名。
- explain 事件压缩覆盖真实一轮和自动两轮：`grounding/exploration/focus/synthesis/observation/Conclusion` 产生有限进度，`AgentThought`、`AgentObservation` 正文、工具参数、原始 triples 和 answer token 不进入前端；连接关闭时释放 socket。
- 真实场景覆盖：从完整用户输入路径验证语义会改变结果时自动查询、用户规则明确或机械任务时跳过、证据不足或服务不可用时失败关闭；同时验证 tool-only Skill 能被模型正确发现。
- Copilot OAuth 生命周期、工具调用能力探测和已有 capability 结果复用。
- Artifact 记录、缺失血缘拒绝和稳定拓扑编译。
- typed parameter binding 的非法输入和注入尝试。
- Recipe hash、代码篡改、dry run 和发布状态机。
- SQLite migration、唯一入队、lease、重试、取消和恢复。
- Worker 与 Web 的 Workspace/数据库路径一致性。
- Feature flag 关闭时的 API 和 UI 行为。

## 每阶段完成条件

- M0：四条探针都有可重复测试和明确结论。
- M1：普通用户输入可按需获得业务知识并在长查询中看到真实轮次；文档来源与检索轨迹不混淆，未就绪目标不向 Agent 宣称可用，Copilot 不影响其他模型。
- M2：真实 artifact 能稳定编译、dry run、发布和手动运行。
- M3：页面关闭后 Schedule 仍能创建并执行 Run。
- M4：所有基础命令通过，重启和 schema drift 场景通过。
