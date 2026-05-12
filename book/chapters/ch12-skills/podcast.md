# 第 12 章播客脚本：Skills——可复用的能力单元

> 风格：tutorial（科普教学）
> 主持人：涛哥（窦文涛）≥95% + 小周（周迅）<5%
> 时长目标：约 30 分钟
> 人名规则：Bob 代替任何真实工程师名，绝不出现作者名

---

【窦文涛】听众朋友好，欢迎来到《从零构建你的 AI Agent》配套播客。我是涛哥。今天讲第 12 章，Skills，可复用的能力单元。上一章我们完成了 MCP——让 Lena 通过标准协议接入外部工具。但工具只告诉 agent "能做什么"，它不告诉 agent "怎么做"。这一章补这块缺口，把 Lena 从 v0.11 升级到 v0.12，赋予她从 skills/ 目录动态加载多步 SOP 的能力，/weather 上海 一键触发完整天气查询流程。

【窦文涛】先从一个具体的失败场景感受问题的重量。假设你想让 Lena 生成 PDF 报告，最自然的做法是给她一个 generate_pdf 工具，@tool 装饰器，docstring 写"生成 PDF 报告"。工具注册好了，你运行一把，发现问题来了：工具告诉 Lena "我能生成 PDF"，却没告诉她生成之前应该先提取哪些关键数字、应该用哪个模板、表格里的数字保留几位小数。

【窦文涛】内容太长时如何分页、渲染失败时用户看到什么——这些都没讲。于是你开始往 docstring 里填：先提取内容中的关键数字、季度报告用 quarterly 模板、金额保留两位小数、每页最多三个图表……docstring 写到 200 行，工具注册表里 80% 的 token 全是"怎么用"的说明，而不是"能做什么"的声明。

【窦文涛】更严重的是：每次 LLM 需要判断"该不该调用这个工具"，都要把这 200 行扫一遍。而且这 200 行是始终在 context 里的，不管当前任务是不是要生成 PDF，这 200 行都在消耗你的 context。这就是工具的天花板。Convention 先立在这里：Tool 等于函数，声明"我能做 X"；Skill 等于 SOP，描述"做 X 类任务的正确方法"。那 200 行应该在 Skill 里，不在工具 docstring 里。

【窦文涛】Skills 要解决的问题可以用一句话概括：知识需要在 context 里，但 context 是有限的。工具描述必须始终占位，因为 LLM 每轮都要判断用哪个工具。但 SOP 知识不需要始终占位，它只在执行特定任务时才有用。Skills 的答案是渐进式披露——把知识分三层，始终只有第一层在 context 里。

【窦文涛】Anthropic 在 2025-10-16 发布的文章 Equipping Agents for the Real World with Agent Skills 里把这个设计比作一本结构良好的手册：先是目录，然后具体章节，最后是详细附录。三层结构如下：Level 1 是元数据，始终在 system prompt 里，只有 name 加 description，大约 20 到 50 个 token per skill；Level 2 是完整的 SKILL.md 正文，只有用户触发对应命令时才加载进来，100 到 500 个 token。

【窦文涛】Level 3 是 Skill 内部引用的子文件，只有 Skill 正文显式引用时才加载。一个有 30 个 Skill 的 agent，在没有触发任何 Skill 时，30 个 Skill 只占约 600 到 1500 个 token。触发某个 Skill 时，只增加那一个 Skill 的全文。这就是渐进式披露在 context 层面的量化收益。

【窦文涛】Skill 和 System Prompt 的边界也是个容易混淆的设计问题，这里立第二个 Convention：System Prompt 等于 agent 的身份和全局行为规范，始终有效；Skill 等于特定类型任务的 SOP，按需激活。判断标准很简单：这段描述，是对所有任务都成立的，还是只在做某类特定任务时成立？

【窦文涛】"你是一个专注代码的 agent，不做非技术任务"——这对所有任务成立，放 System Prompt。"当用户要求生成 PDF 报告时，按以下步骤处理"——这只在特定任务时成立，放 Skill。把 SOP 放进 System Prompt 是一种常见的设计反模式，Anthropic Context Engineering 原文称这种情况为 context pollution：无关 token 淹没焦点信号。

【周迅】涛哥，Skill 和 Tool 的区别我理解了，Skill 是写在 Markdown 里的？

【窦文涛】对，这是最关键的形态差异。工具是代码，Skill 是 Markdown 文件。形态上，Tool 是函数代码，Skill 是 Markdown 文件；描述的是，Tool 是一个能力，Skill 是一类任务的做法；执行方式，Tool 是 LLM 调用然后 runtime 执行，Skill 是按需注入 system prompt。

【窦文涛】何时占 context，Tool 始终占位，Skill 仅触发时才占；修改成本，Tool 要改代码重新部署，Skill 改 Markdown 文件立刻生效；可读性，Tool schema 对人不友好，Skill 是自然语言谁都能读。核心结论：工具的 docstring 越长，你就越接近一个 Skill 的需求。

