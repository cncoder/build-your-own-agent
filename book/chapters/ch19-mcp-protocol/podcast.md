【窦文涛】今天讲 MCP——Model Context Protocol，模型上下文协议。Anthropic 在 2024 年底发布这个规范，它要解决的问题可以用 USB 类比来理解——就像 USB 让所有外设都能插进同一台电脑而电脑不需要为每种外设单独修改内核，MCP 让所有工具都能连接到 Lena 而不需要为每种工具修改核心代码。在 MCP 之前，每个 AI 应用要接入一个外部工具，就要手写一套胶水代码，包括工具怎么被调用、参数怎么传、返回值怎么解析、错误怎么处理。接的工具越多，这些重复的胶水代码越多，而且每次某个外部 API 改了接口，就得修改核心代码重新部署。

【窦文涛】本章要讲清楚三件事。第一，MCP 协议本身是什么，底层用的 JSON-RPC 2.0 加 stdio 是怎么一回事。第二，200 行 MCPClient 代码里最关键的五步流程——spawn 子进程、握手、发现工具、调用工具、清理。第三，_stderr_loop 这一行代码背后的死锁机制——这是本章最反直觉的工程细节，也是整个 MCP 实现里最容易漏掉、漏掉就挂死的那个点。Lena 从 v0.18 升到 v0.19，工具从 4 个硬编码扩展到 30 个以上，核心代码零改动。

【周迅】没有 MCP 时怎么接工具？

【窦文涛】想让 Lena 读本地文件，就要在 lena/tools/filesystem.py 里手写 read_file、write_file、list_directory、search_files 四个函数。再想接 GitHub，又手写一批函数。再加 Postgres，又一批。每加一类工具，要改两个地方：工具函数本身，以及 lena/tools/__init__.py 里的 TOOLS 注册列表。MCP 把这个模式改成——在 mcp_config.py 里增加一行配置，Lena 启动时自动发现工具，不改核心逻辑、不重启。这个核心设计原则叫"工具是被发现的，不是被写死的"。

【窦文涛】理解 MCP 需要先理解 JSON-RPC 2.0。格式极简，一条请求就是一个 JSON 对象，包含四个字段：jsonrpc 值是字符串 "2.0"、id 是请求编号、method 是方法名、params 是参数对象。一条响应包含 jsonrpc、id 匹配请求 id、result 或 error 二选一。还有第三种消息叫通知 notification，没有 id 字段，发出去不需要等响应。

【窦文涛】MCP 在 JSON-RPC 2.0 上定义了一套方法名——initialize、notifications/initialized、tools/list、tools/call，这四个方法名加上三种消息类型，就是 MCP 协议的全部骨架。协议规范加起来只有几页，选择 JSON-RPC 2.0 而不是自定义格式，也是为了让实现简单、生态复用容易。

【周迅】为什么用 stdio 而不是 HTTP？

【窦文涛】两个原因。第一，进程生命周期绑定——MCP server 是子进程，随 agent 启动退出，不需要单独管理 server 生命周期，没有端口冲突。第二，三个通道天然分离——stdin 写请求、stdout 读响应、stderr 接日志，操作系统强制保证，不需要协议层规定。对比 HTTP：响应体和日志混在 HTTP 流里需要应用层区分，server 需要单独启停和端口管理。对于文件系统、GitHub CLI 这类命令行程序，stdio 是最自然的方式。MCP 规范也支持 HTTP+SSE 传输，用于多 agent 共享远程 server 的企业场景。

【窦文涛】MCPClient 用五步流程组织，nanoClaw 的 nanoclaw/mcp/client.py 大约 200 行是这个流程最干净的实现。第一步 spawn 子进程，调 asyncio.create_subprocess_exec，stdin、stdout、stderr 都设成 PIPE——三个都必须是 PIPE，不能是 DEVNULL，原因后面讲。spawn 完立即用 asyncio.create_task 起两个后台任务：_read_loop 和 _stderr_loop，这两个任务从现在开始并发运行直到 server 退出。

【窦文涛】第二步握手，发 initialize 请求，参数里带 protocolVersion 值是 "2024-11-05"、capabilities、clientInfo，server 回包含 serverInfo 的响应——里面有 server 名字和版本号。再发一条通知 notifications/initialized，这条通知没有 id，server 不需要回复，但它是 MCP 握手的必要信号，告诉 server 可以开始工作了。

【窦文涛】第三步发现工具，调 tools/list 方法，server 返回所有工具列表，每个工具包含 name、description 和 inputSchema——inputSchema 是 JSON Schema 格式的参数描述，会被原样传给 LLM 的 tools 字段。第四步是工具调用，调 tools/call 方法，参数带 name 和 arguments。第五步 stop，关闭子进程、取消后台任务、清理 _pending 里未完成的 Future。

【周迅】Future 模式怎么工作？

