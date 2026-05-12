# 第 10 章播客脚本：上下文工程——Token 经济学

> 风格：tutorial（科普教学）
> 主持人：涛哥（窦文涛）≥95% + 小周（周迅）<5%
> 时长目标：约 25 分钟
> 人名规则：Bob 代替任何真实工程师名，绝不出现作者名

---

【窦文涛】听众朋友好，欢迎来到《从零构建你的 AI Agent》配套播客。我是涛哥。今天讲第 10 章——上下文工程，副标题是 Token 经济学。到本章为止，Lena 已经是 v0.9：能记忆、会 RAG 检索、工具调用顺畅。但有个要命的问题一直没解决——她跑十轮没事，跑三十轮就崩溃。学完这一章，Lena 升级到 v0.10，能维持五十轮对话不溢出，token 成本最多削减 90%。

【窦文涛】先看一组真实的数字感受问题规模。让 Lena v0.9 跑重工具任务——每轮读取文件、执行 shell 命令：第 1 轮约 1800 tokens，第 10 轮约 18000 tokens，第 20 轮约 52000 tokens，第 30 轮约 98000 tokens，第 35 轮：`anthropic.BadRequestError: prompt_too_long`。崩溃。

【窦文涛】崩溃的根源不是逻辑 bug，而是一个只会追加、没有泄压阀的 `messages[]` 列表的必然结果。大语言模型本身是无状态的，每次发消息，后台是把整个对话历史重新打包发过去。第一轮两千 token，第二轮四千……这是等差数列求和，到第三十轮总输入是天文数字。

【窦文涛】显而易见的修法是"截断最旧的消息"。但这条路行不通：最旧的消息往往承载着原始任务目标，截断后 Lena 开始漂移——完成的不是用户要求的那个任务。Anthropic 2025 年工程博文把这种失败模式称为"上下文腐烂"（context rot）：随着上下文增长，模型召回能力渐进下降，开始解决错误的问题。注意这是渐进的质量退化，不是某一轮突然崩溃——你可能跑了二十轮才发现 Lena 已经在做错的事，这让 context rot 比硬截断更难察觉，也更危险。

【窦文涛】所以我们需要的是压缩（compaction），不是截断（truncation）。Anthropic 官方博文给出了一个精确定义：context 必须被当成有边际递减收益的有限资源，LLM 有一个"注意力预算"，每加一个新 token 就消耗一点。（来源：《Effective context engineering for AI agents》，2025-09-29）这意味着精心裁剪的 50K context 有时比散装 200K 推理质量更好。

【窦文涛】本章的工程目标因此是：用更少 token 获得更好结果，而不是把窗口装满。核心设计是三层 compaction 架构。为什么要三层、不能用一层？因为存在三个不同的失败面，每个失败面需要不同的响应速度和成本权衡，一种机制三种都处理不好。

【窦文涛】第一个失败面是"持续 token 堆积"。工具结果——文件读取、shell 输出、搜索命中——在每轮之间不断累积，大多被引用一次后再也不用，却在每次后续 API 调用中反复消耗 token。正确的响应是在每次循环迭代时进行零成本、零 API 调用的内联清理，这就是微层 microcompact。

【窦文涛】第二个失败面是"接近硬上限"。当总 token 数接近 `context_window − buffer` 时，必须在 API 拒绝请求之前主动介入，用 LLM 驱动的摘要压缩上下文。这消耗一次额外 API 调用，但保留了对话的语义结构。这是自动层 autocompact。

【窦文涛】第三个失败面是"分词器估算误差"。客户端 token 计数是近似值，Anthropic API 的内部分词器可能有几个百分点的偏差。前两层可能在边界情况下失手，API 返回 413 错误。正确的响应是在错误路径上强制压缩并重试一次，这是响应层 reactivecompact。三层是级联（cascade），不是冗余——microcompact 零成本常驻，autocompact 偶发有代价，reactivecompact 作为最后安全网极少触发，三者成本特征完全不同，无法合并。

【窦文涛】代码层面，microcompact 最简单：函数签名是 `microcompact(messages: list[dict], keep_last: int = 3) -> list[dict]`，默认保留最近三个包含 tool_result 的轮次，把之前的替换为占位符 `[tool_result cleared by microcompact]`。无 API 调用，每次迭代安全运行，成本零。把这个函数插入 agent loop 最开头，就已经把工具垃圾的累积问题解决掉了。

【窦文涛】AutoCompactor 是第二层的骨架，两个关键常量：`BUFFER_TOKENS = 13_000`，与 Claude Code 生产代码 `autoCompact.ts:62` 的缓冲常数一致；`MAX_FAILURES = 3`，断路器阈值，对应 `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3`，连续失败三次后停止触发，避免压缩本身造成无限循环。

【窦文涛】`should_compact()` 判断逻辑：断路器打开返回 False，否则检查 `token_count >= context_window - BUFFER_TOKENS`。注意 13000 是 Sonnet 的合理默认值，Haiku 的 8K 输出上限意味着需要不同的安全缓冲，切换模型时必须重新校准。

【窦文涛】真正的摘要逻辑在 `compact()` 里，它用专门的系统 prompt 调用 LLM，核心要求是必须保留三样东西：用户的原始目标、所有已做的决策、每条错误信息的原文——不得省略错误。这条铁律反直觉，但非常关键。

【周迅】为什么错误信息不能省略？

【窦文涛】压缩时本能地想只保留成功结论。结果发现模型会反复犯同样的错误。比如某个 API 参数格式错了重试三次，如果摘要只写"成功调用了 API"，下次遇到类似情况模型还是用错误格式。错误是导航标记，agent 需要知道什么路走不通。正确的摘要是：原始目标 + 已执行步骤 + 遇到的错误（原文保留）。这个设计叫做保留 negative knowledge，它减少重试，从结果上反而省 token。