【窦文涛】好，理论讲完了，看脚手架。Lena v0.12 的最小 Skills 加载器只需要三样东西：一个 Skill 数据类，一个目录扫描函数，一个 slash 命令解析函数。先从数据类开始。

【窦文涛】Skill 是一个不可变的数据类，frozen=True，三个字段：name 是 slash 命令名，比如 weather 对应 /weather；description 是元数据层的目录条目，始终在 context 里；content 是 SOP 正文，仅触发时注入 system prompt。还有一个 expand 方法，把正文里所有 $ARGUMENTS 占位符替换成实际参数，返回最终注入 system prompt 的文本。

【窦文涛】运行后，skill.expand("上海") 应该把正文里所有 $ARGUMENTS 替换为"上海"，然后这段文本追加到 system prompt 里。目前骨架还不能解析文件，接下来逐步加上四个扩展点。第一，frontmatter 解析：Skill 的元数据 name 和 description 存在 YAML frontmatter 里，用 re 提取两个 --- 之间的块，然后 yaml.safe_load 解析。文件名兜底：如果 frontmatter 里没写 name，就用文件名去掉扩展名。解析函数返回 Skill 实例或 None，没有 frontmatter 的文件直接跳过。

【窦文涛】第二个扩展点，目录扫描：实际使用里 skills 是一个目录，不是单个文件。用 Path.rglob("*.md") 递归扫描，返回 dict[str, Skill] 映射，键是 skill.name。同名 Skill 后者覆盖先者，这实现了项目级优先全局级的优先级：后扫描到的项目级 Skill 文件自动覆盖全局级同名 Skill。打印中间结果，加载 2 个 skill: ['pdf-report', 'weather']，然后才接入 agent loop。

【窦文涛】第三个扩展点，slash 命令解析：用户输入 /weather 上海，需要提取命令名 weather 和参数字符串"上海"。实现很简单，去掉开头的斜杠，然后 split(maxsplit=1)，取 parts[0] 作为命令名，parts[1] 作为参数，没有参数则返回空字符串。三个 assert 测试：/weather 上海 返回 ("weather", "上海")，/pdf-report 返回 ("pdf-report", "")，普通对话返回 None。

【窦文涛】第四个扩展点，接入 agent loop，关键改动只有三处。chat 方法入口先检查是不是 slash 命令，是的话提取 name 和 args。如果 name 是 skills 就列出所有可用 Skill 的名称和一行描述。

【窦文涛】如果 name 匹配到某个 Skill，就把这个 Skill 的 expand 结果追加到 system prompt，用扩展后的 system prompt 去调 LLM，原有的所有逻辑不动。如果命令名不存在，返回"未知命令，输入 /skills 查看可用技能"。普通对话走正常流程，不触发任何 Skill。DEBUG 日志：触发 Skill weather，参数"上海"，注入 system prompt 追加 247 个 token。

【窦文涛】运行完整的 Lena v0.12，预期的前几轮对话应该是这样的。用户输入 /skills，Lena 返回"当前已加载 2 个 Skill：/weather 城市名，查询城市天气并生成易读简报；/pdf-report 主题，生成结构化 PDF 报告含数据提取和排版规则"。用户输入 /weather 上海，DEBUG 打印触发 Skill weather，Lena 返回完整的天气简报，格式由 weather.md 里的 SOP 定义。用户接着问"今天适合户外运动吗"，Lena 根据刚才查询的上下文回答，无需重新触发 Skill。整个流程运行耗时约 2 到 4 秒。

【窦文涛】常见失败诊断三个。ModuleNotFoundError: yaml，执行 pip install pyyaml 解决。/weather 触发后 LLM 不按 SOP 格式输出，检查 skill.expand() 是否正确替换了 $ARGUMENTS，可以加 print(injected_system[-300:]) 看实际注入内容。未知命令: /weather，说明 skills/weather.md 的 frontmatter 里 name 字段缺失或拼写有误，直接打开文件检查 --- 块。

【窦文涛】现在到 Design Note，一个常见的替代方案：把所有 SOP 全部写进 system prompt，不需要 Skill 触发机制。这是很多早期 agent 的做法，也是大量"我的 system prompt 已经 8000 个 token"问题的根源。

【窦文涛】全量 system prompt 方案的 tradeoffs：绿灯是实现简单零架构复杂度；红灯第一，context 里充满当前任务不需要的指令，Anthropic Context Engineering 原文说"every irrelevant token competes with relevant ones for the model's attention"；红灯第二，system prompt 越来越长，维护成本 O(n) 增长，最终变成任何人都看不懂的魔法文件；红灯第三，context 窗口有限，加不了第 31 个 SOP。

【窦文涛】当前选择 Skills 目录加按需注入的理由：Simon Willison 评价 Anthropic 这篇 Skills 文章 "a bigger deal than MCP"，理由是知识复用比工具连接标准化更难解决。MCP 解决的是工具发现和调用协议的标准化，Skills 解决的是知识编码和按需激活的效率问题，两者解决的是不同层面的问题。如果你在构建一个只有三四个固定 SOP 的专用 agent，全量 system prompt 完全够用——Skills 目录的价值从 10 个以上可复用 SOP 时才开始体现。