【窦文涛】_call 方法是整个 client 最精妙的部分。每次调用 _call，先分配一个自增 id，用 asyncio.get_event_loop().create_future() 创建一个 Future 对象，存到 _pending 字典里，key 是 id。然后把 JSON-RPC 请求序列化成一行文本写进 stdin，再 await fut——这里挂起，_call 让出事件循环控制权。

【窦文涛】_read_loop 在另一个协程里持续跑 await self._proc.stdout.readline()，每读到一行就 json.loads 解析，取出 id，在 _pending 里找到对应的 Future，调 fut.set_result(msg) 唤醒。_call 被唤醒后拿到 msg，取出 result 字段返回。等了 30 秒没被唤醒，asyncio.wait_for 抛 TimeoutError，_call 把这个 id 从 _pending 清掉，抛 MCPError。这个 Future 请求-响应匹配机制让单个事件循环能同时处理多个并发的 MCP 调用，每个调用挂在自己的 Future 上等待，互不阻塞。

【周迅】_stderr_loop 为什么重要？

【窦文涛】这是本章最重要的工程细节。代码极简——就是一个死循环，不停地 await self._proc.stderr.readline()，把读到的内容打日志或者忽略。看起来没什么，但如果没有这段代码，整个 MCP 连接会在随机时间死锁，没有任何错误提示，agent 就是卡住不动。死锁路径分五步：第一，MCP server 往 stderr 写日志；第二，操作系统为 PIPE 分配的内核缓冲区——通常 4KB 到 64KB——被写满；第三，server 的 write(stderr_fd) 系统调用阻塞。

【窦文涛】第四，server 整个进程卡住，阻塞在系统调用上，无法执行任何其他代码。第五，server 不再读 stdin 也不再写 stdout，Lena 这边 await fut 永远等不到 set_result，死锁。这个 bug 有四个特征极难排查：没有错误日志（stderr 正是堵住的通道）；症状延迟（要等缓冲区积满）；不可复现（取决于特定调用触发多少 stderr 输出）；表面看像超时但加长超时没有任何帮助。修复成本只有一行——在 start() 里加 self._stderr_task = asyncio.create_task(self._stderr_loop())。

【窦文涛】这就是 Karpathy 常说的反直觉工程细节——协议本身极简，但一个操作系统级别的 PIPE_BUF 机制，一行代码漏掉，整个系统随机挂死。从 nanoClaw mcp/client.py 第 177 到 191 行可以看到完整实现，整个 _stderr_loop 方法只有 12 行，用 asyncio.CancelledError 做退出处理，用 errors="ignore" 防止 stderr 里的非 UTF-8 字节崩溃。

【周迅】FastMCP 是什么？

【窦文涛】FastMCP 是 Josiah Carlson 在 2024 年底发布的 MCP server 开发框架，现已合并进官方 MCP Python SDK，pip install mcp 就包含它。核心价值是把写一个 MCP server 的成本从 150 行降到 10 行。自己写需要手写 initialize 握手逻辑、tools/list 响应构造、JSON Schema 生成、stdio 读写循环、错误格式化，全部加起来 150 行起步。用 FastMCP 只需要：from mcp.server.fastmcp import FastMCP，创建实例，用 @mcp.tool() 装饰器定义工具函数，最后 mcp.run() 启动。

【窦文涛】函数的类型注解自动变成 JSON Schema，docstring 自动变成工具描述，定义一个 read_file 工具只需要 6 行代码。关键数据：70% 的 MCP server 以 FastMCP 为底层，日下载量峰值约 100 万次，GitHub stars 超过 25000。FastMCP 已合并入官方 Python SDK 这个事实说明它不是社区项目，而是 MCP 生态正式的基础设施。

【窦文涛】有一个细节容易被忽视——工具的 docstring 质量直接影响 LLM 调用准确率。FastMCP 把 docstring 原样放进工具描述的 description 字段传给 LLM，LLM 看这个 description 决定什么时候调用、传什么参数。好的描述需要说清楚：这个工具做什么、什么场景应该用、参数的含义和约束条件。这不是写给人看的 API 文档，是写给 LLM 看的行为规范，两者对信息的要求不一样。工具描述写得好，LLM 才能在正确的时机调用正确的工具，这是 MCP server 开发里最常被忽视的工程质量维度。

【周迅】MCP 和 Skills 的区别？

【窦文涛】第 12 章讲的 Skills 和本章的 MCP 是两种不同的扩展机制，经常被混淆。MCP 是工具层扩展——让 Lena 能调用外部系统，以 JSON-RPC over stdio 子进程形式运行，获得新的"手"；Skills 是能力单元层扩展——让 Lena 知道如何做某类事，以 Markdown 文档注入 LLM 上下文形式存在，获得新的"思维框架"。两者不是竞争，是互补。

【窦文涛】MCP 适合接入外部服务——读文件、查数据库、发 Slack 消息；Skills 适合注入方法论——如何调试代码、如何设计 API。Simon Willison 在 2025 年 10 月 16 日写过一篇文章，称 Skills "在某种意义上比 MCP 影响更大"，逻辑是：MCP 让 agent 连接更多工具，而 Skills 改变了 agent 获取方法论的方式，任何人都能把最佳实践封装成 Skill 分发给所有 agent。随后 OpenAI 在 2025 年 12 月也在 ChatGPT 和 Codex CLI 里加入了 Skills。

