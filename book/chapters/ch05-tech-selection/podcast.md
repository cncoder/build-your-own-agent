【窦文涛】今天讲一道工程师在 AI 项目头三十分钟里最容易答错的选择题。你面前有五条路：Prompt Engineering、Few-shot、RAG、Agent、Fine-tune。选对了，可能几小时出活；选错了，两到四周的时间白白扔进去，或者每个月多烧几百美金的冤枉钱。这是《从零构建你的 AI Agent》第五章，核心产物是一张可以打印出来用的选型决策树。

【窦文涛】先说清楚 Lena 在本章的位置。她在 Ch3 末尾能跑通一次工具调用，现在你想让她做更多事——回答内部文档问题、用特定风格写邮件、自主执行多步任务。在动手之前先停下来问：你打算走哪条路？

【窦文涛】这不是哲学问题，是工程决策。不同路径的成本相差十倍，数据需求相差一千倍，时延相差五倍。选错了不是"不够好"，是"做了再改"——而"改"在 LLM 系统里意味着从头评估、重建索引、或者重新训练。

【窦文涛】先建动机，看两个真实的代价数字。一个初始规模的 LoRA fine-tune 实验，数据清洗加标注加训练加评估，至少需要两到四周。如果最终发现"其实用 RAG 加好的 Prompt 就够了"，这几周的沉没成本无法回收。更糟的是，fine-tuned 模型是静态的，知识在训练截止日冻结，每次知识更新都要重训。

【窦文涛】反方向的代价同样具体。一个本该用 Fine-tune 的风格化任务——比如"用我公司客服的语气回复"——如果强行用 few-shot，每次调用要塞入二十个示例，每个 API 请求多花约两千 token。按 Anthropic Claude Sonnet 定价折算，一百万次调用多花约六百美元，而且还没解决风格一致性问题。两个陷阱、两个方向，选型错了，要么浪费时间，要么持续浪费钱。

【窦文涛】在讲决策树之前先做理论铺垫，因为很多选型错误的根源是术语模糊。本章用"路径"指代五种顶层选择，用"策略"指代同一路径下的具体实施方式——比如 Few-shot 是 Prompt Engineering 的策略之一。五条路径的本质差异可以用一张表格总结：Prompt Engineering 改变的是输入格式和指令；Few-shot 改变的是输入中的示例内容；RAG 在推理时动态注入外部知识；Agent 给模型工具和循环改变行动能力；Fine-tune 改变的是模型本身的权重。

【窦文涛】这五条路径在概念上独立，但工程上经常叠加：一个 Agent 可以内嵌 RAG 作为工具，RAG 的文档过滤可以用 Prompt Engineering 优化，Fine-tune 的结果可以作为 Agent 的骨干模型。它们不是互斥选项，但选型时要分清主路径。

【窦文涛】要做有依据的选型，需要五维度评估框架。本章用这五个维度：成本，指每次推理的 API 费用加工程维护成本；数据要求，指需要准备的标注数据量；时延，指端到端响应时间；精度，指在目标任务上的准确率；维护，指系统上线后的持续维护复杂度。打分用一到五，一代表代价最低，五代表代价最高。Anthropic 在 Building Effective Agents 里的核心原则是："Success in the LLM space isn't about building the most sophisticated system. It's about building the right system for your needs."

【窦文涛】先讲两个反直觉事实，因为这两个误解造成了最多错误选型。第一个：Fine-tune 不是"更高级的 Prompt Engineering"。乍看它像是把 Prompt 烧进模型权重，但实际上它更像给模型做手术。手术后模型的通用能力可能衰退——这就是 catastrophic forgetting，模型在目标任务变好了，通用推理能力反而退化。而且每次知识更新都要重做手术。Fine-tune 解决的是风格、格式、领域术语问题，不是知识更新问题。

【窦文涛】第二个反直觉事实：Agent 不是"更复杂的 RAG"。Agent 更像一个操作系统进程：它有循环、有状态、有行动能力，错误会在循环中放大。RAG 的错误只在单次检索上体现。Anthropic 在 Building Effective Agents 里明确警告"adding unnecessary framework layers"是反模式。含义是：在上 Agent 之前先穷尽简单方案。

【窦文涛】进入五条路径具体解析。路径一：Prompt Engineering。五维度打分，成本和数据要求都是一颗星，几乎零额外成本；时延四颗星，略高于裸调用；精度三颗星，复杂任务上限较低；维护四颗星，迭代依赖主观判断。

