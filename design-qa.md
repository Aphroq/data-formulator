# Automation Run 报告设计 QA

**对照目标**

- Source visual truth: `C:\Users\lenovo\.codex\visualizations\2026\08\20\automation-ai-analysis-audit\01-current-report.png`
- Rendered implementation: `C:\Users\lenovo\.codex\visualizations\2026\08\20\automation-ai-analysis-audit\02-simplified-report.png`
- Combined comparison: `C:\Users\lenovo\.codex\visualizations\2026\08\20\automation-ai-analysis-audit\03-before-after.png`
- Route/state: `http://127.0.0.1:5176/automation`，同一 Comedy 成功 Run 的结果对话框，中文、浅色主题、支撑数据默认折叠；截图采集时尚未配置可用模型。
- Viewport: source 与 implementation 均为 `688 × 911` CSS px；截图均为 `688 × 911` pixels，device density `1x`，未缩放。

这里是体验优化前后对照，不是像素复刻。Source 用于确认既有产品结构、数据和视觉语言；目标差异是删除重复说明、把冻结参数并入元数据行，并增加一个显式且非自动执行的 AI 解读入口。

**Findings**

- 无可执行的 P0 / P1 / P2 问题。
- 字体与排版：沿用现有 MUI/system font、字号、字重和中英文 fallback；标题、说明、元数据层级清楚，没有新增截断或异常换行。
- 间距与布局：原先参数卡、Recipe 说明、只读说明、重复副标题和“分析过程”已移除；同一视口中结果标题和图表显著前移。参数 chip、图表、支撑数据和技术信息仍遵循既有间距、圆角和折叠样式。
- 颜色与 token：继续使用现有 `success`、`text.secondary`、`divider`、`action.hover` 和 outlined Button token，没有引入新配色或低对比度自定义样式。
- 图像与资产：没有新增位图或替代资产；图表继续使用真实 `VegaChartRenderer`，AI 入口复用现有 MUI icon。图表在同一数据状态下清晰度与缩放保持一致。
- 文案与内容：首屏只保留一次结果说明；AI 输出限定为摘要、1–3 条带证据发现和可选限制，并明确标注为 AI 生成。
- 可访问性：结果仍有 article/section/heading 结构；AI 入口是标准 Button，无模型时为 disabled，并通过 tooltip 与 `aria-describedby` 解释原因；生成结果使用命名 region 和 `aria-live="polite"`。

**Open Questions**

- 截图采集阶段浏览器只验证了无模型时 AI 按钮禁用和原因提示。随后已通过现有全局模型配置接入 SiliconFlow `Qwen/Qwen3.5-27B`，并完成真实参数推荐到复杂 Automation Run 的后端产品闭环；报告“AI 解读”的 loading/success/error 浏览器状态仍是明确验收缺口。结构化 helper、route 和组件交互由自动化测试覆盖，未把参数推荐 live 测试冒充报告解读 live 验收。

**Full-view comparison evidence**

- `03-before-after.png` 在同一视口并排显示前后状态。旧版在图表前有四层重复文本；新版把状态、时间、触发方式和参数压成一行，只保留一个输出标题和一个说明，主要结果更早进入视野。
- 当前 implementation 没有横向溢出、遮挡、裁切或不可达的固定操作。关闭按钮、技术信息和数据明细均在对话框内可见。

**Focused region comparison evidence**

- 未额外裁切 focused region：`688 × 911` 的完整对话框已经可以清楚辨认元数据、AI 按钮、结果标题、图表和折叠控件，局部裁切不会增加判断信息。

**Primary interactions tested**

- 从真实 Runs Inbox 打开 Comedy 成功 Run。
- 展开“数据明细”，确认真实保存行 `Comedy / 675 / 50,384,049,282`、搜索入口与 CSV 下载入口可见，再折叠恢复交付状态。
- 确认无模型时 AI 解读不发请求并显示禁用原因。
- 当前标签页 console error 日志为空。

**Comparison history**

1. 审计源截图识别出参数独立卡、Recipe 说明、只读说明、输出副标题/展示说明和分析步骤的重复信息。实现已删除或合并这些块，并加入显式 AI 解读入口。
2. 首次同视口 implementation 对照未发现新的 P0 / P1 / P2 问题；没有因 QA 发现问题而进行第二轮视觉修复。

**Implementation Checklist**

- [x] 元数据与参数合并为紧凑行。
- [x] 每个输出最多显示一条说明。
- [x] 删除首屏只读解释和分析过程重复块。
- [x] AI 解读仅由用户显式触发，未配置模型时禁用并解释原因。
- [x] 保留真实图表、按需数据明细、完整数据查询/下载和折叠技术信息。

**Follow-up Polish**

- 配置真实模型后补一次浏览器 success/error 状态截图；这属于验收覆盖，不是当前可见布局阻塞项。

final result: passed