【窦文涛】Anthropic 架构白皮书还提到了 Skills 的可组合性：Skill 可以调用其他 Skill。一个 compliance-check Skill 的内部实现可以引用 document-analysis Skill，后者再引用 entity-extraction Skill，形成能力金字塔，每一层都是独立的可复用单元。本章实现的三层披露机制，元数据到完整 SOP 到子文件，正是这个金字塔在单个 Skill 内部的体现。

【窦文涛】再来看 Claude Code 的真实实现，源文件是 loadSkillsDir.ts，887 行，比本章的 Python 骨架复杂很多，但核心逻辑一致。几个值得关注的工程细节：扫描路径的三层优先级，getSkillsPath 函数定义了三个路径：用户主目录下的 .claude/skills 是全局级，当前项目下的 .claude/skills 是项目级，managed 目录下的同名路径是组织策略级。

【窦文涛】优先级是项目级大于全局级大于组织级，同名 Skill 项目级覆盖全局级，和我们 Python 实现里的后扫描覆盖先扫描逻辑是同一个思路，只是路径优先级不同。

【窦文涛】token 预估的渐进披露实现：estimateSkillFrontmatterTokens 函数把 skill.name 加 skill.description 加 skill.whenToUse 拼接成字符串，调用 roughTokenCountEstimation 估算 token 数。CC 会估算每个 Skill 的元数据 token 数，用于在 context 接近上限时决定是否继续加载更多 Skill 的元数据。完整 SOP 正文 content 只在 getPromptForCommand 被调用时才加载。这就是渐进式披露在代码层的精确实现。

【窦文涛】$ARGUMENTS 之外 CC 还支持两个特殊变量：${CLAUDE_SKILL_DIR} 被替换为 Skill 自身所在目录的绝对路径，让 Skill 能引用同目录下的脚本或文件；${CLAUDE_SESSION_ID} 是当前会话 ID，用于需要持久化状态的 Skill。本章的 Python 骨架只实现了 $ARGUMENTS，已足够演示核心机制。

【窦文涛】CC 还有一条安全防线：MCP Skill 是远端不可信来源，不允许执行内联 shell 命令。CC 的 Skill 支持在正文里内联 shell 命令，用反引号加感叹号语法，但来自 MCP 的 Skill 禁止执行这类内联命令，源码注释清楚写着"Security: MCP skills are remote and untrusted — never execute inline shell commands from their markdown body"。这是 Skill 信任边界的第一次亮相，第 13 章安全章会详细展开。

【窦文涛】2025 年 12 月，OpenAI 在 ChatGPT 和 Codex CLI 里加入了格式上高度相似的 Skills 功能。这不是竞争式跟随，而是同一个工程问题——知识复用和 context 效率——在不同产品里收敛到了相似答案。工具告诉 agent 能做什么，Skills 告诉 agent 怎么做，两层分工在不同产品里独立得出了同一个结论。这是一种工程收敛，说明这个分层是真实有效的解决方案。

【窦文涛】从通用 agent 的视角看这一章。Lena v0.12 实现了一个重要的能力跃迁：第一次按需加载知识。在这之前，Lena 的每次对话上下文是固定的，system prompt 写什么就是什么。从这一章开始，system prompt 是动态的，根据用户触发的 Skill 临时扩充。这是 agent 学习维度的起点——不是 fine-tuning 意义上的学习，而是 prompt 层面的知识积累：把经验写成 Skill 文件，agent 下次执行同类任务时按需激活，不需要改任何代码，不需要重新部署。

【窦文涛】Lena v0.12 的产物清单：lena-v0.12 目录包含 main.py 入口、requirements.txt 依赖 anthropic 和 pyyaml、core/agent.py 含 AgentLoop 加 skill 注入逻辑、core/skills.py 含 Skill 数据类加 load_skills_dir 加 parse_slash_command。

【窦文涛】skills 目录下是 weather.md 和 pdf-report.md 两个示例文件。新增能力相比 v0.11：load_skills_dir 扫描 skills 目录返回 name 到 Skill 的映射；parse_slash_command 解析 /name args 格式；AgentLoop.chat 识别 slash 命令并注入对应 Skill 的 SOP；/skills 命令列出所有可用 Skill 的名称和一行描述。

【窦文涛】Lena 现在能按需加载 Skill 了。但如果某个 Skill 的 instructions 里藏着恶意指令呢？下一章讲输入安全：如何让 Lena 不被 prompt injection 劫持。我们会看到，Skills 系统引入了一个新的信任边界——本地 Skill 文件和远端 MCP Skill 的信任等级不同，对它们的处理方式也应该不同。这是第 13 章的起点，也是 Lena 从"功能完整"走向"生产可用"的关键门槛。

---

*约 3200 字 / 预计 TTS 时长 ~21 分钟（语速 1.1x）*
