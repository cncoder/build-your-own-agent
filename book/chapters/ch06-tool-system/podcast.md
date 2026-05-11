# 第 6 章播客脚本：工具系统——每一项能力都是一个工具

> 风格：tutorial（科普教学）
> 主持人：涛哥（窦文涛）≥95% + 小周（周迅）<5%
> 时长目标：约 30 分钟
> 人名规则：Bob 代替任何真实工程师名，绝不出现作者名

---

【窦文涛】听众朋友好，欢迎来到《从零构建你的 AI Agent》配套播客。我是涛哥。今天讲第 6 章，工具系统。上一章我们把 Lena 的身份确定下来——她知道自己是谁，有 ReAct 循环，能逐步推理。但她只会一招：查当前时间。这一章，我们要彻底解决"加一个工具就要动核心代码"的问题，把 Lena 从 v0.3 升级到 v0.6，赋予她四个真实工具，同时让核心循环零改动。

【窦文涛】先交代背景，感受问题的重量。Lena v0.3 结束的时候，她的工具接线长这样：一个叫 TOOLS 的列表，里面硬写了 get_time 的 JSON Schema 字典；一个叫 run_tool 的函数，里面一个 if 分支调 datetime.utcnow()。这很自然，写一个工具就这样写。但你现在想加第二个工具 web_search，必须做三件事：在第 12 行附近追加一个新字典，在第 20 行附近加一个 elif 分支，在第 1 行附近加一个新 import。三处独立修改，全在同一个包含 agent 循环的文件里。

【窦文涛】十个工具之后，run_tool 长这样：if get_time、elif web_search、elif read_file、elif write_file、elif shell、elif send_email、elif list_dir、elif grep_files、elif create_event、elif delete_file——然后抛异常。团队里每次合并冲突都发生在这个函数上。

【窦文涛】新人加 delete_file 在第 60 行，不小心在第 40 行的 read_file 分支里引入了一个差一错误。测试全过，因为测试不覆盖交互路径。这就是"两文件税"——schema 字典和调度分支，每加一个工具就要同时修改两处。

【窦文涛】更深层的问题是：agent 循环不应该知道有哪些工具。它应该在运行时问"注册了哪些工具"，让注册表回答。这是一个架构上的根本分工：循环负责驱动，注册表负责管理工具的元数据。Claude Code 的生产实现注册了 40 多个内置工具，加上可以在运行时动态添加的 MCP 工具——如果循环硬编码工具名称，这一切都不可能。我们想把因新增工具而必须改动 lena.py 的行数降到零。

【窦文涛】解决方案是 ToolRegistry，一个工具注册表。它的接口很小：register 注册一个工具，get 按名字取回，names 列出所有名字，get_schemas 返回 Anthropic API 格式的 schema 列表。循环只用这四个方法，它永远不知道背后有多少工具，也不知道工具怎么实现的。

【窦文涛】注册表里每个工具用一个 ToolMeta 数据类描述。ToolMeta 包含 name、description、input_model——一个 Pydantic 类，JSON Schema 从这里自动派生——以及 handler，一个异步函数。还有三个安全标志和一个结果预算字段，稍后细说。

【周迅】涛哥，Pydantic 是用来做什么的？

【窦文涛】好问题。Anthropic API 要求每个工具都以 JSON Schema 格式描述——一个指定参数名称、类型、描述以及哪些参数必填的 JSON 对象。手写 JSON Schema 既繁琐又容易出错。Pydantic 通过自动将 Python 类注解转成 JSON Schema 来解决这个问题。你声明一个类，字段带类型注解和 Field description，调用 model_json_schema() 就得到正确的 JSON Schema，一行 JSON 都不用手写。schema 和处理函数共享同一个真相来源：Pydantic 类。

【窦文涛】这里有一个 Convention 值得钉进脑子：schema 生成，定义是将 Pydantic model 类转换为 JSON Schema 字典，在启动时执行一次；schema 验证，定义是检查来自 LLM 的具体参数字典是否满足该 schema，每次工具调用时执行。这两个操作发生在生命周期的不同时间点，服务不同目的。Claude Code 在 TypeScript 里用 Zod 做同样的事，源码里 Tool.ts:396 有一行 readonly inputSchema: Input，原理相同：声明一次，到处派生。

【窦文涛】手写 JSON Schema 在规模化时有三个死法。第一，schema 漂移：函数里把 path 改名为 file_path，忘了更新字典，运行时无声 TypeError。Pydantic 解决这个，类既是 schema 也是验证接口，不可能漂移。第二，没有运行时验证：模型发送整数 42，处理函数期待字符串，错误在函数深处炸开。model_validate(args) 在调用处理函数之前就捕获，返回结构化错误让模型重试。第三，维护成本随工具数线性增长：40 个字典，每个字段改名都要人工同步。Pydantic 把认知负担降低为"了解 Python 类型提示"。

