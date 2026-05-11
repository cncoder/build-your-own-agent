【窦文涛】今天讲一个问题：为什么 ChatGPT 帮不了你真正做事？你让它帮你清理三个月没修改的日志文件，它给你一条命令，让你自己去跑。任务没完成——它给建议，不做事。这不是模型不够聪明，换 GPT-4o、Claude Opus 也一样，回答更详细，但结构相同：**给建议，不做事**。根本原因是结构性的，单次 API 调用缺少"执行→观察→再推理"的回路。

【周迅】所以问题不是模型不够强，而是结构上缺了什么？

【窦文涛】差异就在这个回路。Chat 是一次性推理，你问我答，结束。Agent 有一个持续的循环——每次推理之后立刻行动，每次行动之后立刻观察，观察结果成为下次推理的起点。这条"推理→行动→观察→推理→……"的链条就是本章核心：ReAct 循环。来源是 2022 年普林斯顿和 Google Research 团队发表的论文 ReAct: Synergizing Reasoning and Acting in Language Models（arxiv: 2210.03629，ICLR 2023）。

【窦文涛】这篇论文用数字证明了这个回路的价值。在 ALFWorld 决策任务上，ReAct 比模仿学习基线高出 **34 个百分点**的绝对成功率；在 HotpotQA 多步问答上，ReAct 显著超过纯推理的 Chain of Thought，而且解决了 CoT 容易产生幻觉的问题。34 个百分点不是边际改进，是结构跃升。背后原因简单：多步推理任务需要中间状态，中间状态必须来自真实的外部反馈，不能靠模型内部"想象"。

【窦文涛】ReAct 有三个节点，直觉上很好理解。**Thought（推理）**：LLM 的内心独白——它看到当前状态，想清楚下一步要做什么。**Action（行动）**：LLM 发出工具调用请求，注意这一步 LLM 只是请求执行，它自己不能运行代码，工具调用是发给外部执行器的指令。**Observation（观察）**：工具真实执行后把结果返回给 LLM，这是真实世界的反馈，不是 LLM 猜的。

【窦文涛】三个节点首尾相连。每次 Observation 被追加到 messages 数组，下一轮 Thought 就能看到它。循环在 LLM 判断"任务完成"时退出。**聊天机器人没有这个循环，每次一次性推理；agent 有这个循环，能基于真实反馈持续推理直到完成任务**——这是两者的结构差异，不是智能差异。

【周迅】那 LLM 自己没记忆，怎么知道上一轮发生了什么？

【窦文涛】理解 ReAct 的另一个视角是把 messages 数组想象成**账本**。每次循环，账本里都会新增几条记录：先是 assistant 消息（Thought + Action），然后是 user 消息（Observation，即 tool_result）。账本是 LLM 每次推理的唯一输入，LLM 没有独立记忆，它只能看到 messages 数组里的内容。每次循环的 Observation 被追加进去，就成了下一轮推理的基础。

【窦文涛】账本里的 tool_result 来自真实的工具执行，不是 LLM 自己生成的——这是 ReAct 比"让 LLM 假装执行工具"更可靠的根本原因：每一步推理都锚定在真实世界的反馈上，而不是模型内部的想象。这里有一个让初学者困惑的细节：工具结果消息的 `role` 是 `"user"` 不是 `"tool"`，因为 Anthropic 把工具结果看作"环境给 LLM 的反馈"，与用户消息同侧——下面讲协议差异时会把这个和 OpenAI 的设计对比清楚。

【窦文涛】先看最小的代码骨架。一个有效的 ReAct 循环只需要五步：把用户消息加入 messages 账本；循环开始，用当前 messages 调用 LLM 得到 Thought 和可选的 Action；如果没有 Action 就是最终回复，退出循环；如果有 Action 就执行工具得到 Observation；把 Observation 加入 messages 账本，回到循环头。就这五步，核心 Python 代码二十行左右，`for step in range(max_steps)`，循环里判断 `stop_reason`，执行工具，追加 tool_result。

【窦文涛】有两个细节特别重要。第一，**`stop_reason == "end_turn"` 是出口**，不是 `"tool_use"`。Anthropic API 用 stop_reason 告诉你为什么停止：`"tool_use"` 意味着 LLM 想调用工具，循环继续；`"end_turn"` 意味着 LLM 认为任务完成，循环退出。