【窦文涛】reactivecompact 是第三层，在真实 413 或 prompt_too_long 错误时调用。它不做 LLM 摘要，直接把所有包含 tool_result 的 user 消息替换为单行字符串 `[context cleared by reactive_compact]`。最粗暴但最可靠的紧急兜底，保证 API 错误不会以未处理异常的形式暴露给用户。

【窦文涛】骨架搭好之后，填充四个关键扩展。核心是 `compact()` 的真正实现：调用 LLM 生成摘要，`max_tokens=2048`，成功时重置失败计数，失败时递增返回 None——调用方决定是否继续。接着是 `parse_usage()` 统一多 provider 缓存字段。实际工程里 agent 通常需要跑在多个 provider 上，Anthropic/OpenAI/DeepSeek 缓存字段互不相同（口诀：A 根 O 嵌 D 根），没有处理 OpenAI 嵌套 dict `prompt_tokens_details.cached_tokens`，缓存读取就会静默返回零。

【窦文涛】第三个扩展是单标记缓存纪律：每个请求恰好一个消息级 `cache_control` 标记，放在最后一个工具定义上，格式 `{"type": "ephemeral"}`，多个标记静默失效——这是文档里不显眼但踩到就头疼的行为。第四个扩展是实时 TokenMonitor，每轮打印"input / cache_hit% / compactions"三个指标，是你验证整套系统是否生效的唯一窗口。跑 50 轮后看到第 5 轮 cache_hit 爬到约 70% 并稳定，第 25 轮 input 从 64K 骤降到 38K（autocompact 触发标志）——这两个信号是设计按预期运行的证明。

【窦文涛】理解了缓存机制之后，才能看懂一个隐蔽的陷阱。缓存断点（cache breakpoint）是请求中 API 开始缓存的位置，断点前 token 从缓存提供（0.1 倍价格），断点后重新计算（1.0 倍），首次写入惩罚 1.25 倍。关键：缓存命中的条件是断点前的内容逐字节相同。

【窦文涛】所以 system prompt 里嵌了时间戳就毁掉了一切。`system = f"你是 Lena。当前时间：{datetime.now()}。"` 每次调用时间戳都变，前缀失效，system prompt 全量重新计算，每轮付全价 1.0 倍而非 0.1 倍。一个时间戳字段 = 50 轮里多付 9 倍成本。

【周迅】修法是什么？

【窦文涛】把时间戳从 system prompt 移到用户消息。`system = "你是 Lena，一个通用 agent。"` 逐字节不变；`user_msg = f"[{datetime.now()}] 第 {i} 轮：..."` 让变化内容在断点之后。system prompt 和工具定义完全稳定，缓存命中率从 0% 立刻跳回 70% 以上。

【窦文涛】看到这里你可能会想：为什么不用一个统一的压缩层来简化代码？简单替代方案是每轮调用 `compact_if_needed()`，超过阈值就摘要——确实有框架这么做。核心问题是成本特征不兼容：microcompact 必须零成本常驻（每轮都跑），autocompact 必须有代价偶发（LLM 调用），reactivecompact 必须在 API 错误路径才触发。合并成一层，要么每轮跑昂贵路径（成本翻倍），要么只在阈值跑（工具垃圾累积 20+ 轮），要么没有 413 错误路径（分词器偏差漏网后以未处理异常暴露）。

【窦文涛】三层分离不是理论设计，在 Claude Code 源码里明确落地：`autoCompact.ts:62` 存缓冲常数，`microCompact.ts:253` 是零成本路径，`query.ts:15` 的 `REACTIVE_COMPACT` 特性标志控制响应层开关。每层一个职责，一个触发条件，无法传播失败给其他层——这也是这套设计在生产环境能稳定工作的原因。

【窦文涛】这套单 agent 的 context 管理思路，直接延伸到多 agent 场景。第 11 章 Lena 获得派生子 agent 能力后，orchestrator 的 context 会因为汇总子 agent 结果而膨胀，问题规模升维。Anthropic 架构白皮书给出的三种解法——Context editing、File-based persistence、Response cap 加 pagination——正好对应三层架构的三个扩展方向，是同一套思路在不同规模下的延伸。

【窦文涛】这一章 Lena 第一次拥有了主动管理自己 context 的能力，不再等到崩溃才被动终止。一个重要的工程教训是：context engineering 不是上线后的优化项，而是从第一天开始就应该设计进去的基础能力。很多 agent 项目在早期用简单的全量 replay 跑得很流畅，等到用户对话轮次变长、工具调用变多，才发现 token 成本突然变成不可持续的量级。把三层 compaction 和 prompt caching 纪律在架构阶段就建进去，是避免这个陷阱的正确时机。第 11 章，Lena 获得规划能力，能自主把大目标拆成小步骤并行委托执行。

【窦文涛】最后来看三个挑战练习，验证三条关键铁律。时间戳测试：嵌入 `datetime.now()` 跑 10 轮再还原对比，差距约 70 个百分点。错误保留测试：扩展 `compact()`，把每行 `Error:` 追加到摘要末尾，故意触发 `FileNotFoundError` 验证 50 轮后存活。

【窦文涛】Provider 测试：用 mock 返回 OpenAI 格式 usage dict 含嵌套 `cached_tokens`，确认 `parse_usage()` 正确读取非零值。三个练习跑通，这套系统才算真正掌握了。我们下期见。

---

*约 3200 字 / 预计 TTS 时长 ~22 分钟（语速 1.1x）*