【窦文涛】现在聊三旗安全契约。每个工具必须声明三个属性，这不是风格建议——它们决定 agent 循环如何调度工具调用。is_read_only：工具只观察状态，从不改变状态。is_destructive：工具执行不可逆操作，比如删除、覆盖、发送邮件。is_concurrency_safe：工具可以和同一轮的其他工具调用安全地并行运行。

【窦文涛】为什么恰好是这三个？每个都对应调度器的具体决策。is_concurrency_safe 决定循环是否可以在上一个工具还没结束时就触发这个工具。Claude Code 的 StreamingToolExecutor.ts:40 使用的正是这个信号：随着 API 响应流式传来，每个 tool_use 块触发 addTool。

【窦文涛】如果该块的工具 isConcurrencySafe 是 true，执行立即开始——模型甚至还没生成完响应。这就是为什么 web_search 可以和 read_file 重叠执行：两者都是只读的，可以安全并行。write_file 不能：两次并发写入同一路径会交叉写入，损坏文件。

【窦文涛】is_read_only 进入权限层。在 Claude Code 的 plan 模式下——agent 可以读取一切但写之前必须询问——循环会自动批准声明了 isReadOnly=true 的工具，无需提示用户。权限决策树在检查模式特定规则之前先评估 isReadOnly，出处是 Tool.ts:402-404。is_destructive 是硬覆盖，源码注释很清晰："默认为 false，仅当工具执行不可逆操作时才设置"，出处 Tool.ts:405-406。破坏性工具总是触发确认对话框，无论权限模式如何。

【窦文涛】三个标志之间有一个微妙之处值得单独说：它们是独立布尔值，不是互斥分类。create_file 创建新文件但不覆盖或删除任何东西，所以不是破坏性的；但它确实修改了状态，所以也不是只读的。这种"非只读也非破坏性"的中间态在真实工具集里非常常见，三个独立标志能精确描述它，一个三值枚举做不到。

【窦文涛】第三个理论概念是大结果问题。当工具返回一个大结果——比如读取一个 500 KB 的源文件——整段文本落入对话历史里。每次后续 API 调用都带着那 500 KB 的 token。几轮之后，上下文窗口填满，agent 以 prompt_too_long 错误崩溃。

【窦文涛】生产级 agent 用结果预算来处理这个问题：如果工具结果超过某个字符阈值，就把它持久化到磁盘，给 LLM 一个紧凑的引用而不是完整文本。Claude Code 把这个阈值叫做 maxResultSizeChars，出处 Tool.ts:466：当工具结果超过它时，applyToolResultBudget() 把内容写入临时文件，用 persisted-output 标签替换对话消息，出处 toolResultStorage.ts:30。模型收到的是路径，不是内容。

【窦文涛】有一个显眼的例外：FileReadTool 的 maxResultSizeChars 设为 Infinity。如果它有有限的阈值，持久化会触发自引用死循环：read_file 大文件 → 超预算持久化临时文件 → 模型调用 read_file 读临时文件 → 再次超预算 → 无限循环。Infinity 通过契约打破这个循环，工具自己的 limit 参数（默认 200 行）负责控制结果大小——这是工具自我限制与外部预算管理的分工边界。

【窦文涛】理论讲完了，看脚手架。ToolRegistry 约 50 行，register 方法把 ToolMeta 放入内部字典，get_schemas 方法迭代所有 ToolMeta，调用每个 input_model.model_json_schema() 生成 Anthropic 格式的 schema 列表。

【窦文涛】在添加任何真实工具之前，先用一个 EchoInput 类验证骨架能生成正确 schema——运行后看到 name、description、input_schema 三个字段，required 由 Pydantic 自动推断，没有默认值的字段自动进入 required，一行 JSON 都不用手写。

【窦文涛】现在渐进组装四个真实工具。第一个：read_file。max_result_chars 设为 None，也就是 Infinity，理由直接来自前面说的循环回路问题。工具通过 limit 参数自我管理，默认 200 行，从不返回超过 limit 的内容。输入模型有三个字段：path 必填，offset 默认 0，limit 默认 200。返回结果带行号——行号让 LLM 在后续工具调用里能引用具体行，这个细节让多步文件编辑变得可操作。安全标志：is_read_only=True，is_concurrency_safe=True。

【窦文涛】第二个：write_file。is_destructive=True，因为覆盖不可逆，一个把空字符串写入 report.md 的 agent 就销毁了里面原有的内容。调度器在完全自主模式下运行这个工具之前应该暂停并确认。is_concurrency_safe=False，两次并发写入同一路径会交叉写入，损坏文件。父目录不存在时自动创建，这是一个贴心的细节——很多新手工具忘了处理这个，导致 FileNotFoundError 在奇怪的地方冒出来。