【窦文涛】第二，**Observation 的 role 是 `"user"`**。这是 Anthropic 的设计——工具结果被包在 user 消息里，content 数组里有 `type: "tool_result"` 的 block。OpenAI 的设计不同，它用 `role: "tool"`，这个差异是跨厂商 agent 开发的常见踩坑点。

【周迅】如果一次要查时间又要算数，两个工具同时调，消息怎么发？

【窦文涛】Anthropic API 允许 assistant 一次回复里同时请求多个工具调用——content 数组里有多个 `tool_use` block。对应地，所有 tool_result 必须收集到一个列表，追加为**一条** user 消息，不是多条。如果你对每个工具单独追加一条 user 消息，就违反了 user/assistant 严格交替规则，API 会返回 400 错误。这是最常见的 bug 来源。另一个配对规则：每个 `tool_result` 通过 `tool_use_id` 和对应的 `tool_use` block 配对，顺序无关，ID 匹配才重要。

【窦文涛】trace 调试是 ReAct 开发的必备技能。当 agent 行为诡异时，答案永远在 messages 数组里。在代码里加一行 `print(json.dumps(messages, indent=2, default=str))` 就能打印完整 trace。阅读 trace 时有三个检查点：user/assistant 是否严格交替；每个 tool_use 的 ID 是否恰好有一个对应的 tool_result 引用；包含 tool_result 的 user 消息是否用了数组格式而不是纯字符串。这三个地方出问题，排查起来都不直观，但根因相同。

【窦文涛】骨架往里加特性，每次只加一个。先加工具注册表，用字典 `TOOL_REGISTRY = {"get_current_time": fn}` 做派发，execute_tool 函数查字典调用；再加 max_steps 保护，无限循环是生产事故的常见来源，没有 max_steps 的 agent 在 2024 年烧掉过数百美元 API 费用；再加工具执行错误捕获，try/except 包裹工具调用，错误信息写入 tool_result 的 content，LLM 在下一轮看到错误后通常能改变策略；最后加 stop_reason 断言防止静默跳过未知状态。

【窦文涛】现在讲 Anthropic 和 OpenAI 的 Tool Use 协议差异，这是构建跨厂商 agent 必须掌握的。四个关键点。**关键点一：工具定义字段名不同**，Anthropic 用 `input_schema`，OpenAI 用 `function.parameters`，内容都是 JSON Schema。

【窦文涛】**关键点二：工具调用参数格式不同**，Anthropic 的 `input` 是结构化 JSON 对象，直接用；OpenAI 的 `arguments` 是字符串化 JSON，必须 `json.loads()` 后才能用，漏掉这步会拿到字符串而不是 dict，后续 `args["city"]` 报错，在日志里看起来莫名其妙。

【窦文涛】**关键点三：工具结果的 role 不同**，Anthropic 把工具结果放在 user 消息里的 tool_result block，OpenAI 用独立的 role="tool" 消息。这就是"为什么是 user"的完整答案。**关键点四：助手消息结构不同**，Anthropic 的 content 是数组可以同时包含文本和工具调用，OpenAI 的 content 是字符串工具调用在独立的 tool_calls 数组。如果你要构建支持多家 API 的 agent，最干净的做法是在 Provider 抽象层里统一这些差异，上层的 ReAct 循环代码完全不感知用的是哪家 API。

【周迅】那是不是所有场景都该用 ReAct？什么时候其实不需要这么复杂？

【窦文涛】Anthropic 2024 年 12 月发布的 Building Effective Agents 把 agent 系统总结为五大工作流模式，复杂度从低到高：**Augmented LLM**（单步增强，不循环）→ **Prompt Chaining**（固定步骤序列）→ **Routing**（LLM 分类器选路径）→ **Parallelization**（子任务并行）→ **Orchestrator-Workers**（主控 LLM 自主拆解，子 agent 执行）。

【窦文涛】这五级是选择题，不是必选项。Anthropic 在同一篇文章里立下铁律：**能不用 agent 就别用**，多数场景单次 LLM 调用已经够了；如果确实需要，选择能解决问题的最简架构。

【窦文涛】ReAct 和五大模式的关系：ReAct 是 Orchestrator-Workers 模式（最复杂的一级）的底层机制。五大模式是从系统架构层面对循环的组合与扩展，ReAct 是各模式内部的基本单元。能用 Prompt Chaining 解决的问题，不要上 ReAct 循环；能用 Routing 解决的问题，不要上 Parallelization。每升一级，复杂度翻倍，可调试性减半。这句话的操作含义是：技术选型从最简单的开始。

