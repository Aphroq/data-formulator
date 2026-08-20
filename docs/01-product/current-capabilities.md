# 现有能力与增量判断

## 核对基线

| 组件 | 固定版本 |
| --- | --- |
| Data Formulator | `0.8.0b1` / `5477f0e236426dc8f74a498ec400414fba7fbc0f` |
| TrustGraph | `0bcfe9377c3d55b7199c16335b9e52ed91286233` |
| LiteLLM | Data Formulator `uv.lock` 中的 `1.91.3` |

TrustGraph 的 `release/v2.8` 是移动分支。开发、测试和问题复现记录完整提交号，不只记录分支名。

## 对补充参考材料的判断

参考材料的核心结论成立，并已纳入项目范围：

- Data Formulator 已有成熟的会话恢复，不需要重新实现“项目保存”。
- Workflow Replay 是 Agent 语义重做，不是确定性复现。
- 已有页面内自动刷新和签名 Python 代码重跑，可以复用底层能力。
- 现有定时刷新不是后台 Scheduler。
- Workspace 导入导出、数据导入和常用结果导出应直接保留。
- 真正的增量是 Artifact Lineage、RecipeVersion、Run、Schedule 和 Worker。

需要修正或收紧的地方：

1. 现有刷新逻辑主要在 React Hook 中，不能直接视为后端 `RecipeExecutor`。
2. 派生刷新只检测非派生源表的 hash，并刷新直接依赖项；它不是任意深度 DAG 调度器。
3. HMAC 签名证明代码未被篡改，不锁定输入、参数、环境和输出，因此不等于可复现。
4. Agent 可以生成解释、Workflow 和人工修复建议；机器 Recipe 必须由确定性 Compiler 从 Artifact Lineage 生成。
5. Agent 不得在定时 Run 中自动修复和继续。异常进入 Needs Review，由用户确认后产生新 RecipeVersion。
6. Workspace ZIP 不含自动化 SQLite 中的 Recipe/Schedule/Run 元数据，因此不能默认宣称会迁移完整自动化状态。

## 能力矩阵

| 能力 | 当前实现 | 规划判断 |
| --- | --- | --- |
| 会话恢复 | 3 秒 debounce 保存可序列化 Redux 状态；打开 Workspace 时恢复 | 直接复用 |
| Workflow Replay | WorkflowDistillAgent 生成 Markdown；前端一次请求交给 Agent 重做 | 保留为语义重放 |
| 源数据刷新 | URL/可刷新数据库支持手动或定时轮询 | 保留交互体验 |
| 派生表刷新 | SQL View 重采样；签名 Python 代码重跑 | 复用 Sandbox/签名，重建后端编排 |
| Workspace 导入导出 | ZIP 保存清洗后的状态和 Workspace snapshot | 直接复用，暂不承载 Recipe/Run |
| 数据导入 | 上传 CSV/TSV/JSON/Excel；Local Folder 另支持 Parquet/JSONL | 直接复用 |
| 结果导出 | 表格 CSV/TSV；报告 PNG、打印 PDF、HTML/文本复制 | 直接复用 |
| 后台 Cron | 已有固定 Published RecipeVersion 的 Schedule、Cron/timezone/DST、Schedule API/UI、长步骤 lease heartbeat、正式 `data_formulator_worker`，以及一次真实 Web/独立 Worker 人工产品闭环 | 继续补默认浏览器 E2E、进程监督和发布稳定化 |
| Recipe 版本 | 已实现 Artifact Lineage、确定性编译、dry run、发布和手动运行 | 直接复用 |
| Run 审计与结果 | 已有 Recipe 终态制品、Automation 逻辑 Run 状态机、持久化 manual enqueue/cancel、Runs Inbox、失败证据，以及成功 Run 的紧凑只读报告：状态/时间/触发方式/冻结参数合并展示，全部最终输出连续呈现，图表优先、明细按需展开并支持完整 CSV 下载；用户还可显式请求一次基于已验证结果样本的简短 AI 解读 | 继续补真实外部 connector、报告 AI 解读 live 验收、默认浏览器自动化与长期运行验收 |

截至 2026-08-21，Automation 分支已经把共享目录数据库升级到 schema v5，并落地固定版本 Schedule、Cron/timezone/DST、typed parameter policy、逻辑 Run 的 claim/renew/fencing、取消、有限重试和过期 lease 恢复。v4 在 Run 行中增加仅供 Worker 使用的 active/cleanup attempt id；v5 为 Schedule 保存非敏感 typed value policy，并在入队时把解析后的实际值冻结到 Run。`AutomationWorker.run_once()` 可在无 Flask request 的路径中打开明确 identity/Workspace、验证固定 RecipeVersion、使用 Run 已冻结值执行 `RecipeExecutor`，并把安全的成功、失败、Needs Review、取消或延迟重试结果写回逻辑 Run；connector classifier 的 `retry=true` 和明确的 SQLite busy 是仅有的自动重试来源。