【窦文涛】Prompt Engineering 有三个典型的该用场景。第一，结构化输出格式化，要求模型输出 JSON 或特定模板，这类任务 Prompt 就够。第二，语气和角色设定，客服机器人需要"友善、简洁、不道歉"的语气，在 system prompt 里写清楚比 fine-tune 快一百倍且可随时修改。第三，思维链激活，加上逐步思考的指令，Wei 等人 2022 年在 arxiv:2201.11903 发表的研究表明，CoT 提示能将推理任务准确率提升十五到三十个百分点。

【窦文涛】Prompt Engineering 不该用的三个场景：知识密集型问答，模型不知道的事 Prompt 再好也没用，这是 RAG 的领地；极高一致性要求的风格任务，不同 token 采样下风格仍会飘移，需要 Fine-tune 解决；长期记忆任务，context window 是有限的，无法解决跨会话的持久记忆问题。

【窦文涛】路径二：Few-shot，也叫 In-Context Learning，ICL。一句话定位：给模型看例子而不是告诉模型怎么做。当行为比语言更容易展示时，Few-shot 比长篇指令更有效。但成本随示例数量线性增长，每加一个 shot 每次调用就多花那些 token。

【窦文涛】Few-shot 有一条工程经验线：当示例数量超过二十到三十个时，继续增加示例的边际收益接近零，成本继续线性增长。这是一个决策点：如果你已经在用二十个以上的 shot 且效果还不理想，说明问题不在示例数量上，任务本身需要不同的路径。另一个边界是 context window——当示例总量超过约百分之六十的 context window 时，模型注意力会"迷失在中间"，准确率下降。

【窦文涛】Few-shot 该用的三个场景：快速适配新格式，还没有足够数据做 fine-tune 的早期阶段；低频专用任务，每天五十次调用，多花约零点零五美元完全合理；边界验证，在投入 fine-tune 之前先用三十个 shot 验证任务是否可学习，如果三十 shot 效果还很差说明任务定义本身有问题，fine-tune 大概率也没用。Few-shot 不该用的场景：高频调用加成本敏感，每天一百万次调用携带二十个 shot 每月多花约一万八千美元；以及需要精确记忆大量事实信息，这是 RAG 的场景。

【窦文涛】路径三：RAG，Retrieval-Augmented Generation，检索增强生成。一句话定位：在推理时给模型找资料，模型不需要记住所有知识，能在需要时检索到正确文档。它是 AI Agent 系统里出现频率最高的技术，但检索不到，RAG 就是一个昂贵的 Prompt。

【窦文涛】RAG 有四个核心工程决策点。第一，Chunk 策略，文档怎么切割，固定长度简单但质量中等，语义分块效果好但实现复杂；错误的 chunk 策略会让关键信息跨 chunk 断裂，检索时两半都不够相关。第二，Embedding 模型选择，OpenAI text-embedding-3-large 效果好但贵，本地 BGE-M3 适合中文但需要自己跑推理服务。

【窦文涛】RAG 的第三个决策点是检索方式。纯向量搜索对精确术语，比如产品型号、代码片段会漏检。Hybrid Search，也就是 BM25 关键词搜索加语义向量的组合，能兜住这类情况。第四个决策点是 Reranking，对 Top-K 检索结果进行二次排序。Reranking 不是 embedding，是用 cross-encoder 打分，把最相关的文档排到最前。不做 Rerank 直接用 Top-5 的话，排名第五的文档经常不够相关。

【窦文涛】RAG 有一个有价值的数字：Anthropic 在 Contextual Retrieval 博客里报告，为每个 chunk 加上上下文摘要后，检索失败率降低约百分之四十九。这说明 RAG 的质量上限不是由向量库决定的，而是由 chunk 的信息完整性决定的。RAG 该用的场景：企业知识库问答、实时频繁更新的知识、以及需要来源引用的法律医疗财务场景。

【窦文涛】RAG 不该用的三个场景：文档质量极差时，RAG 会把垃圾喂给模型，效果可能不如 zero-shot；推理密集型任务，RAG 能检索数据但多步推理是 Agent 的工作；以及延迟极度敏感的场景，向量检索加 rerank 加 token 注入很难在两百毫秒内完成，这种场景要么用 Fine-tune，要么用纯 Prompt 配合极小的专用上下文。