【窦文涛】现在讲 Beat 7——为什么不用 Plan-and-Execute？Plan-and-Execute 的思路是先让 LLM 生成完整的步骤列表，再按顺序逐步执行，中途不修改计划。乍看比 ReAct"更有条理"。以"清理三个月没修改的日志文件"为例，计划可能是：第一步列出文件，第二步筛选，第三步删除。执行时发现步骤一有子目录和权限问题，步骤二有 audit log 不该删，但步骤三的指令已经固定是"删除"。**核心问题：计划是对未来世界的假设，而未来世界不可预测**。

【窦文涛】ReAct 的每一步 Thought 都能基于 Observation 重新推理。发现 audit log？直接在 Thought 里改变决策，不删。发现权限错误？下一步 Thought 里请求提权。Plan-and-Execute 在信息不完整的时候就把所有决策锁死了，这是它输给 ReAct 的根本原因。

【窦文涛】Anthropic 在 Building Effective Agents 里说："Start with simple prompts and add multi-step agentic systems only when simpler solutions fall short."——先从简单 prompt 开始，只在简单方案确实不够用时才上 agent。ReAct 是正确的下一步，不是默认选项。

【窦文涛】Plan-and-Execute 什么时候比 ReAct 好？两种情况：第一，步骤完全确定且可预知，把 100 个 CSV 文件转 JSON，每个处理方式相同，不需要动态决策，Plan-and-Execute 效率更高，少一半 LLM 调用成本减半；第二，需要人类审批工作流，先出 Plan 给人确认再执行，ReAct 循环在中途等待人工审批的工程实现比较复杂。总结：**ReAct 适合探索性、动态的任务，Plan-and-Execute 适合结构化、可预测的任务**。

【窦文涛】Plan-and-Execute 和 ReAct 代表了两种不同的智能倾向：前者是"先想好再做"，后者是"边做边想"。聊完这两者的边界，自然引出一个更大的问题：Observation 能不能来自 agent 自己的反思，而不只是工具的返回？Shinn et al., 2023 年的 Reflexion 论文（arxiv: 2303.11366）就做了这件事——让 agent 对自己的失败经历生成语言形式的"反思"，把反思存入记忆，下次遇到类似情况时从记忆里检索。本质上是把 Observation 的范围从"工具结果"扩展到"自我评估结果"，这是 Ch 09 记忆系统要深入的方向。

【窦文涛】三个工程挑战需要记住。**无限循环风险**：没有 max_steps 的 agent 循环会因工具一直报错陷入"重试→失败→重试"死循环，max_steps 是必须的不是可选的。**幻觉工具**：LLM 可能请求一个你没注册的工具，execute_tool 返回错误信息，LLM 在下一轮看到错误后通常能调整策略，错误也是信息，这是 ReAct 的优雅属性。**上下文膨胀**：每轮循环追加两条消息，50 步任务有 100+ 条记录，超出 context window 后 LLM"忘记"了之前的操作，这是 Ch 10 Context Engineering 要解决的核心问题。

【窦文涛】本章的核心产物是一张手绘状态机图：三个节点 Thought/Action/Observation，节点间有向箭头，两个出口（任务完成和 max_steps 超限），每个节点旁边标注输入和输出是什么。这张图不是装饰，是下一章写代码的设计文档。

【周迅】那开头那个清理日志文件的场景，有了 ReAct 之后会怎样？

【窦文涛】回到开头那个场景：清理三个月没修改的日志文件。有了 ReAct 循环，Lena 不再给你一条命令让你自己跑——她会先 Thought"需要知道哪些文件符合条件"，然后 Action 执行 find 命令，Observation 看到结果里有 audit log，再 Thought"这个不该删"，改变决策只清理其他文件，最后告诉你"已清理 3 个文件，1 个 audit log 保留"。任务完成了，不是给建议。这一章 Lena 从 v0.1 升到 v0.2，代码文件没变，但你对它的理解发生了质变。

【窦文涛】三个验证标准：能用一句话向非技术朋友解释为什么 agent 需要循环，对方听懂；打开任意 agent 框架源码，30 秒内找到 while 循环、工具调用、结果追回 messages 三个位置；给一个你熟悉的 AI 产品说出它属于 Anthropic 五大模式哪一级，为什么。三个都做到，Ch 02 就真正完成了。下一章，50 行 Python，Lena 从 v0.2 变成 v0.3，第一次真正"做事"。
