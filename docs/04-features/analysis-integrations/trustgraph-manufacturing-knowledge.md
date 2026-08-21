# TrustGraph 制造业知识准备与验收

## 选择结论

当前公开制造业验收知识采用 [Industrial Ontologies Foundry（IOF）Ontology](https://github.com/iofoundry/ontology)。IOF 面向数字制造，Core 提供跨制造场景的共同概念，Production Planning 覆盖离散、流程、批次等生产计划语义以及 ERP/MES、生产设备、工艺、检验和物料搬运计划。相较偏 IoT 互操作的 [SAREF4INMA](https://saref.etsi.org/) 和偏材料/物理建模的 [EMMO](https://github.com/emmo-repo/EMMO)，它更贴合 Data Formulator 当前“分析或清洗时核对业务含义”的需求。

本次固定使用 IOF [`Release_202602`](https://github.com/iofoundry/ontology/releases)、提交 `4c905ad22a93a1c6a5893d0907f32330074c8200`，许可证为 [MIT](https://github.com/iofoundry/ontology/blob/4c905ad22a93a1c6a5893d0907f32330074c8200/LICENSE)。[Production Planning](https://github.com/iofoundry/ontology/blob/4c905ad22a93a1c6a5893d0907f32330074c8200/productionplanning/README.md) 在上游仍标记为 provisional，适合公开集成验收，不应直接替代企业已治理的术语、编码和规则。

## GitHub 通用业务本体候选

2026-08-21 对可直接装载的公开 RDF/OWL 资源做了复核。现成资源确实存在，但“通用”不表示能无映射地叠加到当前 IOF 图：

| 候选 | 可复用内容 | 格式/许可 | 对当前项目的判断 |
| --- | --- | --- | --- |
| [Semantic Arts gist](https://github.com/semanticarts/gist) | Organization、Person、Agreement、Event、Product、Service 等约百个企业通用概念 | OWL 2 DL；Turtle，发布包另有 RDF/XML、JSON-LD；CC BY 4.0 | 最完整、最易读的通用企业候选，但属于另一套 upper ontology。可作为非制造业知识域的候选底座或建模参考，不与 IOF 全量混装 |
| [Common Core Ontologies](https://github.com/CommonCoreOntology/CommonCoreOntologies) | BFO 之上的 Agent、Organization、Event、Information、Facility、Artifact、Unit、Currency 等 11 个模块 | OWL/Turtle；BSD-3-Clause | 与同为 BFO 系的 IOF 结构最接近；但上游正进行 3.0/4.0 重构且明确提示迁移窗口，当前只适合固定已发布版本、按缺口选模块做验证 |
| [FIBO](https://github.com/edmcouncil/fibo) | Foundations、Business Entities、Agreements、Organizations、Products/Services 以及金融业务域 | OWL/RDF；MIT | 成熟且治理严格，但核心目标是金融合同、监管和风险。只有进入金融/法务场景时才建立独立领域知识，不作为制造业默认底座 |
| [gUFO](https://github.com/nemo-ufes/gufo) | Object、Event、Role、Situation 等轻量基础概念 | OWL 2 DL/Turtle；CC BY 4.0 | 适合构建本体的建模基础，抽象度高，不适合作为面向普通分析问题的现成业务词表 |

当前不新增第三个通用本体 collection，也不把任何候选写入 TrustGraph。现有 IOF Core 已包含 `BusinessOrganization`、`BusinessProcess` 等制造业共同业务概念；组织自己的指标口径、状态、编码、规则和术语仍应以自有 namespace 建成独立 Core，并按授权、发布生命周期和图关系决定装入既有业务知识 collection 还是独立 collection。若确实需要跨图直接遍历正式映射，再把固定版本的最小映射与两侧知识放入同一治理域验收；不能因为用户未来可能同时提问就预先全量合并。

## 固定来源清单

| 文件 | 用途 | SHA-256 | 官方 RDF triples |
| --- | --- | --- | ---: |
| [`core/meta/AnnotationVocabulary.rdf`](https://github.com/iofoundry/ontology/blob/4c905ad22a93a1c6a5893d0907f32330074c8200/core/meta/AnnotationVocabulary.rdf) | IOF 自定义定义、示例和说明谓词；让下游能解释 `naturalLanguageDefinition` 等注解 | `0539c2e6c7fed457c922410808b13da74804b4e6781decb48b3c5cc2a6f7a488` | 311 |
| [`core/Core.rdf`](https://github.com/iofoundry/ontology/blob/4c905ad22a93a1c6a5893d0907f32330074c8200/core/Core.rdf) | 制造活动、资源、组织、质量等共同语义 | `a653bcacef50a241aa1696d0d647b60527497cb1f32726f1891a05cbe5cb7638` | 3,889 |
| [`productionplanning/ProductionPlanning.rdf`](https://github.com/iofoundry/ontology/blob/4c905ad22a93a1c6a5893d0907f32330074c8200/productionplanning/ProductionPlanning.rdf) | Production Order、Production Plan、Manufacturing Operation、Machine、Process/Inspection/Material Handling Plan 等生产计划语义 | `8f5b8504346bbdab36195b719bd7597d383fdb64dfe23a117035a19e8ee08875` | 635 |

合计 4,835 条上游 RDF triples。固定提交 URL 和哈希是部署清单的一部分，不能在生产装载时静默改成移动分支。

## 最小装载合同

知识准备仍在 TrustGraph 部署侧完成，Data Formulator 保持只读。当前真实验收按以下简单合同装载：

1. 下载固定提交的三个 RDF/XML 文件，先核对 SHA-256，再解析；原文件同时保存进 TrustGraph Library。
2. 把可查询的本体 triples 写入目标 collection 的默认知识图。锁定版本的 GraphRAG 查询默认图，把全部知识只放在命名来源图会导致 SPARQL 可见但 Agent 不可检索。
3. 来源元数据写入 `urn:graph:source`。每个文件建立来源子图，用 RDF-star `contains <<s p o>>` 和 `prov:wasDerivedFrom` 关联到固定 GitHub blob URL；不把实体、谓词 IRI 冒充文档来源。
4. 用上游 label、自然语言定义、半形式定义、示例、父类和模块名建立图实体上下文。空白节点先稳定化；不由装载器编造行业定义。
5. 当前验证目标最终包含三个原始文档、6,878 条知识/来源/溯源记录和 218 个可检索实体上下文。部署到其他环境时按同一清单重新装载并重新计数，不复制当前 reader token 或 workspace 配置。

## 在 Collection 设计中的位置

A15 为了验证现有端到端链路，把 IOF 装入了 A11/A15 共用的验证 collection；该 collection 之前已经包含领域中立合成 fixture。上述数量和真实中文结果证明 IOF 可被当前 GraphRAG/Agent 链路检索，但这个混合集合不是生产候选 collection，也不应直接改名后上线。

A16 的分域发布和后续生产准备保持简单：

1. 把本页固定版本 IOF 来源制作成 workspace 级、独立于目标 collection 的可重复装载 Knowledge Core；组织自己的术语、编码、规则和来源保留为另一个或若干独立 Core。
2. 先按治理关系决定边界：如果 IOF 与组织扩展的授权或所有权不同，应进入不同 workspace/Profile，当前调用不跨 workspace；如果它们在同一 workspace 且需要在同一知识图中建立正式关系、共享发布生命周期，可以把相应 Core 装入同一版本化制造知识 collection；同一 workspace 内仍独立发布和检索的则保留为两个 collection。这个决定不依赖预想中的用户问题。
3. 为每个生产可查询知识域在同一只读 Agent group 中配置名称稳定、描述明确的 collection-bound 工具；发布新 collection 版本时只切换工具绑定，并按当前 TrustGraph 部署的正常方式使配置生效。用单域定义、关系问题和一个跨域多部分问题验收 Agent 的查询时选择；旧版、测试和归档 collection 不进入 Agent 可见工具集。
4. Data Formulator 仍只调用一次 `query_business_context`，不维护 collection 列表或做 fan-out；Knowledge Core 的组合只用于同一域内的来源复用，不承担跨域问题路由。

原始文档仍属于 TrustGraph workspace 的 Library；collection 承载从这些来源提取、组合并供查询的知识。来源文件多不等于必须拆成多个 collection。

### A16 分域发布结果

A16 没有在查询时临时组合 collection，也没有提前为某类问题建立跨域 serving collection。部署侧把两个长期治理域分别发布，再由同一个 Agent group 在问题到来后选择：

- 业务术语 Core `https://validation.data-formulator.local/core/business-glossary-serving-v1` 包含 31 条去重来源知识和 7 个实体上下文，装入干净的 `dfm-business-glossary-v3`；TrustGraph 物化后的精确 SPARQL 计数为 62。稳定工具 `business-glossary-query` 只描述术语、定义、计算口径、比较规则及其排除范围。
- 固定 IOF Core `https://github.com/iofoundry/ontology/tree/4c905ad22a93a1c6a5893d0907f32330074c8200` 装入独立的 `dfm-iof-release-202602-v2`，精确计数为 13,750。稳定工具 `manufacturing-ontology-query` 只描述公开制造概念、定义和关系及其排除范围。
- 两个工具位于同一个 `data-formulator-readonly` group；既有 `structured-query` 继续保留，仍绑定历史结构化验证集合。本次没有增加 row embeddings、写操作、摄取或管理工具。

普通业务术语问题只调用 `business_glossary_query`，IOF 概念关系问题只调用 `manufacturing_ontology_query`，同时涉及两域的问题各调用一次；产品只显示两轮通用实时步骤，不暴露 action。为验证发布合同，同一业务术语 Core 又装入 `dfm-business-glossary-v4`，直接 GraphRAG 验证后仅把稳定工具的 collection 绑定从 `v3` 切至 `v4`，Data Formulator Profile 和请求保持不变并成功回答；验证后已切回 `v3`。旧混合 collection 和 `v4` 留作历史验收/回滚材料，不进入当前领域工具路由。

## 真实验收结果

- 精确 SPARQL 返回 `ProductionOrder` 的官方 label、自然语言定义和固定 GitHub 来源。
- 英文语义检索前列包含 `ManufacturingOperation`、`ProductionOrder`、`ProductionPlan`、`ManufacturingProcess` 和 `ProcessPlan`；直接 GraphRAG 能区分生产订单、生产计划和制造操作，并返回一个官方来源。
- 真实中文 `/api/agent/analyst-streaming` 输入使用包含 `production_order_ref`、`production_plan_ref`、`operation_name`、`equipment_ref`、`planned_quantity`、`event_time` 的表结构，自动完成 `load_skill → query_business_context`。同一次 TrustGraph Agent 查询执行两轮检索，前端收到两轮实时步骤，最终建议不要把三类对象合并；没有调用 Python 或图表工具。
- IOF 的实体上下文以英文为主，锁定 embedding 的直接中文命中不稳定。Data Formulator 的通用任务帧因此允许：首轮证据不足且请求语言与索引术语可能不一致时，再用保持原业务含义的常用语或英文等价词补查一次，并仍以用户语言回答。这里没有写死制造业词表。
- 查询失败等于没有证据。Skill 明确禁止用模型记忆或泛化行业经验替代失败的业务上下文查询。
- A16 的 B-only 真实请求只调用制造业本体工具并完成一轮 `searching → filtering → summarizing → completed`；A+B 请求由同一 TrustGraph Agent 依次调用业务术语和制造业本体工具，完成两轮后再形成结论。`structured_query` 未被这些知识问题误用。

## 已知来源边界

直接 GraphRAG 响应能返回上述来源，但锁定的 `trustgraph-base==2.8.14` 高层 `AgentAnswer` 不携带中间 GraphRAG 的 `sources`；`agent_explain` 也只提供阶段事件和最终答案。因此 Data Formulator 的真实 Agent 路径当前只展示 session trace，不伪造文档 citation，也不增加第二次低层查询来重建来源。2026-08-21 又用真实四轮双域 session 调用官方 `ExplainabilityClient.fetch_agent_trace()`，SDK 在首次 provenance 读取即因内部调用 `FlowInstance.triples_query(g=...)` 而失败，而同版本公开方法不接受 `g` 参数。修复已提交上游 [trustgraph-ai/trustgraph#1096](https://github.com/trustgraph-ai/trustgraph/pull/1096)；当前产品仍锁定官方 `2.8.14`，不依赖个人 fork 或在 Data Formulator 局部打补丁。只有官方 Agent 终态明确透传来源，或修复进入官方发布并完成真实合同回归后，才重新评估 citation。

这批 IOF 数据证明公开制造业知识可以被真实产品链路检索，不代表组织自己的工位、物料、状态码、质量规则、口径和来源已经治理完成。生产上线仍需用同样的来源、版本、定义、关系和可检索上下文清单装载企业知识，并单独验收保留的 `structured_query` 场景。
