# 第 7 章播客脚本：流式与并发——让 Agent 不卡顿

> 风格：tutorial（科普教学）
> 主持人：涛哥（窦文涛）≥95% + 小周（周迅）<5%
> 时长目标：约 30 分钟
> 人名规则：Bob 代替任何真实工程师名，绝不出现作者名

---

【窦文涛】听众朋友好，欢迎收听《从零构建你的 AI Agent》配套播客。我是涛哥。今天讲第 7 章：流式与并发——让 Agent 不卡顿。这一章解决的是 Lena v0.6 的两个痛点：第一，用户按下回车之后屏幕空白整整三秒多，然后才"啪"一下全出来；第二，五个完全独立的搜索任务非要一个一个排着队跑，加起来要八到十二秒。本章结束，Lena 从 v0.6 升级到 v0.7，第一个字出现的时间从三秒缩到零点三秒，五个工具并发执行总耗时从约十二秒压缩到约两秒。我们先把问题说清楚，再一步步看解法。

【窦文涛】先看具体时间轴。用户说"帮我同时查今天北京天气、最新 AI 新闻、BTC 价格、北京到上海航班、Python 3.13 新特性"。t=0.0s 按下回车，屏幕空白；t=3.2s 收到完整响应，含五个 tool_use 块；接下来一个工具一个工具串行跑，t=12.0s 五个工具才全部完成；t=15.5s 用户看到第一个字。两个根因：第一，LLM 在 0.3 秒就开始输出第一个 token，v0.6 非要等到 t=3.2s 完整响应才开始处理，白等了将近三秒；第二，五个工具彼此独立，v0.6 非要串行，白白叠加了每个工具的延迟。修法也是两个：流式接收、工具并发。

【窦文涛】在解法之前，先翻转一个很常见的直觉错误：agent 应该默认把所有工具并发跑。这个想法听起来合理，但真实世界的 agent runtime，包括 Claude Code 和 OpenClaw，默认都是序列化的。Claude Code 的 StreamingToolExecutor.ts:40 注释写明：结果必须按工具收到的顺序发出，不管哪个工具先完成。

【窦文涛】顺序语义是 LLM 协议强制的：LLM 把工具按顺序放进 content 块数组，tool_result 也必须与之对应。这不是偷懒，是协议约束。

【窦文涛】OpenClaw 在会话级别更进一步，强制整个会话同一时刻只运行一个 agent 实例。原因留到本章 Design Note 详细展开，这里先记住结论：序列化是出于副作用安全考虑，不是性能懒惰。

【窦文涛】所以这章要教的并发，是"对 isConcurrencySafe 等于 true 的工具开启并发"，不是"所有工具都并发"。isConcurrencySafe 等于 true 的定义：只读、无副作用、幂等。web_search 满足这三条，所以可以并发。write_file 不满足，必须序列化。这个分级是贯穿全章的核心 Convention。

【窦文涛】现在来看第一个解法：SSE 流式输出。SSE 是 Server-Sent Events 的缩写，基于 HTTP/1.1 的单向文本流协议，RFC 6202 标准化。它的本质很简单：服务器不关闭 HTTP 连接，生成一点内容就立刻往连接里写一点，不等所有内容生成完再一次性返回。Anthropic、OpenAI、DeepSeek 三家 API 全部选择 SSE，这是收敛结果，不是各家独立发明。

【窦文涛】为什么三家都选 SSE 而不是 WebSocket？理由直接：LLM 生成天然是单向的，服务端生成 token，客户端消费，没有客户端向服务端推送的场景，SSE 天然适合。SSE 是纯 HTTP，任何 HTTP/1.1 代理和 CDN 都能透明处理；WebSocket 的升级握手会被很多企业代理拦截。SSE 还有内置的断线重连，浏览器原生 EventSource API 会自动重连并携带 Last-Event-ID 头。

【窦文涛】SSE 格式极简单：每条消息是"event: 类型名"加"data: JSON"，消息之间空行分隔。消费侧只需逐行读、过滤 data: 开头、解析 JSON、按 type 分支处理。三家协议在工具参数传输上有差异：Anthropic 用 content_block_start + 连续 input_json_delta 分片；OpenAI 用 choices[0].delta.tool_calls 内嵌，流结束标志是 data: [DONE]；DeepSeek 推理模型还加了非标字段 reasoning_content 用于传输思维链，需要特判。

