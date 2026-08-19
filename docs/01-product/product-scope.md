# 产品目标与范围

## 产品定义

本项目直接扩展 Microsoft Data Formulator，形成一个“可信交互分析 + 确定性 Recipe + 轻量后台运行”的单体工作台。

用户继续在现有 Data Thread 中使用唯一的 `AnalystAgent` 探索数据。Agent 可以按需读取本地知识，也可以浏览 TrustGraph 的知识目录和本体、按语义发现图实体、查询 RDF 事实与抽取溯源，并把 TrustGraph 的 GraphQL 行查询结果作为结构化证据用于当前分析。用户还可以选择经 LiteLLM 使用 GitHub Copilot 模型。用户确认结果后，系统从真实 Artifact Lineage 编译不可变 RecipeVersion；手动和定时 Run 只执行该版本，不调用 LLM 或 TrustGraph。

## 目标用户

- 需要结合业务语义做数据探索的数据分析师。
- 希望把一次成功分析固化为可审计流程的数据团队。
- 需要同主机轻量定时执行，但不需要企业级编排平台的团队。

## 五个产品概念

现有能力和新增能力必须使用不同名称，避免把“看起来又跑了一次”都叫作重放。

| 名称 | 含义 | 是否依赖 Agent | 是否适合后台调度 |
| --- | --- | --- | --- |
| 继续会话 | 从 Workspace Snapshot 恢复表、图表、线程、报告等分析现场 | 否 | 否 |
| 重放分析 | 把 Workflow Markdown 作为提示交给 Agent，在当前数据上语义重做 | 是 | 否 |
| 刷新数据 | 页面内更新 URL/数据库源，并重算直接相关派生表 | 否 | 否，依赖页面运行 |
| 运行 Recipe | 执行固定输入绑定、固定代码和图表规范，产生可审计 Run | 否 | 是 |
| 定时运行 | Scheduler 按固定 RecipeVersion 创建 Run | 否 | 是 |

Workflow Replay 保留为灵活的“分析方法复用”；Recipe 是严格的“已确认结果重放”。两者互补，不能互相冒充。

## 第一版必须完成

- 在现有 AnalystAgent 中浏览 TrustGraph collection、文档、处理任务和 Context Core 目录，并按需读取业务本体。
- 通过图实体语义搜索、三元组模式或 SPARQL 查询知识图谱及抽取溯源。
- 通过 GraphQL 只读查询 TrustGraph 结构化数据；当前阶段只返回结构化查询结果，不写入 Data Formulator 表、Workspace，也不建立同步或刷新链路。
- 可选使用 GitHub Copilot 模型，并验证 OAuth device、刷新、流式和工具调用。
- 为加载、转换、图表和报告建立后端权威 Artifact Lineage。
- 从选定产物编译、dry run、发布和手动运行 Recipe。
- 为已发布 RecipeVersion 创建每日或 Cron 调度。
- 在 Runs Inbox 中查看成功、失败、Needs Review、日志和 manifest。
- 通过 schema drift 演示确定性失败和人工复核闭环。

## 直接复用、不重复建设

- Workspace 自动保存、恢复、导入和导出。
- Workflow Distill 与 Agent 语义 Replay。
- 页面内 URL/数据库刷新和已有派生代码重跑体验。
- CSV/TSV 表格导出，以及报告 PNG、打印 PDF、富文本复制。
- 现有数据连接器、Sandbox、代码签名和内容 hash。
- TrustGraph 官方 `trustgraph-ui` 负责知识图谱浏览、Ontology/SPARQL/GraphQL 工作台、文档摄取和 Context Core 运维；Data Formulator 不复制这些管理界面。

这些能力可扩展或调用，但不改名包装成后台 Recipe 系统。

## 第一版明确不做

- 不增加第二个 Agent 或新的 Agent runtime。
- 不把 TrustGraph Agent、GraphRAG 或文本补全作为本项目的回答路径；自然语言回答仍由现有 `AnalystAgent` 生成。
- 不接入 TrustGraph `row_embeddings_query()`，不增加行数据语义搜索。
- 不在 Data Formulator 增加文档摄取、Processing 或 Context Core load/unload/bulk 管理入口。
- 不自建或复制 TrustGraph 工作台；需要管理和可视化时复用官方 `trustgraph-ui`。
- 不使用 Copilot SDK，不部署 LiteLLM Proxy。
- 不建设通用 DAG 编辑器或任意工作流平台。
- 不引入 Celery、Redis、Temporal、Kafka。
- 不在正常 Recipe Run 中调用 LLM、TrustGraph 或重新生成代码。
- 不允许模板字符串把参数直接替换进 Python 或 SQL。
- 不做多节点 Worker、网络共享盘 SQLite 或高可用调度。
- 项目开发、测试和运行不使用 Docker、Docker Compose 或容器化依赖。
- 不新增 Excel/Parquet/JSON 表格导出、报告投递和 Webhook。
- v1 不把 Recipe/Run 数据塞进现有 Workspace ZIP；自动化制品迁移另行设计。

## 完成标准

- 用户能在同一 Data Thread 中发现可用知识域、查看业务本体、语义搜索实体、获得结构化图谱事实和行数据，并把结果用于后续表格与图表分析。
- Save as Recipe 不依赖聊天猜测，能显示完整输入和步骤。
- 发布前 dry run 成功；版本不可变，Schedule 固定版本。
- 手动和定时 Run 均不调用 LLM/TrustGraph。
- 重启后 Schedule、Run、manifest 和 Recipe 制品仍可恢复。
- Schema drift 可解释地进入 Needs Review。
- 三个 feature flag 默认关闭，关闭时没有残留可调用路径。
- 后端测试、前端测试和生产构建全部通过。
