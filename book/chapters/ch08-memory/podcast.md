【窦文涛】今天我们来聊一个让 agent 脱胎换骨的能力——记忆。Karpathy 有一句话切中要害："LLM 的 context window 就是 RAM，顺行性遗忘症意味着跨 session 无法巩固记忆，每次重启都是白纸一张。"笔记本电脑关机后 RAM 归零，但硬盘还在。没有记忆层，agent 每次启动就像一个失忆患者——知道所有常识，但忘了昨天跟你说过什么。本章要解决的就是这件事。

【窦文涛】Lena 这一章从 v0.7 升到 v0.8。v0.7 已经能流式并发、调工具、处理多步任务。但它每次启动都失忆——你上次说"我偏好 Python"，这次它照样问你"用什么语言"。v0.8 加上两层记忆架构：SQLite 短期记忆加文件系统长期记忆，跨会话能记住用户是谁、偏好什么、上次讨论到哪里。本章要实现这两层，讲透原理，跑通演示。

【窦文涛】先建一个精确的分类框架。记忆有四个维度，每个维度对应一个设计决策。第一个维度叫**时间**——记忆分会话内和跨会话两种。前者只活在当前进程内存里，后者需要持久化到磁盘，能在下次启动时恢复。这是最根本的分层，没有跨会话持久化，agent 永远是一次性的。

【窦文涛】第二个维度叫**精确性**——记忆分 verbatim（原文存储）和 summarized（LLM 摘要）两种。SQLite 存原始消息，是 verbatim；autocompact 生成的是 LLM 摘要，是 summarized。**可以失真**。这个差异就是"Compaction 摘要不可信"问题的根源——摘要经过 LLM 重写，会丢失细节甚至改变事实。

【窦文涛】这是真实的生产事故模式。场景是这样的：用户在对话里明确否决了某个方案——"LangChain 那条路我们不走了"。后来会话超过 128K tokens，触发 autocompact，LLM 把历史压缩成摘要，把"明确否决"写成了"待评估"。然后 agent 在后续对话里再次推进这个方案，直到用户发现并叫停。verbatim 存储不经过模型，忠实保存每一条原始消息，这正是本章 SQLite 方案能防住这类事故的原因。

【窦文涛】Convention 定义如下：**短期记忆** = 当前会话的消息历史，存 SQLite，verbatim，进程退出后持久化；**长期记忆** = 跨会话的关键事实和用户偏好，存文件系统，verbatim，每条记忆一个 `.md` 文件。

【窦文涛】第三个维度叫**访问方式**——短期记忆顺序读取，按时间戳加载全部历史；长期记忆按需检索，MEMORY.md 索引加读相关文件。这个区别影响 context 占用量：顺序读全量，按需读索引页。随着会话轮次增加，短期记忆的顺序加载会撑大 context，这是后续 Context Engineering 章节要处理的问题。

【窦文涛】第四个维度叫**写入时机**——短期记忆自动写入，每轮对话结束追加；长期记忆 agent 主动判断，"这句话值得记住"才调用 `save_memory` 工具写入。让 agent 自己决定什么值得记是关键设计——如果所有对话都写入长期记忆，会产生大量噪声，用不相关的事实污染 system prompt。四个维度合起来，就是这个系统全部设计决策的来源。

【窦文涛】四维框架讲完了分类，接下来有一个绕不开的实现选型问题：长期记忆存到哪里？最直觉的答案是向量数据库——把每条记忆向量化，用余弦相似度检索。但向量库解决的是**语义相似性搜索**问题，而 agent 记忆需要的是**精确检索**："这个用户的所有偏好"、"上次讨论的结论"。个人 agent 的长期记忆通常在 100 到 1000 条，对 1000 个 `.md` 文件做全量读取，Python 只需要约 50 毫秒，远低于任何 LLM API 调用的延迟。