【窦文涛】Anthropic 还有一个特殊字段值得单独讲：signature_delta。当你使用 Extended Thinking 时，每个 thinking block 结束时会收到一个 signature_delta 事件，携带 Anthropic 对该 thinking block 内容的加密签名。

【窦文涛】工具调用多轮对话场景里，agent 构造下一轮 user 消息时，必须把上一轮的 thinking block 原样放进去，包括 signature 字段。这是 Anthropic 验证 thinking block 完整性的机制。丢了 signature，API 返回 400 错误："messages[1].content[0].thinking must contain a signature field"。nanoClaw 的 llm.py:383 有完整参考。口诀：收到 signature_delta 就追加；回传 thinking block 时 signature 原样带上，不能省。

【窦文涛】最小骨架不到三十行：aiohttp ClientSession POST 到 messages API，加上 stream=true；异步逐行读，过滤 data: 开头，解析 JSON，遇 text_delta 就 print，遇 message_stop 就 break。跑通这个骨架就验证了一件事：token 在零点三秒就能开始显示。先跑通，再往上叠扩展。

【窦文涛】骨架跑通之后，第一个要加的扩展是工具参数缓冲。Anthropic 用 input_json_delta 分片传输工具参数，你不能逐片解析 JSON，因为中间的 JSON 片段是残缺的。正确做法是为每个 tool_use block 维护一个 json_buffer 字符串，每收到一个 input_json_delta 就拼接进去，等到 content_block_stop 时再整体 json.loads。

【窦文涛】具体需要两个字典：current_blocks 以 block 的 index 为 key，记录 type、id、name；json_buffers 以 index 为 key，记录累积的 JSON 字符串。content_block_start 时初始化，content_block_delta 时追加，content_block_stop 时收割并解析。这三个时机对应三个事件，是 Anthropic 流式协议中工具参数的完整生命周期。

【窦文涛】第二个扩展是流式抢跑。这是本章最关键的性能优化点。传统做法是等 message_stop 收到之后，再把所有工具调用打包提交执行。流式抢跑是：content_block_stop 那一刻 tool_use block 刚好完整，立刻调用 asyncio.create_task() 启动这个工具的协程，不等 LLM 流结束。这意味着当 LLM 还在生成后续 tool_use block 的时候，前面已经完整的 block 对应的工具已经在并发跑了。这就是"抢跑"的含义：抢在 LLM 流结束之前启动工具。LLM 流通常在一点二秒结束，工具从零点四秒就开始跑了，等 LLM 流结束时工具可能已经完成了大半。

【窦文涛】实现这个的核心类是 ConcurrentToolExecutor，对应 Claude Code 的 StreamingToolExecutor。它维护一个 semaphore（对应 CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY）和一个 pending 字典。add_tool 方法调用 asyncio.create_task 启动协程，协程内部用 async with semaphore 包住工具调用做并发上限保护，task 存入 pending。wait_all 方法 await 所有 pending task，返回 tool_id 到 result 的映射。

【窦文涛】第三个扩展是 signature_delta 保存。在流循环里，content_block_start 时如果 block.type 等于 thinking，在 current_blocks 里同时初始化 thinking 字段和 signature 字段为空字符串。content_block_delta 时，遇到 thinking_delta 就追加 delta.thinking，遇到 signature_delta 就追加 delta.signature。如果你不用 Extended Thinking，这几行代码安静地没有任何输出。如果你用了但没这几行，会直接报 400 错误。这是一个低成本的防御性编码，值得加上。

【窦文涛】把三个扩展和骨架组合进一个 while 循环，就是完整的 StreamingAgentLoop。结构是：初始化 executor 和状态跟踪字典，进入流式读取循环，在 content_block_stop 时调用 executor.add_tool 抢跑启动工具，等 LLM 流结束后调用 executor.wait_all 收集结果，把 assistant content 和 tool_result 追加进 messages，进入下一个 step。stop_reason 等于 end_turn 且 executor.pending 为空，才 break 退出循环。

【窦文涛】看一下真实的时间轴对比。Beat 6 运行验证的 benchmark.py 用 mock_web_search 模拟每个查询随机零点五到两点零秒的延迟。串行执行五个查询，总耗时是五个延迟之和，通常在五到九秒。并发执行用 asyncio.gather，总耗时等于五个延迟中最大的那个，通常在一点五到两秒。加速比在三到五倍之间。理论上限是五倍，实测偏低的原因是五个任务的延迟不同，最慢的那个决定了并发总耗时。实测看到加速比小于两倍时，最常见原因是在 async 函数里调用了同步阻塞的 requests 库，requests.get() 会阻塞整个事件循环，aiohttp 才是正确选择。