【窦文涛】路径四是 Agent，本书主线。一句话定位：给 LLM 工具和循环，让它能感知环境、执行动作、根据结果调整下一步。五条路径里能力边界最宽，但复杂度最高、最难 debug。工作流（Workflow）是预定义的固定步骤序列，每步由 LLM 填充内容；Agent 是 LLM 自主决定步骤，能动态选择工具和调整路径。本章把两者统称 Agent 路径，但在决策树里会区分。

【窦文涛】Anthropic 在 Building Effective Agents 里专门讲不该用 Agent 的场景，原文是："Agents are better suited for open-ended problems where it's difficult or impossible to predict the required number of steps, and where you can't hardcode a fixed path." 决策语言版本：如果任务路径可预知、步骤数固定、不需要动态决策，就用工作流，不要上 Agent。Agent 的复杂度是代价，不是奖励。

【窦文涛】Agent 该用的三个场景：多工具协同的开放式任务，比如调研竞品定价策略并汇总报告，步骤数不固定工具组合不可预知；跨系统操作，读邮件更新 CRM 发邮件，横跨三个系统且步骤数依数据而定；以及 always-on 长时间自主执行任务，每天凌晨爬取行业新闻分析后发送到指定频道，只有 Agent 能做，其他路径根本不具备这个能力。

【窦文涛】Agent 不该用的三个场景：固定流程任务，把表单数据格式化写入数据库，hardcode 成函数即可，用 Agent 是过度工程，每次触发 LLM 调用是纯粹浪费；实时低延迟要求，语音对话三百毫秒以内，Agent 的多步串行执行根本无法满足；高确定性合规场景，银行贷款审批、医疗检验结果，截至写作时最务实的做法是人工在环加 Agent 作为辅助，而不是全自动 Agent。

【窦文涛】路径五：Fine-tune。一句话定位：改变模型本身，不是调整输入而是改变权重。它解决的是"模型的行为方式和风格"问题，不是"模型知道什么"的问题。这个区别在现实中被大量忽视，是本路径最重要的一点。

【窦文涛】Fine-tune 有三种常见实现方式，不是平行选项而是不同层次工具。SFT，即 Supervised Fine-Tuning，给定输入示范正确输出，适合"学会做某类任务"。DPO，即 Direct Preference Optimization，给定两个输出标注哪个更好，适合"调整风格偏好"。LoRA，即 Low-Rank Adaptation，是 SFT 或 DPO 的高效实现方式，只更新少量参数，大幅降低 GPU 成本和 catastrophic forgetting 风险。

【窦文涛】Fine-tune 该用的三个场景：特定领域术语和写作风格的高度一致性，比如法律合同标准措辞，Few-shot 稳定性不够；高频调用的固定任务加成本敏感，每天一百万次调用的情感分析，Fine-tune 一个小模型推理成本可降低十倍还能消除 API 依赖；以及安全合规要求不能调用外部 API，在内部服务器 Fine-tune 开源模型是唯一可行路径。

【窦文涛】Fine-tune 最常见的三个错误使用场景。第一，知识注入：试图通过 Fine-tune 让模型记住公司内部文档。Fine-tune 会让模型倾向于某类回答，但不能可靠记住具体事实，日期、数字、名称。知识注入是 RAG 的场景，不是 Fine-tune 的，这是社区最常见的误解，没有之一。第二，快速迭代阶段，产品还在 PMF 阶段需求每周变化，Fine-tune 的数据准备和训练周期以周为单位，完全配合不了这个节奏。第三，工具调用能力增强，改进工具的文档和 schema 设计比 Fine-tune 有效，成本低三个数量级。

【窦文涛】五条路径都看完了，进入本章核心产物：决策树。从一个问题出发走到最终路径推荐。第一问：任务执行路径是否完全可预知，步骤固定、不需要动态决策？如果是，直接用工作流，hardcode 步骤序列即可，不要上 Agent。

【窦文涛】如果路径不可预知，进入第二问：任务需要访问模型训练数据截止日之后的知识，或组织内部专有信息吗？如果是，进第三问：这些知识更新频率高吗？频率高选 RAG，可以实时更新索引；频率低但知识量超出 context 百分之三十的也选 RAG；频率低且知识量不大，Few-shot 或 Fine-tune 均可，再看调用频率超过五十万次每月优先 Fine-tune 节成本，否则先 Few-shot。

