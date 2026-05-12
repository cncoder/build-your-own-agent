# Chapter 5 · 技术选型：Prompt / Few-shot / RAG / Agent / Fine-tune 怎么选

> 方法论章 · 无代码产物 · 产物是印刷级决策树

```
全书路线图

Ch1 → Ch2 → Ch3 → Ch4 → [Ch5 ← 你在这里] → Ch6 → Ch7 → ...
                                  ↑
                           选型决策章
                      写第一行代码之前，先决定走哪条路
```

本章从"五条路径是什么"出发 → 经过逐条解剖（动机、适用边界、不该用的场景、五维打分）→ 到一张可打印的决策树。途中会踩一个坑：大多数工程师在面对新需求时会本能地选"最熟悉的路径"，而不是"最适合的路径"——本章的目的是打断这个本能，建立一套有判断依据的选型直觉。

Lena 在本章不写新代码。本章结束时，读者脑里有一张地图，知道 Ch6 开始的每条技术路线在地图上的位置。

---

## Beat 1 — 路线图

```
你现在在这里：Ch5

Ch3（Lena 诞生：50 行裸 loop）
    ↓
Ch4（LLM 内部结构：工程直觉）
    ↓
Ch5（技术选型：五条路径，一张决策树）← 当前位置
    ↓
Ch6+（工具系统、RAG、Planning……按选型结果深入）
```

Lena 在 Ch3 末尾已经能跑通一次工具调用。现在你想让她帮你做更多事——比如回答公司内部文档的问题、用特定风格写邮件、自主执行多步任务。

在动手之前，先停下来问一个问题：**你打算走哪条路？**

这个问题不是哲学问题，而是工程决策。不同路径的成本相差 10 倍，数据需求相差 1000 倍，时延相差 5 倍。选错了，不是"不够好"，是"做了再改"——而"改"在 LLM 系统里意味着从头评估、重建索引、或者重新训练。

本章对应 Lena 演进图上的一个特殊节点：**没有新代码，但有选型后的清醒**。读完这章，你能用自己的话解释"我选这条路，因为……"，而不是"好像大家都在用 RAG"。

> **🧠 聪明度增量（v0.4 → v0.5）**：Lena 第一次具备"理性选型"能力——用五维度打分框架（成本/时延/数据需求/更新频率/可控性）在 Prompt / Few-shot / RAG / Agent / Fine-tune 五条路径中做有依据的选择，而不是本能地选"最熟悉的路"。这一章教读者把选型判断力长在自己 agent 架构决策上的方法。

---

## Beat 2 — 动机：为什么选型错误代价极高


先看一个数字：一个不该走 Fine-tune 路径的项目，平均浪费多少时间？

在实际生产系统里，一个初始规模的 LoRA fine-tune 实验（数据清洗 + 标注 + 训练 + 评估）至少需要 2-4 周。如果最终发现"其实用 RAG + 好的 prompt 就够了"，这 2-4 周沉没成本无法回收。更糟的是，fine-tuned 模型是静态的——它的知识在训练截止日冻结，每次知识更新都要重训。

Fine-tune 是典型的"过度工程"陷阱，但反过来的陷阱也存在：

一个本该用 Fine-tune 的风格化任务（比如"用我公司客服的语气回复"）如果强行用 few-shot，每次调用要塞入 20 个示例，每个 API 请求多花约 2000 token，按 Anthropic Claude Sonnet 定价折算，**1000 次调用多花约 $0.60**。听起来不多？规模化到 100 万次调用就是 $600 的纯浪费，而且还没解决风格一致性问题。

两个陷阱、两个方向。选型错了，要么浪费时间，要么持续浪费钱。

真正的挑战不是"哪条路最好"——每条路都有适合它的场景——而是"在面对新需求的头 30 分钟，如何快速收敛到正确的路径"。这就是本章决策树要解决的问题。

---

## Beat 3 — 理论铺垫：五条路径的本质

> *3.1 节 — 纯理论*

### 3.1 五条路径的本质差异

Convention：**路径** = LLM 系统解决特定问题的核心技术手段；**策略** = 同一路径下的具体实施方式（如 Few-shot 是 Prompt Engineering 的策略之一）。本章统一用"路径"指代五种顶层选择。

五条路径，一句话定位：

| 路径 | 本质 | 改变什么 |
|------|------|----------|
| **Prompt Engineering** | 告诉模型怎么做 | 输入格式和指令 |
| **Few-shot / ICL** | 给模型看例子 | 输入中的示例内容 |
| **RAG** | 给模型找资料 | 在推理时动态注入外部知识 |
| **Agent** | 给模型工具和循环 | 模型的行动能力和执行环境 |
| **Fine-tune** | 改变模型本身 | 模型的权重 |

这五条路径在概念上是独立的，但在工程上经常叠加：一个 Agent 可以内嵌 RAG 作为工具，RAG 的文档过滤可以用 Prompt Engineering 优化，Fine-tune 的结果可以作为 Agent 的骨干模型。

> *3.2 节 — 纯理论*

### 3.2 五维度评估框架

不同路径在五个维度上的代价和收益截然不同。评估时必须同时看五个维度，而不是只看"精度"：

