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
| `feat/analysis-integrations` | TrustGraph 知识目录、只读查询 Skill、citation、Copilot OAuth/capability | Recipe、Scheduler、Worker、TrustGraph UI、rows 入表/同步、行语义搜索、知识摄取/Core 管理 |
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

1. TrustGraph：固定快照、真实 ontology/flow/collection、bearer workspace、三元组与只读 SPARQL、`urn:graph:source` 溯源、超时和错误格式。
2. Copilot：LiteLLM `1.91.3` 下的 OAuth device、chat、stream、tool calling 和 token refresh。
3. Lineage：真实 database load → transform → chart，后端能完整遍历并稳定编译。
4. Runtime：Worker 无 Flask request 打开相同 Workspace，Web/Worker 共享同一 SQLite 和 artifact store。

探针失败时先修正契约或收缩功能，不继续堆 UI。

M0 不启动 Docker。数据库和 TrustGraph 合同验证使用已有可访问环境或测试替身；缺少真实端点时记录为外部条件，不以搭建容器作为解决方案。

### M1：可信交互分析

- 通用引用通道，以及 TrustGraph 本体/知识图谱只读 Skill。
- identity/workspace/citation 契约及前端持久化显示。
- TrustGraph Flow、collection、document、processing 与 Knowledge Core 目录。
- TrustGraph 图实体语义检索、本体读取、类型化 RDF 查询、只读 SPARQL、溯源和故障降级。
- TrustGraph GraphQL rows 只读查询；当前阶段不写 Data Formulator 表或 Workspace，不做同步。
- TrustGraph 官方 UI 继续承担摄取、Context Core 管理和完整知识图谱工作台；Data Formulator 不复制这些能力。
- Copilot OAuth endpoint 和能力探测。

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

- TrustGraph 目录、图实体语义检索和只读 GraphQL 查询的端到端产品收口；需要管理 UI 时打开官方 `trustgraph-ui`。
- 保留既有授权、引用、错误和大小边界的回归测试，不把它们继续拆成独立功能里程碑。
- 长时间运行、崩溃恢复、重复调度和重启测试。
- 中英文 UI、升级说明和发布检查。

## 第一条纵向切片

只使用一个数据库连接器、一个 TrustGraph collection 和一个支持工具调用的模型：

1. 查看 TrustGraph 知识目录，语义发现一个实体，再读取绑定本体、事实和抽取溯源。
2. 用 TrustGraph GraphQL query 取得结构化 rows，作为只读查询证据返回。
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

- TrustGraph 目录、本体、图实体语义检索、三元组/SPARQL 和只读 GraphQL rows 合同。
- TrustGraph RDF term 与溯源规范化、查询 Skill 只读边界、超时和故障降级。
- Copilot OAuth 生命周期和工具调用能力探测。
- Artifact 记录、缺失血缘拒绝和稳定拓扑编译。
- typed parameter binding 的非法输入和注入尝试。
- Recipe hash、代码篡改、dry run 和发布状态机。
- SQLite migration、唯一入队、lease、重试、取消和恢复。
- Worker 与 Web 的 Workspace/数据库路径一致性。
- Feature flag 关闭时的 API 和 UI 行为。

## 每阶段完成条件

- M0：四条探针都有可重复测试和明确结论。
- M1：上下文来源可追踪，Copilot 不影响其他模型。
- M2：真实 artifact 能稳定编译、dry run、发布和手动运行。
- M3：页面关闭后 Schedule 仍能创建并执行 Run。
- M4：所有基础命令通过，重启和 schema drift 场景通过。