提交 `61eba9eb` 又增加了长步骤定时 heartbeat 和正式 `data_formulator_worker`：常驻进程每个周期先执行事务型 Scheduler tick，再最多执行一个 queued Run；heartbeat 在同步步骤运行期间持续续租，取消请求也会保持 lease 到下一个安全步骤边界。步骤期间观察到 heartbeat/fencing 失败会阻止终态 manifest，任何 lease 失败都阻止旧 Worker 写逻辑 Run 终态。当前稳定化实现会定点隔离并删除无 manifest 的过期 attempt，写入 retired tombstone 阻止旧进程迟到重建同一 id；已有 manifest 的未引用 attempt 保留且绝不误接到逻辑 Run。入口在创建 SQLite、Workspace opener 或 connector registry 前检查 `AUTOMATION_ENABLED=true`、稳定签名和 local Workspace，并与 Web 使用同一绝对 `DATA_FORMULATOR_HOME`；SIGINT/SIGTERM 会在当前同步周期后停止。重新构造 repository/runtime，以及执行中子进程被强制终止后的 lease/制品恢复合同测试均已通过。

提交 `1f5f181d` 完成 M3-D API/UI：默认关闭且 Workspace-scoped 的 Automation API 提供 Schedule 创建、列表、编辑、启停，持久化 manual enqueue、Run 列表/详情/取消，以及 manifest/events 只读查询。2026-08-20 又增加成功 Run 的 `result` 和最终输出表 sample/download，并打通 typed values。Compiler 候选现在有两类真相源：持久化 load query 的 filter/limit，以及 AnalystAgent 生成 transform 时显式声明、由服务端验证后与签名代码共同持久化的 scalar slot。运行时值作为独立 `params` 对象注入，不改写源代码。`ask` 不保存默认值，`keep` 保存当前 typed 默认值；手动 Run、Schedule policy 和 Run snapshot 均按 RecipeSpec 校验。每次结果读取都重新校验 scope、相对路径、manifest 与文件 hash，只允许 Recipe 声明的最终输出表；UI 直接复用原有图表与表格组件，不复制到 Workspace、不生成 Data Thread、不调用 Agent 或 Workflow Replay。真实 Web + 独立 Worker 的页面关闭、重启、取消和 schema drift 已做过一次人工产品验收；默认产品数据测试还对同一三步 Movies Recipe 的 transform `top_n` 分别运行 3/7，得到不同的 3/7 行结果、累计值和 binding hash，并在 Worker 内禁止 LLM。

当前工作树的保存参数助手已经收口为 Workflow 语义优先：候选默认不选中；用户可直接保存固定 Recipe，也可让当前模型先根据完整 Workflow 上下文判断最多 4 个真正有意义的运行选择，再映射到 Compiler candidate。模型只返回推荐子集，不再逐项覆盖全部候选；服务端对 candidate id 去重并取交集，未知或重复项被忽略，未匹配的语义选择只作为当前对话框的一句提示，不持久化、不自动改写 transform。

AI 只勾选匹配成功的推荐，其余候选折叠供手动选择。没有有效推荐、没有候选、没有模型或调用失败都不阻断保存固定 Recipe；零候选时仍可由模型说明 Workflow 中存在但当前血缘尚不能绑定的重要选择。最终 compile 仍只接受当前 Compiler 已知的 typed binding，正常 Run/Worker 仍完全无 LLM，也没有新增 Parameter Intent、匹配状态机或自动补 slot 流程。

2026-08-21 已用现有根目录 `.env` 和全局 `ModelRegistry` 配置 SiliconFlow `Qwen/Qwen3.5-27B`：API key 只留在服务端，前端显示掩码与“由服务端管理”；`SILICONFLOW_ENABLE_THINKING=false` 是唯一 provider 特有配置，Client 不按模型名推断能力，其余生成设置使用 provider 默认值。显式 live 用例在 3,201 行 Movies 复杂血缘上让真实模型从四个候选中选出三个运行输入，并把推荐直接编译、dry run、发布和交给无 LLM Worker 执行，最终表与独立 Pandas 基线一致。剩余稳定化重点是默认浏览器 E2E、报告 AI 解读 live 验收、Worker 进程监督、用户真实外部 connector 和长期运行验证。