**Convention**：
- **成本（Cost）** = 每次推理的 API 费用 + 工程维护成本；
- **数据要求（Data）** = 需要准备的标注数据量；
- **时延（Latency）** = 每次推理的端到端响应时间；
- **精度（Quality）** = 在目标任务上的准确率/质量；
- **维护（Maintenance）** = 系统上线后的持续维护复杂度。

五维度打分用 1-5 表示（1 = 该维度代价最低/最容易，5 = 该维度代价最高/最难）。

> 这个框架来自 Anthropic Engineering Blog 对 agent 设计的核心原则之一："Success in the LLM space isn't about building the most sophisticated system. It's about building the *right* system for your needs."（来源：[Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)）

> *3.3 节 — 纯理论*

### 3.3 两个反直觉事实

**反直觉事实 1：Fine-tune 不是"更高级的 Prompt Engineering"**

乍看 Fine-tune 像是"把 prompt 烧进模型权重"——精度更高，成本更低。但实际上它更像"给模型做手术"：手术后，模型的通用能力可能衰退（catastrophic forgetting），而且每次知识更新都要重做手术。Fine-tune 解决的是**风格/格式/领域术语**问题，不是**知识更新**问题。把 Fine-tune 当成知识注入工具，是这个领域最常见的误解之一。

> "Fine-tuning and RAG are often seen as alternatives. In practice, they solve different problems: RAG handles knowledge retrieval; fine-tuning handles behavioral alignment." —— 这是目前该领域被引用最多的工程判断之一，本书采用此操作性定义。

**反直觉事实 2：Agent 不是"更复杂的 RAG"**

乍看 Agent 像是 RAG 加上工具调用——能检索、能执行。但实际上它更像一个"操作系统进程"而非一个"查询引擎"：它有循环、有状态、有行动能力。这意味着它的错误也会循环放大，而 RAG 的错误只在单次检索上体现。Agent 的适用场景是**多步、不确定、需要动态决策**的任务，而不是"我需要更准确地回答问题"。

> Anthropic 在 Building Effective Agents 中明确写道："many patterns can be implemented in a few lines of code"，并警告"adding unnecessary framework layers"是反模式。这句话的背后含义是：在上 Agent 之前，先穷尽简单方案。

---

## Beat 4 — 五路径全景图：先鸟瞰，再俯冲

Now let's walk through each path systematically — not to celebrate it, but to find its ceiling and its floor.

在深入每条路径之前，先看一张全景对比表。这是选型的第一步：用五维度快速定位你的场景落在哪个象限。

**五条路径五维度对比（1=代价最低，5=代价最高）**

| 路径 | 成本 | 数据要求 | 时延 | 精度（目标任务） | 维护复杂度 |
|------|------|----------|------|-----------------|-----------|
| Prompt Engineering | ★ | ★ | ★★ | ★★★ | ★★ |
| Few-shot / ICL | ★★★ | ★★ | ★★★ | ★★★★ | ★★ |
| RAG | ★★★ | ★★★ | ★★★ | ★★★★ | ★★★ |
| Agent | ★★★★★ | ★★ | ★★★★★ | ★★★★★（多步任务） | ★★★★★ |
| Fine-tune | ★★★★ | ★★★★★ | ★★ | ★★★★★（目标域） | ★★★★ |

读表方式：不要找"全最低"的行——那条路径不存在。要找"你最在意的那个维度里代价可接受、其他维度都不超预算"的路径。

**三个最常见的误选模式**

乍看这张表，有三种本能误选：

1. **"Fine-tune 精度最高，所以选 Fine-tune"** → 忽略了数据要求和维护成本，以及它无法解决知识更新问题。
2. **"Agent 能做所有事，所以选 Agent"** → 忽略了成本倍增和错误放大效应，在固定流程任务上是过度工程。
3. **"Prompt 免费，所以先 Prompt 再说"** → 合理起点，但如果任务根本是知识检索任务，再好的 prompt 也无济于事，早做决策早省力。

现在，带着这张全景图，进入每条路径的细节。

---

### 4.1 路径一：Prompt Engineering

**一句话定位**：Prompt Engineering 是五条路径里成本最低、起点最近的一条。它让你可以在不改变任何基础设施的情况下，通过调整输入文本提升 LLM 输出质量。它的天花板比大多数人认为的要高，但它的地板也比大多数人认为的要高——有些问题它根本够不到。

**五维度打分**

| 维度 | 得分 | 说明 |
|------|------|------|
| 成本 | ★★★★★ | 几乎零额外成本，仅消耗指令 token |
| 数据要求 | ★★★★★ | 无需标注数据，人工迭代 prompt 即可 |
| 时延 | ★★★★☆ | 略高于裸调用（多出指令 token 的处理时间） |
| 精度 | ★★★☆☆ | 对于复杂任务上限较低 |
| 维护 | ★★★★☆ | prompt 版本管理简单，但迭代依赖主观判断 |

**3 个该用的场景**

1. **结构化输出格式化**：要求模型输出 JSON、XML 或特定模板。"你是一个解析器，把以下文本转成 `{"name": ..., "date": ...}` 格式。" 这类任务 prompt 就够，不需要 RAG 或 Fine-tune。

2. **语气/角色设定**：客服 bot 需要"友善、简洁、不道歉"的语气。在 system prompt 里写清楚比 fine-tune 快 100 倍，而且可以随时修改。