【窦文涛】Manus 团队 2025 年在 *Context Engineering for AI Agents* 里明确提出："文件系统是无限外部记忆。把重要上下文持久化到文件，而不是指望 context window 装得下。"向量库还带来三个额外成本：**嵌入依赖**——每次写入需要调嵌入模型；**调参地狱**——相似度阈值和 Top-K 没有正确答案；**可检查性丢失**——文件系统可以用文本编辑器直接读写，向量索引出错时很难调试。文件系统方案对这三个成本结构性免疫。

【窦文涛】要记清楚这条分界线：个人 agent 的记忆（100-1000 条）用文件系统；10,000 条以上的外部文档语义检索才是向量库的主场，那是第 9 章 RAG 的职责。区分标准很简单：这条信息是 agent 经历产生的还是用户提供的外部文档？前者用本章的文件系统方案，后者用 Ch 9 的 pgvector 方案。

【周迅】Claude Code 的 MEMORY.md 机制是怎么工作的？

【窦文涛】很多人以为"Claude Code 能记住你的偏好"是模型的长期记忆能力。不是的。**是每次会话启动时把文件内容注入 system prompt**。模型本身是无状态的，"记住"是每轮调用时从磁盘读取记忆文件，拼入上下文，让模型每次都能"读到"。Lena v0.8 遵循完全相同的原理，这是理解下面实现细节的关键前提。

【窦文涛】Claude Code 源码的 `memdir.ts:34` 定义了 `ENTRYPOINT_NAME = 'MEMORY.md'`，`memdir.ts:35` 定义了 `MAX_ENTRYPOINT_LINES = 200`，约 25KB 上限。`buildMemoryPrompt()` 在会话启动时读取 `MEMORY.md`，截断到 200 行 / 25KB，拼入 system prompt。超限时追加警告行告诉 agent 索引被截断了。`memoryScan.ts:22` 还限制 `MAX_MEMORY_FILES = 200`，防止记忆文件无边界增长。

【窦文涛】这个机制有一个重要推论：**记忆文件的更新立即生效，无需重启**。你手动编辑或删除记忆文件，下一次 `chat()` 调用就会用新状态——这是向量数据库做不到的可检查性。基于这个原理，Lena v0.8 的实现分两个类。

【窦文涛】短期记忆是 `MemoryStore`，底层 SQLite，零依赖。它维护两张表：`sessions` 表存会话元数据，`messages` 表存每条消息的 `session_id`、`role`、`content`（JSON 编码）、`created` 时间戳。核心操作是 `append_message` 追加和 `load_messages` 按会话顺序读取。连接策略是每次调用都新建连接，不用连接池——这个量级不需要。

【窦文涛】长期记忆是 `MemDir`，底层文件系统，也是零依赖。每条记忆一个 `.md` 文件，带 YAML frontmatter，包含 `id`、`type`、`subject`、`description`、`created`、`confidence` 六个字段。`MEMORY.md` 作为索引文件，记录所有记忆文件的简表。类常量 `ENTRYPOINT_NAME = 'MEMORY.md'`，`MAX_ENTRYPOINT_LINES = 200`，和 Claude Code 保持一致。

【窦文涛】举个具体的例子：`mem_20260505_143022_a3f2b1.md` 的 frontmatter 长这样——`type: user, subject: programming_language, description: 用户偏好 Python 写后端`，文件内容是详细说明。`format_for_prompt()` 读取全部记忆文件，把内容格式化成 `- [user] **programming_language**: 用户偏好 Python 写后端` 这样每条一行的文本块，注入 system prompt。

【窦文涛】记忆文件的类型分四种，来自 Claude Code `memdir/memoryTypes.ts:14`：`user` 是用户画像和偏好，`feedback` 是工作指导，`project` 是项目事实，`reference` 是外部资源指针。`MemDir.save()` 在写入前做内容截断保护，`max_chars` 默认 2000，防止单条记忆无限膨胀污染 context。写入后调用 `_update_index` 更新 `MEMORY.md` 索引。

