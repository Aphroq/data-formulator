# 产品目标与范围

## 产品定义

本项目直接扩展 Microsoft Data Formulator，形成一个“可信交互分析 + 确定性 Recipe + 轻量后台运行”的单体工作台。

用户继续在现有 Data Thread 中使用唯一的 `AnalystAgent` 探索数据。Agent 可以按需读取本地知识和 TrustGraph 业务上下文，也可以选择经 LiteLLM 使用 GitHub Copilot 模型。用户确认结果后，系统从真实 Artifact Lineage 编译不可变 RecipeVersion；手动和定时 Run 只执行该版本，不调用 LLM 或 TrustGraph。

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
| 运行 Recipe | 执行固定步骤、代码和图表规范；运行值只能进入已编译的 typed slot，产生可审计 Run | 否 | 是 |
| 定时运行 | Scheduler 按固定 RecipeVersion 和已保存的 typed value policy 创建 Run，入队时冻结实际值 | 否 | 是 |

Workflow Replay 保留为灵活的“分析方法复用”；Recipe 是严格的“已确认结果重放”。两者互补，不能互相冒充。

`Automation` 是 Recipe、Schedule 和 Run / Runs Inbox 的统一管理入口，不是新的 Project 实体，也不替代现有 Workspace、会话或项目概念。一个 Recipe identity 直接对应一个配方，版本保留在该 Recipe 内；Schedule 直接固定 Published RecipeVersion。

## 第一版必须完成

- 在现有 AnalystAgent 中按需查询 TrustGraph，只读获取业务上下文和来源。
- 可选使用 GitHub Copilot 模型，并验证 OAuth device、刷新、流式和工具调用。
- 为加载、转换和图表建立后端权威 Artifact Lineage。
- 从选定产物编译、dry run、发布和手动运行 Recipe。
- 参数含义沿用原 Workflow 的设计原则：从完整分析上下文中只找 0～4 个真正会改变结果、用户以后可能重选的业务选择，而不是把代码里所有可替换值都暴露出来。AnalystAgent 生成 transform 时应把这类明确选择声明为 scalar typed slot（阈值、Top N、窗口、类别或日期）；服务端把声明、默认值和签名代码一起写入不可变 Artifact Lineage。
- 保存 Recipe 时，Compiler 仍从 load filter/limit 和 transform slot 血缘中给出可绑定候选，但它只回答“哪些值能够确定性执行”。可选 AI 先根据 Workflow 上下文判断“哪些值值得调整”，再把最多 4 个推荐与候选对齐；不要求覆盖全部候选。只有匹配成功且经用户确认的 typed slot 进入 Recipe，匹配不上的语义参数只给出简短提示，引导用户回到原分析让 Analyst 生成可调版本。
- 为已发布 RecipeVersion 创建每日或 Cron 调度。
- 在 Runs Inbox 中查看成功、失败、Needs Review、本次冻结参数、日志和 manifest；成功 Run 用紧凑元信息和单一连续阅读流呈现全部最终图表/表格，图表优先、明细按需展开，重复说明与处理步骤不占据主报告。
- 成功 Run 可由用户显式请求一次“AI 解读”：复用当前所选模型，只基于已校验的不可变 RecipeVersion、冻结参数和限量结果样本生成一段摘要、1～3 条发现及可选注意事项；它不重跑 Recipe、不改变参数、不创建会话，也不持久化为新报告。
- 通过 schema drift 演示确定性失败和人工复核闭环。

## 直接复用、不重复建设

- Workspace 自动保存、恢复、导入和导出。
- Workflow Distill 与 Agent 语义 Replay。
- 页面内 URL/数据库刷新和已有派生代码重跑体验。
- CSV/TSV 表格导出，以及报告 PNG、打印 PDF、富文本复制。
- 现有数据连接器、Sandbox、代码签名和内容 hash。

这些能力可扩展或调用，但不改名包装成后台 Recipe 系统。

## 第一版明确不做

- 不增加第二个 Agent 或新的 Agent runtime。
- 可选参数推荐只是保存 Recipe 时的一次创作期模型调用，复用现有 LiteLLM Client 与 Workflow 上下文；它不是新的 Agent runtime，也不进入 dry run、发布、手动 Run、定时 Run 或 Worker。
- 不使用 Copilot SDK，不部署 LiteLLM Proxy。
- 不建设通用 DAG 编辑器或任意工作流平台。
- 不引入 Celery、Redis、Temporal、Kafka。
- 不在正常 Recipe Run 中调用 LLM、TrustGraph 或重新生成代码。
- 不允许模板字符串把参数直接替换进 Python 或 SQL。
- 不做多节点 Worker、网络共享盘 SQLite 或高可用调度。
- 项目开发、测试和运行不使用 Docker、Docker Compose 或容器化依赖。
- 不新增 Excel/Parquet/JSON 表格导出、报告投递和 Webhook。
- v1 不把仅存在于前端会话状态的报告直接编译为 Recipe，也不新增报告编辑器或第二套 Report Artifact。成功 Run 的默认报告只是从经校验的不可变 RecipeVersion 与本次终态制品生成的确定性只读投影；只有用户显式点击“AI 解读”才发生一次独立模型调用，结果仅保留在当前页面状态。
- v1 不提供通用 Recipe 参数定义器，也不允许保存阶段的模型或用户临时发明 binding。正常产品入口只允许用户选择 Compiler 从持久化 load 血缘发现的 filter/limit，以及 Analyst transform 产物中已经声明、验证并持久化的 scalar slot；任意 Python/SQL 字符串替换仍不开放。
- v1 不新增 Parameter Intent 数据表、参数匹配状态机、自动补 slot 或保存时静默改写 transform。AI 推荐只存在于当前保存对话框；没有可用绑定时仍可保存固定 Recipe，用户需要更多可调项时回到现有 Data Thread 明确让 Analyst 调整分析。
- v1 不把 Recipe/Run 数据塞进现有 Workspace ZIP；自动化制品迁移另行设计。

## 完成标准

- 用户能在同一 Data Thread 中获得带来源的业务上下文并完成分析。
- Save as Recipe 不依赖聊天猜测，能显示完整输入和步骤。
- AI 参数推荐默认只选少量真正有意义的候选，不再默认全选，也不要求模型逐项覆盖 Compiler 候选。调用失败或没有匹配项时，用户仍可手动选择候选或直接保存固定 Recipe；保存阶段的模型不能创建 slot、修改类型/绑定或注入代码。
- 发布前 dry run 成功；版本不可变，Schedule 固定版本。
- 手动和定时 Run 均不调用 LLM/TrustGraph。
- 同一 Published RecipeVersion 可用不同 typed values 产生不同结果；每个 Run 可追溯本次冻结值，修改 Schedule 不反改已入队 Run。
- 打开报告不调用模型；显式 AI 解读先验证 Run 制品，只发送有上限的非敏感上下文和结果样本，结构化输出失败不改变 Run 的成功状态。
- 重启后 Schedule、Run、manifest 和 Recipe 制品仍可恢复。
- Schema drift 可解释地进入 Needs Review。
- 三个 feature flag 默认关闭，关闭时没有残留可调用路径。
- 后端测试、前端测试和生产构建全部通过。
