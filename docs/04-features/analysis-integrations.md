# Analysis Integrations 工程记录

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 分支 | `feat/analysis-integrations` |
| Worktree | `D:\projects\dfm-wt-analysis` |
| 基线 | 共享文档提交，父提交为 Data Formulator `5477f0e` |
| 当前阶段 | Worktree 已准备，尚未开发，等待 M0 探针 |

## 目标

在现有 `AnalystAgent` 中增加可信业务上下文和可选 Copilot 模型，不创建第二个 Agent runtime。

## 范围

- 通用 `BusinessContextProvider`。
- TrustGraph 只读 Skill、来源、超时和故障策略。
- `SkillContext` identity/workspace 与 `ToolResult` citation 契约。
- Citation 在 Data Thread 中的持久化展示。
- LiteLLM Copilot `oauth_device`、provider 解析和能力探测。
- `TRUSTGRAPH_ENABLED`、`GITHUB_COPILOT_ENABLED`。

不包含 Recipe、Schedule、Run 或 Worker。

## 实施顺序

1. M0 TrustGraph 与 Copilot 真实契约探针。
2. 通用 context/citation 类型和失败测试。
3. TrustGraph provider 与 business-context Skill。
4. Copilot OAuth endpoint 与 capability probe。
5. 前端引用展示和 feature flag 集成。

## 开发记录

| 日期 | 阶段 | 实质变更 | 验证 | 提交 |
| --- | --- | --- | --- | --- |
| 2026-08-18 | 准备 | 核对真实 Skill、模型注册表和 LiteLLM 扩展点，建立共享文档与独立 Worktree | 固定源码审查、文档检查 | `docs: establish project plan` |

## 已确认决策

- TrustGraph 是 Skill，不是 Agent。
- Copilot 继续经过 LiteLLM，不接 Copilot SDK。
- 引用通道是通用 Skill 契约，不在 Agent 中硬编码 TrustGraph。
- 外部上下文作为不可信数据处理。
- capability probe 至少覆盖 chat、streaming 和 tools。

## 未决与风险

- LiteLLM `1.91.3` 的 Copilot token 存储与刷新行为需真实验证。
- TrustGraph bearer token、flow、collection 与 workspace 映射需用真实环境验证。
- Citation 需要找到稳定的线程持久化位置，不能只进入 thinking step。

## 合并前检查

- [ ] M0 探针有可重复测试和明确结论。
- [ ] 两个 feature flag 默认关闭。
- [ ] 关闭 TrustGraph 不影响本地知识。
- [ ] 关闭 Copilot 不影响现有 provider。
- [ ] Secret 和来源内容没有泄露到日志。
- [ ] `uv run pytest`、`yarn test`、`yarn build` 通过。