【窦文涛】如果你在 Jupyter Notebook 里跑 asyncio.run(main()) 看到 RuntimeError: This event loop is already running，原因是 Jupyter 本身已经有一个事件循环在跑了，asyncio.run 会尝试创建新的事件循环导致冲突。解决方法是改用 await main() 直接在 cell 里 await，或者安装 nest_asyncio 包并在开头调用 nest_asyncio.apply()。

【窦文涛】完整 benchmark 跑完，你应该能看到类似这样的输出：串行总耗时六点零三秒，并发总耗时一点七八秒，加速比三点四倍，节省时间四点二五秒，节省比例百分之七十一。这就是五个 isConcurrencySafe 等于 true 的 web_search 并发执行的收益。如果只有一个工具调用，并发没有任何收益。并发的收益随着可并发工具数量线性增长，直到达到 semaphore 上限。

【窦文涛】现在来看 Design Note：为什么 OpenClaw 强制序列化每个会话。替代方案是允许同一用户的多条消息并发触发多个 agent 实例，用分布式锁保护共享资源。这个替代方案的问题有三条。

【窦文涛】第一，副作用竞争：两个 agent 实例同时写同一个文件，文件锁防写冲突，但防不了先读后写的逻辑竞争。第二，上下文失真：每个实例有自己的 messages 历史，并发实例看不到彼此的工具调用结果，可能做出互相矛盾的决策。第三，错误传播放大：一个实例工具失败会独立触发重试，并发实例各自重试，产生指数级的重复操作。

【窦文涛】OpenClaw 的结论是："agent 的可预测性比原始吞吐量更重要。"对于一个管理真实文件、真实日程的 always-on agent 来说，偶尔多等五百毫秒比偶尔丢失一条日历事件要好得多。会话内的并发仍然存在，序列化是"同一用户的多条消息不并发"，不是"同一消息里的多个工具调用不并发"。单次响应中，所有 isConcurrencySafe 等于 true 的工具调用仍然并发执行。这是本章教的核心内容。

【窦文涛】如果你要在生产系统里放开会话级并发，必须先回答三个问题：所有工具调用是否幂等？共享状态有没有行级锁？并发实例的 messages 历史如何合并？这三个问题没有通用答案，这也是为什么 OpenClaw 选择了保守的序列化默认值。工程上的保守主义在这里是美德，不是懒惰。

【窦文涛】两个优化各有边界要注意：SSE 流式接收要正确处理工具参数缓冲和 signature_delta，这是协议的完整性要求；并发只对 isConcurrencySafe 等于 true 的工具开放，结果顺序语义必须保持，这是 LLM 协议要求。只有边界清楚，优化才是安全的。

【周迅】涛哥，本章 Lena v0.7 最核心的能力跳升是哪一条？

【窦文涛】流式抢跑。用户感知上，零点三秒就有反馈；执行上，工具从 LLM 流还没结束就开始跑了，两个优化叠加在一起，体验质变。这也是很多 agent 开发者最容易忽略的一个细节——大家知道要开流式，但不知道还可以在流式接收阶段就提前启动工具，这中间还有一段时间可以省。

【窦文涛】延伸阅读三个核心资源。Anthropic 官方 Streaming Messages 文档——重点看 event types 列表，每种事件的字段都不一样，没读过直接写代码很容易漏掉字段。Claude Code 公开仓库的 StreamingToolExecutor.ts:40——看并发安全判断的真实实现，能看到"结果按收到顺序发出"这个约束是如何在代码里强制实现的。WHATWG EventSource 规范——理解 id: 字段和断线重连机制即可，因为 LLM 流不可重放，大多数 LLM 客户端用长轮询而非 EventSource，但理解断线场景有助于设计客户端重试逻辑。

【窦文涛】Lena v0.7 现在能不卡顿了，但还有一个问题没解决：每次对话结束，Lena 失忆了。她忘掉了用户说过"我不喜欢飞行，优先推荐高铁"，也忘掉了上周让她分析的那家公司的基本情况。一个真正有用的 agent 必须记得这些。第 8 章，我们给 Lena 装上记忆系统——短期 SQLite 会话历史加长期文件系统偏好库，让她有昨天。下期见。

---

*约 3800 字 / 预计 TTS 时长 ~25 分钟（语速 1.1x）*