3. **思维链（CoT）激活**：给推理题加入思维链提示词（典型写法："think step by step"），o1 之前的模型准确率平均提升 15-30%（来源：Wei et al., 2022, [Chain-of-Thought Prompting Elicits Reasoning in Large Language Models](https://arxiv.org/abs/2201.11903)，不需要读完，只需要知道：给出思考步骤的指令能显著改善推理任务）。

**3 个不该用的场景**

1. **知识密集型问答**：如果用户问"我们公司 2024 年 Q3 的销售额是多少"，prompt 再好也无济于事——模型压根不知道这个数据。这是 RAG 的领地，不是 prompt 的。

2. **极高一致性要求的风格任务**：你想让所有输出都严格遵守某个特定写作风格（比如法律合同的标准措辞），即使每次塞入详细的 prompt，不同 token 采样下风格仍会飘移。这是 Fine-tune 能解决而 prompt 解决不好的场景。

3. **长期记忆任务**：用户希望 agent 记住三个月前说过的偏好。context window 是有限的，prompt engineering 无法解决跨会话的持久记忆问题。

---

### 4.2 路径二：Few-shot / In-Context Learning

**一句话定位**：Few-shot 是"给模型看例子"而不是"告诉模型怎么做"。当行为比语言更容易展示时，few-shot 比长篇指令更有效。但它的成本随示例数量线性增长，每加一个 shot，每次调用就多花那些 token。

**五维度打分**

| 维度 | 得分 | 说明 |
|------|------|------|
| 成本 | ★★★☆☆ | 每次调用携带示例 token，成本随 N 增长 |
| 数据要求 | ★★★★☆ | 需要 5-30 个高质量示例，比 Fine-tune 少得多 |
| 时延 | ★★★☆☆ | 每个 shot 增加约 200-500 token 的处理时间 |
| 精度 | ★★★★☆ | 示例质量高时，对格式/风格任务效果接近 Fine-tune |
| 维护 | ★★★★☆ | 示例库维护成本低，可以即时替换 |

**N-shot 的边界在哪里？**

Few-shot 有一条工程经验线：当示例数量超过 20-30 个时，继续增加示例的边际收益接近零，而成本继续线性增长。这个数字不是固定的，取决于任务复杂度，但它提示了一个决策点：**如果你已经在用 20+ shot，且效果还不理想，说明问题不在示例数量上，而在任务本身需要不同的路径。**

另一个边界是 context window。当示例总量 + 用户输入 + 系统提示超过约 60% 的 context window 时，模型的注意力会开始"迷失在中间"（Lost in the Middle，Shi et al., 2023），准确率下降。

**3 个该用的场景**

1. **快速适配新格式**：你有 10 个"好的"示例输出，想让模型模仿同样的格式和语气，但还没有足够数据做 fine-tune。Few-shot 是这段时间的最优解。

2. **低频专用任务**：某个任务每天只调用 50 次，用 fine-tune 的 ROI 极低，但 zero-shot 效果不稳定。Few-shot 用 20 个示例，每次多花 1000 token，每天 50 次调用只多花约 $0.05——完全合理。

3. **边界验证**：在投入 fine-tune 之前，用 few-shot 先验证任务是否可学习。如果 30-shot 效果还很差，fine-tune 大概率也没有用，说明任务定义本身有问题。

**3 个不该用的场景**

1. **高频调用 + 成本敏感**：当每天有 100 万次调用，每次携带 20 个 shot（约 2000 extra token），按 Claude Sonnet 输入定价，每天额外花约 $600，每月 $18000。这时 fine-tune 的一次性成本几乎必然更划算。

2. **需要精确记忆大量知识**：你的示例本质上是在试图让模型"记住"大量信息（比如 50 个产品的规格参数）。这不是 few-shot 的强项——模型会"压缩"这些信息，而不是精确记忆。这是 RAG 的场景。

3. **动态更新的知识**：如果示例内容需要每天更新（比如价格、库存），维护 few-shot 示例库本身成为负担。RAG 能从实时数据源检索，far better。

---

### 4.3 路径三：RAG（Retrieval-Augmented Generation）

**一句话定位**：RAG 是"在推理时给模型找资料"——模型不需要记住所有知识，但能在需要时检索到正确文档。它是 AI Agent 系统里出现频率最高的技术（LinkedIn JD 数据：75% 的 AI agent 岗位要求 RAG 经验），但它不是万能的：检索不到，RAG 就是一个昂贵的 prompt。

**五维度打分**

| 维度 | 得分 | 说明 |
|------|------|------|
| 成本 | ★★★☆☆ | 向量检索基础设施 + embedding API 成本 + 每次检索的 token 成本 |
| 数据要求 | ★★★☆☆ | 需要文档库，无需标注；但文档质量直接决定 RAG 质量 |
| 时延 | ★★★☆☆ | 多一次检索延迟（通常 50-200ms），多注入 context token |
| 精度 | ★★★★☆ | 知识密集任务上大幅优于纯 prompt；取决于检索质量 |
| 维护 | ★★★☆☆ | 索引需要随文档更新重建或增量更新 |

**RAG 的四个核心决策点**（实现细节在 Ch9，这里只给决策视角）

RAG 不是"接一个向量库"这么简单。它是四个独立工程决策的叠加：

1. **Chunk 策略**：文档怎么切割？固定长度（简单，质量中等）vs 语义分块（效果好，实现复杂）。错误的 chunk 策略会让关键信息跨 chunk 断裂，检索时两半都不够相关。

2. **Embedding 模型**：用哪个向量模型？OpenAI text-embedding-3-large 效果好但贵，本地 BGE-M3 适合中文但需要自己跑推理服务。向量维度越高，存储和检索成本越高。

3. **检索方式**：纯向量搜索 vs Hybrid Search（BM25 + 向量）。精确术语（产品型号、代码片段）用纯向量搜索会漏，Hybrid Search 能兜底。

4. **Rerank**：Top-K 检索后再用 Reranker 重排序。不做 Rerank 就直接用 Top-5 的话，排名第 5 的文档经常不够相关。

这四个决策点，每个都有"默认选项"（快速上线用），也有"优化选项"（精度优先用）。Ch9 会逐一展开。

**3 个该用的场景**

1. **企业知识库问答**：100 页内部 Wiki、1000 封历史邮件、500 个产品规格文档——这些信息太多塞进 prompt，太专有来训练通用模型，RAG 是唯一合理的选择。一个真实数据点：Anthropic 在其 Contextual Retrieval 博客中报告，在标准 RAG 基础上，为每个 chunk prepend 上下文摘要后，检索失败率降低约 49%（来源：[Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)）。

2. **实时/频繁更新的知识**：新闻、股价、用户行为数据——这些不可能 fine-tune（太慢太贵），不能纯 prompt（模型不知道），需要 RAG 实时检索。

3. **需要来源引用的场景**：法律、医疗、财务场景要求 agent 给出"哪句话来自哪个文档第几页"。RAG 天然支持这个，因为你知道是从哪个 chunk 检索来的；纯 prompt 和 fine-tune 都没有这个能力。

**3 个不该用的场景**

1. **文档质量极差的场景**：如果你的知识库充满格式混乱、信息过时、大量重复的文档，RAG 会把垃圾喂给模型，效果可能不如 zero-shot。"Garbage in, garbage out"在 RAG 里被放大了。

2. **推理密集型任务**：用户问"根据我公司的数据，如果增加 20% 预算，ROI 最优的投放渠道是什么？" RAG 能检索数据，但多步推理和决策是 Agent 的工作，不是 RAG 的工作。

3. **延迟极度敏感的场景**：实时语音对话（< 200ms 目标延迟）。向量检索 + rerank + token 注入很难在这个时间窗口内完成。这种场景要么用 fine-tune 把知识烧进模型，要么用纯 prompt 配合极小的专用上下文。

---

### 4.4 路径四：Agent（本书主线）

**一句话定位**：Agent 是"给 LLM 工具和循环"，让它能感知环境、执行动作、根据结果调整下一步。它是五条路径里能力边界最宽的，但也是复杂度最高、最难 debug 的。

**Convention**：
- **工作流（Workflow）** = 预定义的固定步骤序列，每步由 LLM 填充内容；
- **Agent** = LLM 自主决定步骤，能动态选择工具和调整路径。本书把两者统称为 Agent 路径，但在决策树里会区分。

**五维度打分**

| 维度 | 得分 | 说明 |
|------|------|------|
| 成本 | ★★☆☆☆ | 多轮 LLM 调用 + 工具调用成本，一次任务可能触发 10-50 次 LLM 调用 |
| 数据要求 | ★★★★☆ | 无需训练数据，但需要设计工具和 prompt |
| 时延 | ★★☆☆☆ | 多步执行，时延随步骤数累积；不适合实时响应 |
| 精度 | ★★★★★ | 在多步、不确定、需要工具的任务上是唯一有效路径 |
| 维护 | ★★☆☆☆ | 每次工具变化都需要重新评估 agent 行为；错误会在循环中放大 |

**"When Not to Use Agents"**

Anthropic 在 Building Effective Agents 里有一节专门讲不该用 agent 的场景，这是这本书里最被忽视的部分：

> "Agents are better suited for open-ended problems where it's difficult or impossible to predict the required number of steps, and where you can't hardcode a fixed path. This increased autonomy also comes with higher costs."

翻译成决策树语言：**如果任务的执行路径是可以预知的、步骤数是固定的、不需要动态决策——就不应该用 Agent，用工作流（workflow）即可。**

这是本章 Design Note 会详细展开的话题。现在先记住这条原则：Agent 的复杂度是代价，不是奖励。

**3 个该用的场景**

1. **多工具协同的开放式任务**："帮我调研竞争对手的定价策略，汇总成报告。" 这个任务需要搜索、阅读、提炼、写作，步骤数不固定，工具组合不可预知。这是 Agent 的主场。在真实系统里，这类研究任务的自动化程度可以达到以前需要 2-3 小时人工搜索的效果，压缩到 5 分钟。

2. **跨系统操作**："读我邮件里最近 10 封客户反馈，更新 CRM 里对应的字段，然后给需要跟进的客户发邮件。" 这个任务跨越邮件、CRM、发件三个系统，步骤数依数据而定，需要动态判断。workflow 无法胜任，agent 可以。

3. **长时间自主执行任务**：每天凌晨爬取行业新闻、分析关键信息、生成摘要、发送到指定频道——这类 always-on、无人值守、按事件触发的任务，只有 agent 能做，其他路径根本不具备这个能力。

**3 个不该用的场景**

1. **固定流程任务**："每次用户提交表单，把表单数据格式化后写入数据库。" 这是确定性两步操作，hardcode 成函数即可。用 agent 是过度工程，而且每次都触发 LLM 调用，每次多花约 $0.001——规模化后是纯粹的浪费。

2. **实时低延迟要求**：语音对话、游戏 NPC 实时反应（< 300ms）。Agent 的多步执行本质上是串行等待，无法满足这类时延要求。

3. **高确定性合规场景**：银行的贷款审批流程、医疗的检验结果解读——这些场景需要**完全可追溯**的决策路径和**零幻觉容忍**。当前 LLM 的可靠性还不能在零人工审核的情况下胜任这类场景（这是当前领域最没有好答案的问题之一，截至写作时最务实的做法是"人工在环 + agent 作为辅助"，而不是全自动 agent）。

---

### 4.5 路径五：Fine-tune

**一句话定位**：Fine-tune 是"改变模型本身"——不是调整输入，而是改变权重。它解决的是"模型的行为方式和风格"问题，不是"模型知道什么"问题。这个区别在现实中被大量忽视，是本节最重要的一点。

**五维度打分**

| 维度 | 得分 | 说明 |
|------|------|------|
| 成本 | ★★☆☆☆ | 训练成本（即使是 LoRA 也需要 GPU 时间）+ 托管推理成本 |
| 数据要求 | ★☆☆☆☆ | SFT 需要 500-5000 对高质量示例；DPO 需要偏好对比数据 |
| 时延 | ★★★★★ | 推理时延与基础模型相同，甚至更低（小模型 fine-tune）|
| 精度 | ★★★★★ | 在目标领域/风格上显著优于其他路径（前提是数据质量好）|
| 维护 | ★★☆☆☆ | 知识更新需要重训，catastrophic forgetting 需要持续监控 |

**SFT / DPO / LoRA 怎么选？**

这三者不是平行选项，而是不同层次的工具：

- **SFT（Supervised Fine-Tuning）**：给定输入，示范正确输出。适合"学会做某类任务"（如：写特定格式的报告）。
- **DPO（Direct Preference Optimization）**：给定两个输出，标注哪个更好。适合"调整风格偏好"（如：更简洁 vs 更详细）。
- **LoRA（Low-Rank Adaptation）**：SFT 或 DPO 的高效实现方式，在训练时只更新少量参数，大幅降低 GPU 成本和 catastrophic forgetting 风险。

> 本书不展开 Fine-tune 的实现细节——Raschka《Build an LLM from Scratch》和 Karpathy zero-to-hero 已经把这件事做得很彻底。本书专注的是 harness，Fine-tune 是边界外的工具。如果你的场景确实需要 Fine-tune，那两个资源是正确的去处。

**3 个该用的场景**

1. **特定领域术语和写作风格的高度一致性**：某法律公司的合同撰写风格有严格规范（用语、格式、条款顺序），few-shot 的稳定性不够，fine-tune 后的输出一致性显著高于 few-shot。

2. **高频调用的固定任务 + 成本敏感**：每天 100 万次调用的情感分析任务，用基础模型 + 详细 prompt 效果不稳定。Fine-tune 一个小模型（如 Llama 3.1-8B LoRA），推理成本降低 10 倍，且能部署到本地，消除 API 依赖。

3. **安全/合规要求导致不能调用外部 API**：金融机构、政府部门的数据不能发往外部 LLM API。在内部服务器 fine-tune 开源模型是唯一可行的路径。

**3 个不该用的场景**

1. **知识注入**：试图通过 fine-tune 让模型"记住"公司内部文档。Fine-tune 会让模型"倾向于某类回答"，但不能可靠地记住具体事实（日期、数字、名称）。知识注入是 RAG 的场景，不是 Fine-tune 的。这是社区最常见的误解，没有之一。

2. **快速迭代阶段**：产品还在 PMF 阶段，需求每周变化。Fine-tune 的数据准备和训练周期是以周为单位的，完全不能配合这个节奏。在需求稳定前，坚持用 Prompt Engineering + RAG。

3. **工具调用能力增强**：想让模型更好地调用工具？改进工具的文档和 schema 设计（ACI 原则）比 fine-tune 有效得多，成本低三个数量级。Fine-tune tool-use 能力是事倍功半的做法，尤其是现有主流模型（Claude、GPT-4o、Qwen3）的 tool-use 已经很强。

---

## Beat 5 — 名词速查：这章出现的所有术语

这一节是供参考的术语锚点。阅读本书后续章节时，如果遇到不确定的词，回这里查。

**Convention（本书统一定义）**：

- **Embedding** = 把文本转换成高维向量的过程；**向量**是结果，**embedding 模型**是工具。
- **Reranking** = 对检索结果进行二次排序，目标是把最相关的文档排到最前。（不是 embedding，是 cross-encoder 打分）
- **Hybrid Search** = 关键词搜索（BM25）+ 语义向量搜索的组合，取两者的并集后再 rerank。
- **Guardrails** = 对 agent 输入/输出的约束和过滤机制，保证 agent 不执行危险操作或生成有害内容。
- **Evals** = 对 LLM 系统性能的系统化评估，包括自动化测试集、LLM-as-judge、人工评审。
- **MCP（Model Context Protocol）** = Anthropic 提出的工具和上下文协议标准，让 LLM 能以统一方式连接外部工具和数据源。
- **ACP（Agent Communication Protocol）** = agent 之间通信的协议标准（标准化进行中）。
- **A2A（Agent-to-Agent）** = agent 之间直接交互和委托任务的机制，不通过统一协调层。
- **Observability** = agent 系统的可观测性，包括日志、trace、metric，让你知道 agent "在想什么、做了什么"。
- **ICL（In-Context Learning）** = 模型通过 context 里的示例学习，无需梯度更新权重。Few-shot 是其典型形式。
- **LoRA** = Low-Rank Adaptation，fine-tune 的高效实现方式。
- **SFT** = Supervised Fine-Tuning，监督微调。
- **DPO** = Direct Preference Optimization，通过偏好对比数据优化模型输出风格。
- **Catastrophic Forgetting** = fine-tune 时，模型在学习新任务的同时忘记原有能力的现象。
- **Context Rot** = 随着 context 变长，模型准确回忆早期信息的能力下降（来源：Anthropic Context Engineering）。

---

## Beat 6 — 选型决策树（印刷级）

Now let's build the decision tree. 从一个问题出发，走到最终路径推荐。

```
┌─────────────────────────────────────────────────────────────────┐
│                     技术选型决策树 v1.0                           │
│                                                                  │
│  起点：你有一个新的 LLM 需求                                       │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────┐
        │ Q1: 任务执行路径是否完全可预知？   │
        │ （步骤固定、不需要动态决策）       │
        └─────────────────────────────────┘
             │                    │
            YES                   NO
             │                    │
             ▼                    ▼
    ┌─────────────┐    ┌──────────────────────────┐
    │ → 工作流     │    │ Q2: 任务需要访问模型训练    │
    │ （hardcode  │    │     数据截止日之后的知识，   │
    │  步骤序列）  │    │     或组织内部专有信息？     │
    └─────────────┘    └──────────────────────────┘
                                │              │
                               YES             NO
                                │              │
                                ▼              ▼
                     ┌──────────────┐  ┌───────────────────────┐
                     │ Q3: 这些知识 │  │ Q5: 任务对输出风格/    │
                     │ 更新频率如何？│  │ 格式的一致性要求极高，  │
                     └──────────────┘  │ 且现有 prompt 方案     │
                       │         │     │ 稳定性不满足？          │
                      高          低   └───────────────────────┘
                       │          │              │              │
                       ▼          ▼             YES             NO
               ┌──────────┐  ┌──────────┐       │              │
               │ → RAG    │  │ Q4: 知识 │       ▼              ▼
               │ (实时索引) │  │ 量是否超  │  ┌─────────┐  ┌──────────────┐
               └──────────┘  │ 出 context│  │→ Fine-  │  │ Q6: 你有多少  │
                             │ 的 30%?   │  │  tune   │  │ 高质量示例？  │
                             └──────────┘  └─────────┘  └──────────────┘
                               │      │                    │          │
                              YES     NO                 5-30个      0-5个
                               │      │                    │          │
                               ▼      ▼                    ▼          ▼
                         ┌──────────┐ ┌──────────┐  ┌─────────┐  ┌────────────┐
                         │ → RAG    │ │→ Few-shot │  │→ Few-   │  │→ Prompt    │
                         │ (知识库  │ │ 或 Fine-  │  │  shot   │  │ Engineering│
                         │  索引)   │ │ tune 均可 │  └─────────┘  └────────────┘
                         └──────────┘ └──────────┘
                                           │
                                           ▼
                              ┌──────────────────────┐
                              │ 决策辅助：Fine-tune    │
                              │ 当调用频率 > 50万次/月 │
                              │ 优先 Fine-tune 节成本  │
                              │ 否则先 Few-shot        │
                              └──────────────────────┘
```

决策树也可以用代码表达，方便在团队评审时作为可执行文档：

```python
from dataclasses import dataclass
from typing import Literal

PathType = Literal["workflow", "rag_realtime", "rag_index", "fewshot_or_finetune",
                   "finetune", "fewshot", "prompt"]

@dataclass
class SelectionContext:
    """描述一个具体 LLM 需求的参数集合。"""
    path_predictable: bool        # 执行路径是否完全可预知（步骤固定）
    needs_external_knowledge: bool  # 是否需要训练截止日之后或内部专有知识
    knowledge_update_freq: Literal["high", "low"]  # 知识更新频率
    knowledge_exceeds_30pct_ctx: bool  # 知识量是否超出 context window 的 30%
    style_consistency_required: bool  # 输出风格/格式一致性要求极高
    example_count: int            # 可用高质量示例数量
    monthly_calls: int            # 每月调用次数


def select_path(ctx: SelectionContext) -> tuple[PathType, str]:
    """
    根据五维度上下文返回推荐路径及理由。
    对应 Beat 6 决策树的可执行版本。
    """
    if ctx.path_predictable:
        return "workflow", "步骤固定 → 硬编码工作流，无需 LLM 动态决策"

    if ctx.needs_external_knowledge:
        if ctx.knowledge_update_freq == "high":
            return "rag_realtime", "知识频繁更新 → RAG 实时索引"
        # 低频更新
        if ctx.knowledge_exceeds_30pct_ctx:
            return "rag_index", "知识量超出 context 30% → RAG 知识库索引"
        return "fewshot_or_finetune", "知识量可控 → Few-shot 或 Fine-tune 均可，按调用量决策"

    # 不需要外部知识
    if ctx.style_consistency_required:
        return "finetune", "风格一致性要求高 → Fine-tune 改变行为，优于 Few-shot"

    if ctx.example_count >= 5:
        # 有足够示例，按调用量选择
        if ctx.monthly_calls > 500_000:
            return "finetune", f"月调用 {ctx.monthly_calls:,} 次 → Fine-tune 摊薄 token 成本"
        return "fewshot", f"月调用 {ctx.monthly_calls:,} 次 + {ctx.example_count} 个示例 → Few-shot ROI 合理"

    return "prompt", "无外部知识需求 + 示例不足 → Prompt Engineering 起步"


# 使用示例：企业内部文档问答场景
ctx = SelectionContext(
    path_predictable=False,
    needs_external_knowledge=True,
    knowledge_update_freq="high",
    knowledge_exceeds_30pct_ctx=True,
    style_consistency_required=False,
    example_count=0,
    monthly_calls=10_000,
)
path, reason = select_path(ctx)
print(f"推荐路径: {path}")   # rag_realtime
print(f"理由: {reason}")
```

这段代码是决策树的可执行镜像，没有引入新逻辑——它只是把上面 ASCII 树的判断条件翻译成类型化的 Python 函数，方便在 code review 或架构评审中作为团队共识文档使用。

**叠加规则**：上面五条路径不是互斥的。最常见的生产架构是：

```
Agent（决策循环）
  ├── RAG 工具（知识检索）
  ├── Prompt Engineering（每个工具的 system prompt）
  └── 可选：Fine-tuned 骨干模型（对于极高频场景）
```

这个叠加结构覆盖了大多数真实 AI agent 产品的技术架构。本书 Ch6-Ch9 会逐层实现它。

**常见场景到路径的快速映射**

下表是决策树的速查版本，用于日常工程讨论：

| 场景描述 | 推荐路径 | 理由 |
|---------|---------|------|
| 格式化 / 结构化输出 | Prompt | 无需外部数据，调整指令即可 |
| 情感分析（百万次/天） | Fine-tune | 高频 + 固定任务，Fine-tune 摊薄成本 |
| 企业内部文档问答 | RAG | 专有知识，频繁更新，来源引用需求 |
| 代码调试 / 分析 | Agent + 工具 | 需要执行代码、读文件、迭代修改 |
| 语气/品牌风格统一 | Fine-tune 或 Few-shot | 风格问题（行为），不是知识问题 |
| 实时新闻摘要 | RAG（实时索引）| 知识时效性强，每天更新 |
| 跨系统自动化工作流 | Agent | 多工具、多步骤、不确定路径 |
| 低频但风格一致性高 | Few-shot | 频率低，Fine-tune ROI 不足 |
| 开放式研究任务 | Agent + RAG | 需要检索 + 多步推理 |
| 安全/合规（数据不出境） | Fine-tune（本地部署）| 数据主权要求 |

---

## Beat 7 — Design Note × 2

---

> ### Design Note 0：选型三角——能力、速度、成本
>
> Anthropic 在其架构白皮书中总结了模型选型的核心框架：**capabilities（能力）、speed（速度）、cost（成本）**三者构成一个不可调和的三角——在一个固定的模型家族里，你只能在三者之间权衡，无法同时最优。
>
> 白皮书用了一个直白的比喻：
>
> > "Think of it like choosing the right tool from a toolbox: you wouldn't use a sledgehammer to hang a picture frame."
>
> 这句话的工程含义是：**简单任务用轻模型（Haiku），复杂推理用重模型（Opus）——用贵模型跑简单任务"不只是浪费，规模化时成本会快速复利增长"**。
>
> 把这条原则翻译成本章的五条路径决策语言：当你选定了某条路径（比如 Agent），下一个问题不是"哪个模型最好"，而是"这个步骤的任务复杂度，需要多强的模型？" Orchestrator 负责规划（需要强推理能力，用 Sonnet 或 Opus），Worker 负责执行单个确定步骤（可用 Haiku），两者的成本差距通常在 5–20x。在一个有 10 个 Worker 并发的系统里，选错模型等于每次任务多花 10–20x 的成本。
>
> 实践规则：把每个 agent 步骤标注为"规划层"或"执行层"，前者用重模型，后者用轻模型。
>
> （来源：Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*, 2025, p.8）

---

> ### Design Note 1：架构选型三问框架 + Multi-agent 的隐性成本
>
> Anthropic 白皮书在讨论何时从 single agent 升级到 multi-agent 时，提出了一个三问决策框架（p.23）：
>
> 1. **控制需求有多高？** 高控制场景（合规审计、金融交易、医疗决策）→ 优先 Single agent + sequential workflow，每步可追溯、可审计、可回滚。Multi-agent 的自主性在这类场景是负担，不是优势。
> 2. **问题域有多复杂？** 单一领域任务（企业知识库问答、定向数据分析）→ Single agent 够用；跨领域需要协调（同时处理代码、财务、用户行为三个维度的分析）→ Multi-agent 的专业化分工才能体现价值。
> 3. **预算和 token 约束是什么？** Multi-agent 架构会消耗**单 agent 的 10-15 倍 tokens**——每个子 agent 都有自己的上下文窗口、system prompt 和工具调用开销。如果你的月 token 预算是 $500，上 multi-agent 之前要先做好 5-7 倍成本增长的预案。
>
> （来源：Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*, 2025, p.23）
>
> 这三个问题也给出了一条明确的演进路径：
>
> > "You can deploy a single agent in weeks. Multi-agent systems take months to get right. Build something that works, then enhance."
>
> 把这句话翻译成工程决策语言：先用 single agent 跑通任务、验证可行性、建立 eval baseline；等到单 agent 的瓶颈（并行度不够、某个子任务需要专业化模型）明确出现后，再做最小化的 multi-agent 改造。不要在还没遇到瓶颈时就把架构复杂化。
>
> 本章的五条技术路径选型，和上面的三问框架是互补的：五条路径解决的是"用什么技术手段"，三问框架解决的是"用几个 agent 来跑"——两个维度的选型都做对了，才算完整的架构决策。

---

> ### Design Note A：RAG vs Fine-tune：为什么社区误解这是二选一
>
> **你可能听过这个论断**："当你有足够多的数据时，应该做 Fine-tune 而不是 RAG——模型记住知识比每次检索更高效。"
>
> 这个论断的问题在于，它把两件完全不同的事混为一谈：
>
> - Fine-tune 解决的是**行为问题**：模型的输出风格、格式、推理倾向。
> - RAG 解决的是**知识问题**：模型在推理时能访问到什么信息。
>
> 现有证据（包括 Anthropic、OpenAI、Google DeepMind 的多篇研究）表明，fine-tune 并不能可靠地"记住"事实性知识，尤其是具体数字、日期、专有名词。它改变的是"倾向于这样回答"，而不是"精确知道这个数字是多少"。
>
> **实际工程策略（截至写作时的最佳实践）**：
>
> - 🟢 **几乎总是 RAG 先行**：任何需要访问外部知识的场景，先上 RAG。RAG 能解决的问题，不要绕到 Fine-tune。
> - 🟡 **Fine-tune 叠加 RAG**：当 RAG 的精度已经不错，但输出风格不稳定时，可以在 RAG 的基础上 fine-tune 一个更好的"格式化/风格化"层。
> - 🔴 **Fine-tune 替代 RAG**：这个组合几乎没有合理场景，除非你的知识库静态、不更新，且调用频率极高到 RAG 成本无法承受。
>
> **Tradeoff 总结**：
> - Fine-tune 不能热更新；RAG 可以（更换文档即可）
> - Fine-tune 需要大量标注；RAG 只需要文档
> - Fine-tune 推理快；RAG 需要检索延迟
> - Fine-tune 改行为；RAG 加知识
>
> 这不是二选一，是两把不同的锤子。在生产系统里，它们经常同时存在。

---

> ### Design Note B：Agent 不是银弹——Anthropic 说的
>
> **常见误解**：Agent 是"最强大的路径"，能解决所有 LLM 应用问题。
>
> **Anthropic 的官方立场**（来源：[Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)）：
>
> > "Many patterns can be implemented in a few lines of code...We recommend not using agentic frameworks, or using them very lightly, until you understand the underlying principles."
>
> Anthropic 明确列出了不该用 Agent 的特征：
> - 任务路径是可预知的 → 用 workflow，不用 agent
> - 任务步骤数固定 → 用 workflow，不用 agent
> - 错误成本极高（不可逆操作）→ 先穷尽确定性方案，用 agent 时强制加人工在环
>
> **Agent 的真正价值**在于"开放性"：当任务的步骤数不可预知、工具组合依情况而变、需要动态判断时，Agent 才是必要的而不是"更酷的"方案。
>
> **Tradeoff 总结**：
> - 🟢 Agent 能做到其他路径做不到的事：多步自主执行、工具组合、跨系统操作
> - 🔴 Agent 的成本倍增器：一次任务触发 10 次 LLM 调用 = 10 倍成本
> - 🔴 Agent 的错误放大器：每步的小错误会在循环中累积，最终导致完全偏离目标
> - 🔴 Agent 的 debug 难度：不确定性意味着复现困难，这是最没有好答案的工程问题之一
>
> 如果你在面对一个新需求时，第一反应是"用 Agent 做"，先停下来问一句："如果我把这个任务的步骤 hardcode 出来，写成函数，够用吗？"如果够用——就别用 Agent。

---

---

## 章末钩子

决策树有了，但树上的每个分支都是一扇还没打开的门。

最近的那扇门是 **Ch6：工具系统**——它是 Agent 路径的基础设施。你在决策树里选择了 Agent，下一步就是搞清楚"工具"这个概念的边界：什么是工具，工具怎么注册，工具怎么并发执行，工具怎么安全地暴露给 LLM。

Lena 在 Ch3 只有一个工具（`get_time`）。Ch6 结束时，她会有四个工具，并且拥有一套"加工具不改核心"的注册机制——这是从个人玩具到生产系统的第一步。

---

*本章来源依据：*
*- Anthropic Engineering Blog: [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)*
*- Anthropic Engineering Blog: [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)*
*- Anthropic Engineering Blog: [Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)*
*- Wei et al. (2022). Chain-of-Thought Prompting Elicits Reasoning in Large Language Models. [arXiv:2201.11903](https://arxiv.org/abs/2201.11903)*
*- 基于对 26 份 AI Agent 岗位描述的共性分析*
*- Prompt Engineering Guide / DAIR.AI: guides/fewshot.en.mdx, guides/rag.en.mdx（本地 clone）*