【窦文涛】`save_memory` 工具是让 Lena 真正"主动记住"的关键，`input_schema` 要求 `subject` 和 `content`，可选 `mem_type`。工具描述里明确写了什么该存："用户表达了明确偏好、重要事实、需要跨会话记住的内容。"什么不该存："代码片段、临时任务状态、当前会话的上下文。"这个边界说明让 LLM 能正确判断写入时机，不产生噪声记忆。

【窦文涛】`LenaAgent` 的 `chat()` 流程是四步：第一步，`store.load_messages(session_id)` 加载会话历史；第二步，调用 LLM 携带 `save_memory` 工具；第三步，`_handle_tool_use` 处理工具调用——如果 LLM 触发了 `save_memory`，执行 `memdir.save()`，再次调 LLM 拿最终回复；第四步，`store.append_message` 持久化本轮对话。SQLite 负责短期，`MemDir` 负责长期，两层分工清晰。

【窦文涛】`_build_system_prompt()` 里还有一个值得说明的设计——记忆块被写了两次，开头一次，末尾用 `<!-- 记忆重申 -->` 标记再写一次，这个技巧叫 **Recitation**。背后是 Liu et al. 2023 年论文"Lost in the Middle"的结论：**LLM 对 context 两端的注意力显著高于中间，长 context 下中间信息的命中率低 20 到 30%**。如果偏好只放开头，经过 1000 tokens 的对话历史之后，模型对"用户偏好 Python"的注意力会衰减。末尾重申让偏好在对话末端也有强烈信号。

【窦文涛】代价是 system prompt 增大约一倍——记忆量小于 500 tokens 时代价可接受，实测两条偏好约 50 tokens，双写约 100 tokens。大量记忆时考虑末尾只写一行摘要。这不是 Recitation 独有的技巧，Manus 团队在 2025 年 Context Engineering 实践中把它列为核心工程手段之一。

【窦文涛】运行演示是这样的。第一次启动，提示"我叫 Demo-User，我偏好用 Python 写所有代码"，Lena 调用 `save_memory` 保存两条记忆：`user_name` 和 `programming_language`。第二次启动新进程，`[Memories loaded: 2]`，提示"帮我写个 hello world"，Lena 直接给 Python 版本，不再询问语言。对比无记忆版本同样的提示，得到的是"你想用哪种编程语言"的反问。这是 1 条工具调用加 2 个 `.md` 文件带来的能力差距。整个记忆系统磁盘占用小于 10KB，system prompt 注入小于 500 tokens。

【窦文涛】记忆解决了失忆问题，但还有一个隐患——随着对话变长，当 `autocompact` 触发，会话历史被 LLM 压缩成摘要，而这个摘要可以幻觉、可以改变已做的决定。**正确姿势是：重要决策在 compaction 发生前就写进 `save_memory`**。如果 compaction 摘要把"已否决的方案 A"写成了"待评估方案 A"，你有 `MEMORY.md` 里的 verbatim 记录可以覆盖它。Lena 的防御策略：compaction 后第一轮对话先 `load_index()` 对照 MEMORY.md，发现摘要与记忆文件冲突时以记忆文件为准。

【窦文涛】Lena v0.7 到 v0.8 的聪明度增量：第一次有了跨 session 的记忆——SQLite 短期历史加文件系统长期偏好，让她真正能记住"我做过什么、用户是谁"。下一章，Lena 要学会"读"而不只是"回想"——RAG 让她能在海量外部文档里找到与当前问题最相关的那一段。

【周迅】今天怎么动手？

【窦文涛】两步。**已有 agent 项目**：加上 `MemoryStore` 和 `MemDir`，注册 `save_memory` 工具，重启进程验证跨会话记忆。**还没开始的**：先从两个类的骨架写起，各自独立可运行，搭好地基再接进 agent 主循环。

【窦文涛】三个常见报错：`yaml.scanner.ScannerError` 是记忆文件 frontmatter 损坏；`anthropic.APIError: 401` 检查 `ANTHROPIC_API_KEY` 环境变量；`[Memories loaded: 0]` 第二次仍为 0 时，用 `print(agent.memdir.load_all())` debug，确认 Lena 第一次真的触发了 `save_memory` 工具调用。