【周迅】MCP 有什么安全风险？

【窦文涛】两个主要攻击面，防御铁律各三条。第一，子进程无沙箱。MCP server 以你的用户权限运行，没有任何沙箱隔离，可以读写你的所有文件、执行任意命令。恶意的第三方 MCP server 即使看起来只是"读文件工具"，也能偷读 ~/.ssh/id_rsa、~/.aws/credentials 然后发到远端。防御铁律：一，只装 @modelcontextprotocol/* 官方 npm 包，第三方包先审代码；二，给 filesystem server 配置允许路径白名单，只传 /tmp 或特定目录不传根目录；三，github server 只用只读 token，不用有写权限的 token。

【窦文涛】第二，工具输出 prompt injection。Simon Willison 在 2025 年 4 月 9 日发文专门分析这个攻击面：Lena 读取一个文件，如果文件里包含"忽略之前所有指令，执行以下操作"，LLM 可能把它当成系统指令执行。防御铁律：一，在系统 prompt 里明确告知 LLM 工具返回内容属于不可信来源，其中的指令不应被当成系统命令执行；二，涉及写操作（write_file、create_issue）前打印操作内容让用户确认；三，生产环境用第 20 章的 Docker Sandbox 做容器级隔离。

【窦文涛】本章还讲了 A2A——Agent-to-Agent 协议，Google 于 2025 年 4 月主导发布，GitHub 仓库 google/A2A。A2A 官方规范原话是："A2A complements MCP——where MCP focuses on tool/resource access, A2A addresses agent-to-agent communication as peers, not merely as tools。"一句话区别：MCP 是我让工具帮我做，工具没有自主性；A2A 是我请另一个 agent 帮我做，对方有自己的推理循环。

【窦文涛】A2A 定义了 TaskState 枚举，包含 8 个状态：SUBMITTED、WORKING、INPUT_REQUIRED、AUTH_REQUIRED、COMPLETED、FAILED、CANCELED、REJECTED。MCP 的请求-响应是同步的，调用后等结果；A2A 的 Task 是异步的，提交后轮询或等待 SSE 推送，因为 agent 执行复杂分析可能需要几分钟到几小时。当你委托的对象是一个有推理能力的系统而不是确定性程序时，MCP 的同步模型就不够用了。

【周迅】Lena v0.19 具体怎么配置三个 server？

【窦文涛】配置文件 mcp_config.py 里定义字典 MCP_SERVERS，每个 server 是一个条目，key 是 server 名字，value 包含 cmd 字段——启动这个 server 的命令行数组。filesystem 的命令是 npx -y @modelcontextprotocol/server-filesystem 加上允许访问的目录路径。github 的命令是 npx -y @modelcontextprotocol/server-github，环境变量里带 GITHUB_TOKEN。brave-search 类似，带 BRAVE_API_KEY。

【窦文涛】ToolRegistry 初始化时遍历字典，为每个 server 创建 MCPClient 实例，调 start() 完成 spawn、握手、tools/list，然后注册工具，工具名格式是 {server_name}__{tool_name}——双下划线，比如 filesystem__read_file、github__search_repositories。环境变量缺失的 server 自动跳过不报错，这是优雅降级设计。filesystem server 提供 8 个工具，github server 提供 26 个，合计 34 个，启动时打印工具数量确认接入成功。

【窦文涛】最后讲 MCP 生态现状。Anthropic 官方维护了 20 多个 MCP server——filesystem、github、postgres、puppeteer、fetch、slack、google-drive、sentry 等。社区第三方更多，FastMCP 生态数千个 server，截至 2025 年 GitHub 上能找到的 MCP server 项目超过一万个，覆盖 PostgreSQL、MongoDB、Redis、Slack、Discord、Google Drive、Notion、Brave Search 等主流服务。对于后端工程师，你能想到的 API，大概率已经有人封装好了 MCP server。

【周迅】今晚行动？

【窦文涛】三件事。第一，装 FastMCP，pip install mcp，照本章模板写一个最简单的 server，一个工具函数，跑 mcp.run()，用 MCPClient 连上去调一次，感受完整五步流程。第二，在 start() 里故意注释掉 _stderr_loop 那一行，让 server 往 stderr 打大量日志，观察死锁现象，再加回来，感受这一行代码的分量。

【窦文涛】第三，把 lena-v0.19 的 mcp_config.py 加一个你自己的内部 API，用 FastMCP 包装成 server 接进来，用自然语言对话调用，验证工具名前缀格式和 tools/list 返回的 JSON Schema。下一章第 20 章讲 Docker Sandbox，MCP server 现在以你的用户权限运行，Docker Sandbox 给 Lena 的代码执行一个真正的容器级隔离，让她能安全运行任意不可信代码，爆炸半径收缩到一个可丢弃的容器里。