【窦文涛】如果任务不需要外部知识，进第五问：对输出风格或格式一致性要求极高且现有 Prompt 方案稳定性不满足吗？如果是，选 Fine-tune，因为这是行为问题；如果不是，进第六问：有多少高质量示例？五到三十个选 Few-shot，零到五个先用 Prompt Engineering。决策树有叠加规则：最常见的生产架构是 Agent 决策循环加 RAG 工具加 Prompt Engineering 加可选的 Fine-tuned 骨干模型，这个结构覆盖大多数真实 AI Agent 产品的技术架构。

【窦文涛】决策树背后有三个 Design Note 值得展开。第一个：选型三角，能力、速度、成本三者构成不可调和的三角。Anthropic 白皮书用了一个直白比喻："Think of it like choosing the right tool from a toolbox: you wouldn't use a sledgehammer to hang a picture frame." 工程含义是：简单任务用轻模型，复杂推理用重模型。用贵模型跑简单任务规模化时成本会快速复利增长。

【窦文涛】把选型三角翻译成 Agent 决策语言：当你选定 Agent 路径之后，下一个问题不是"哪个模型最好"，而是"这个步骤需要多强的模型"。Orchestrator 负责规划，需要强推理能力，用 Sonnet 或 Opus；Worker 负责执行单个确定步骤，可用 Haiku。两者的成本差距通常在五到二十倍。在一个有十个 Worker 并发的系统里，选错模型等于每次任务多花十到二十倍的成本。实践规则：把每个 Agent 步骤标注为规划层或执行层，前者用重模型，后者用轻模型。

【窦文涛】第二个 Design Note：从 single agent 升级到 multi-agent 的三问框架。Anthropic 白皮书提出：控制需求有多高，高控制场景优先 single agent 加顺序工作流；问题域有多复杂，单一领域 single agent 够用，跨领域才需要 multi-agent；预算和 token 约束是什么，multi-agent 会消耗单 agent 的十到十五倍 token，每个子 agent 都有自己的上下文窗口和工具调用开销。

【窦文涛】三问框架给出了一条明确的演进路径。白皮书原话是："You can deploy a single agent in weeks. Multi-agent systems take months to get right. Build something that works, then enhance." 先用 single agent 跑通任务、验证可行性、建立 eval baseline；等到单 agent 的瓶颈明确出现后，再做最小化的 multi-agent 改造，不要在还没遇到瓶颈时就把架构复杂化。

【窦文涛】第三个 Design Note：RAG 和 Fine-tune 为什么不是二选一。社区有一个错误论断："有足够数据时应该做 Fine-tune 而不是 RAG，模型记住知识比检索更高效。"错误在于它把行为问题和知识问题混为一谈。Fine-tune 改变的是行为，RAG 提供的是知识。现有研究表明 Fine-tune 不能可靠地记住事实性知识，尤其是具体数字、日期、专有名词。

【窦文涛】实际工程策略就三条：几乎总是 RAG 先行，任何需要访问外部知识的场景先上 RAG；Fine-tune 叠加 RAG，当 RAG 精度已经不错但输出风格不稳定时，可以在 RAG 基础上 Fine-tune 一个格式化风格化层；Fine-tune 替代 RAG 这个组合几乎没有合理场景，除非知识库完全静态不更新且调用频率极高到 RAG 成本无法承受。

【周迅】涛哥，有没有一句话概括今天的核心？

【窦文涛】有。不要问"该用什么技术"，要问"我的系统缺什么"：缺知识用 RAG，缺行为用 Fine-tune，缺行动能力用 Agent，都不缺就优化 Prompt。复杂度是负债不是资产，能用工作流解决的别上 Agent，能用 Prompt 解决的别上 RAG。永远从最简单方案建立基线，但诊断清楚了就直接跳到正确答案，别沿阶梯一级一级爬。

【窦文涛】Lena 在本章不写新代码，但完成后她拥有了理性选型能力：用五维度打分框架在五条路径中做有依据的选择，而不是本能地选"最熟悉的路"。这是通用 Agent 架构决策能力的第一层，也是 Ch6 之后每章选技术手段的判断基础。决策树有了，树上的每个分支都是一扇还没打开的门，最近的那扇门是 Ch6：工具系统，它是 Agent 路径的基础设施，也是 Lena 从"只会聊天"变成"什么都能做"的第一步。

---

*约 4600 字 / 预计 TTS 时长 ~31 分钟（语速 1.1x）*