成功 Run 的结果体验进一步收口为“只读分析报告”，但没有建立新报告系统：结果 API 从同一个已验证的不可变 RecipeVersion 投影稳定上下文，再与本次终态输出组成连续阅读流；页面只把状态、时间、触发方式和冻结参数作为紧凑元信息，移除重复目标说明、只读提示和可见处理步骤，每个输出只保留一条真正有用的展示说明。图表、按需数据、查询和 CSV 下载继续复用现有组件。打开报告仍不读取当前 Recipe 列表、聊天或 Redux，也不调用模型。

“AI 解读”是报告上的显式一次性动作，不是 Automation Run、Workflow Replay 或新的 Agent runtime。后端先按正常 result 路径校验 scope、manifest、descriptor 与文件 hash，再把不可变报告目标/参数/步骤、本次冻结值和有上限的最终输出样本交给当前所选 LiteLLM 模型；输出被限制为一段摘要、1～3 条带证据的发现和可选注意事项。解读只保存在组件状态，失败不会修改已成功 Run，也不生成 Report Artifact、Data Thread 或可继续对话的聊天界面。

## 会话恢复不是执行

`useAutoSave.tsx` 使用 3000 ms debounce，把去除敏感和瞬时字段后的状态保存到当前 Workspace 的 `session_state.json`。打开 Workspace 时，前端恢复输入表、派生表、图表、报告、线程和其他可持久状态，再从 Workspace 读取表数据。

这支持“继续工作”和“迁移已有结果”，但没有重新执行步骤、验证输入或生成 Run 记录。

源码：

- [自动保存](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/app/useAutoSave.tsx)
- [Workspace 状态恢复](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/app/dfSlice.tsx)

## Workflow Replay 是语义重放

`WorkflowDistillAgent` 从分析上下文提炼 Goal、Parameters、Abstract workflow、Concrete workflow 和 Notes。Replay 时，`SimpleChartRecBox.tsx` 把整份 Workflow 作为一次提示直接交给 Data Agent，源码明确描述为“one request, let the agent reproduce”。

因此它适合把分析思路应用到相似或不同数据，但允许字段映射、代码和图表发生变化，不能用于审计或后台确定性运行。

源码：

- [Workflow 提炼](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/agents/agent_workflow_distill.py)
- [Replay 入口](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/SimpleChartRecBox.tsx)

## 页面刷新链不是 Scheduler

`useDataRefresh.tsx` 使用递归 `setTimeout`：

```text
页面保持运行
  → 到达刷新间隔
  → 获取 URL/数据库新数据
  → 比较内容 hash
  → 更新源表
  → 重跑直接依赖的派生表
```

SQL View 通过 DuckDB 重新采样；Python 派生表把已保存代码和服务器 HMAC 签名提交到后端，经现有 Sandbox 重跑。这个机制有实际复用价值，但仍缺少后台进程、持久化调度、步骤状态、超时、重试、版本和输出验收。

这条前端刷新链自身在页面关闭、浏览器限制计时器或 Web 服务重启后仍没有可恢复任务；新建的 Automation Worker 是另一条持久化执行路径，不能据此把前端 Hook 当成 Scheduler。

源码：

- [自动刷新与派生刷新](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/app/useDataRefresh.tsx)
- [签名代码重跑接口](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/routes/agents.py)

## 导入导出边界

普通上传支持 CSV、TSV、JSON、`.xlsx` 和 `.xls`。Local Folder connector 另支持 Parquet、JSONL 及上述格式。现有 Workspace ZIP 包含 `state.json` 和 `workspace/` snapshot，其中可有 `workspace_meta.json`、`workspace.yaml`、`session_state.json` 和数据文件；导出前会清除模型、身份、连接参数等敏感字段。

现有产品导出包括：

- 表格 CSV，后端也支持 TSV delimiter。
- 报告 PNG。
- 通过浏览器打印流程生成 PDF。
- 报告 HTML + 纯文本复制。

当前导出仍没有 Recipe/Run 审计包、定时投递，以及 Excel/Parquet/JSON 表格导出入口。第一版不把这些相邻需求并入核心闭环。

源码：

- [上传入口](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/UnifiedDataUploadDialog.tsx)
- [Workspace 导入导出路由](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/routes/sessions.py)
- [ZIP 实现](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/datalake/workspace.py)
- [表格导出](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/py-src/data_formulator/routes/tables.py)
- [报告导出](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/ReportView.tsx)

## 对实现范围的直接影响

- 不重做会话、Workflow Replay、数据导入和现有导出。
- Recipe Core 复用 DataOperation plan、Sandbox、代码签名和 Workspace 表能力，但不依赖前端 Hook 作为执行器。
- 后端新建权威 Artifact ledger，才能把现有交互结果编译成固定 Recipe。
- Automation 只增加持久化 Schedule、Run、Worker 和恢复机制。
- Workflow Replay 与 Recipe 在 UI 和术语上明确分开。