【窦文涛】第三个：shell。这是这组工具里最强大也最危险的。is_destructive=True，因为它可以删除文件、发送网络请求或修改系统状态——agent 和用户对"运行一条命令"的理解可能不一致。timeout 参数至关重要：没有它，一个长时间运行的进程会无限期阻塞 agent 循环。默认值是 30 秒。返回字符串里包含 exit_code，模型需要它来判断命令是否成功。一个调用 git commit 后不知道退出码的 agent，可能会在提交实际失败时愉快地继续执行。

【窦文涛】第四个：web_search。is_concurrency_safe=True，使用 DuckDuckGo 即时答案 API，无需 API Key，适合教学演示。这个标志在下一章解锁了并行执行——模型一轮里发出三次 web_search，三次同时触发，而不是排队等待。

【窦文涛】四个工具连接注册表的方式值得注意：lena.py 只 import ToolMeta 实例，从不直接引用任何处理函数。调度完全在 registry.execute() 内部完成。execute 方法里捕获 TypeError 很重要——LLM 偶尔会在 schema 说 path 是字符串时发送整数 42，没有这个捕获，处理函数会抛出毫无用处的 TypeError，捕获后的错误消息作为工具结果反馈给模型，让它有机会用正确参数重试。

【周迅】加第五个工具的时候，lena.py 真的不用改吗？

【窦文涛】真的不用。看完整流程：新建一个 tools/list_dir.py，定义 ListDirInput 类，写 _list_dir 处理函数，创建 LIST_DIR 的 ToolMeta 实例。然后在 lena.py 里加一行 from tools.list_dir import LIST_DIR，在注册循环里加 LIST_DIR。lena.py 核心循环代码零改动，只是多了一个 import 和一个列表元素。这就是"加工具不改核心循环"的具体含义：新工具完全在自己的模块里自包含，主程序对它一无所知，只在注册时知道它的存在。

【窦文涛】端到端运行演示。任务是"读取 registry.py，描述 ToolMeta 存储了什么"。步骤 1：模型收到 schema 列表，自主选择 read_file，生成调用参数 path="registry.py" offset=0 limit=200。步骤 2：系统执行，返回带行号的文件内容。步骤 3：模型综合答案，end_turn。两步，核心循环不需要知道有多少工具，也不需要知道用哪个工具读文件，它只是驱动循环，具体决策全部由模型完成。

【窦文涛】常见失败诊断有三个。第一：AuthenticationError: invalid x-api-key，ANTHROPIC_API_KEY 环境变量未设置，export 后重新运行。第二：TypeError: handler() got an unexpected keyword argument，这通常意味着字段名和处理函数参数名不匹配，检查 ReadFileInput.path 对应的是 _read_file(path: str, ...)，这是构建工具时最常见的集成错误。

【窦文涛】第三：stop_reason='max_tokens' 而不是 end_turn，模型的回答被截断了，增加 max_tokens 或缩短系统提示。这三个错误是首次运行最常遇到的坑，每次遇到按这个顺序排查，基本都能快速定位。

【窦文涛】生产里有两个细节值得注意。第一，给每个输入 model 添加 model_config = ConfigDict(strict=True)，严格模式拒绝整数强制转换为字符串，在参数到达处理函数之前捕获更多幻觉参数错误。Claude Code 通过 Zod 的 .strict() 选项实现等效功能，出处 Tool.ts:472。

【窦文涛】第二，有一个例外情形：包装第三方 MCP 工具时，schema 以原始 JSON blob 的形式到来，你对输入类没有控制权。这时用 inputJSONSchema 转义舱口，出处 Tool.ts:397，直接把原始 schema 传给 API，绕过 Zod/Pydantic。规则很简单：自己写的工具全用 Pydantic，接入外部工具用转义舱口。

【窦文涛】从通用 agent 的视角看这一章。工具通用性是构建通用 agent 的第一支柱：任何能力都等于一个工具，agent 的能力边界完全由注册了哪些工具决定。一个有趣的推论是：你可以在运行时动态加载工具，让 agent 的能力边界随用户上下文变化。这是 MCP 协议的核心思想——第 19 章会讲它如何让 agent 通过标准接口连接任意外部工具，把能力边界从"预先注册的工具集"扩展到"整个互联网上所有暴露了 MCP 接口的服务"。

【窦文涛】Lena 现在能读文件、写文件、运行 shell 命令、搜索网页——全部通过一个注册表路由，agent 循环完全通过名称在运行时寻址。没有 elif 链，没有硬编码工具列表，没有两文件税。

【窦文涛】但她每次只执行一个工具，等每个结果返回后才问模型下一步。在生产里，模型经常在单轮里产生多个工具调用——同时发五次 web_search，或者交错使用 read_file 和 shell。下一章解决流式输出和并发工具执行，当流式响应中一个调用块到达时就立刻触发工具，甚至在模型还没生成完响应之前。

---

*约 3800 字 / 预计 TTS 时长 ~25 分钟（语速 1.1x）*
