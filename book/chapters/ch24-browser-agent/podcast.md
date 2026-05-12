【窦文涛】来到第二十四章了，全书大结局，今天讲的是 Browser Agent——让 Lena 真正上互联网的最后一块拼图。在这之前，Lena-v0.23 有三十多个工具、三层记忆、常驻运行、Telegram 推送、MCP 协议扩展、Docker 沙箱。但你给她一个任务——"帮我查微博上的 AI 新消息"——她做不到。

【周迅】为什么做不到？

【窦文涛】不是不够聪明，是架构限制。微博的内容住在 JavaScript 渲染的动态 DOM 里，住在登录态的背后，住在反爬机制的后面。Lena-v0.23 的工具集里没有"操作浏览器"这一项。这是本章要填上的最后一块拼图。

【窦文涛】先做一个测试。用 Lena-v0.23 的工具系统尝试读取微博首页，三种失败模式——第一，web_search 返回登录跳转页，无内容；第二，HTTP 200 但内容是 `<div id='root'></div>`，CSR 空壳，JavaScript 还没执行；第三，403 Forbidden，User-Agent 被识别为非浏览器。

【窦文涛】三种失败对应三个根本原因——内容在登录墙后面、内容在 JavaScript 里、反爬机制识别你。数字化的差距：SPA 动态内容 Lena-v0.23 成功率约百分之五，v0.24 约百分之八十；登录后内容 v0.23 零，v0.24 约百分之七十；需要交互操作 v0.23 零，v0.24 约百分之六十。不加浏览器就是零，这个差距不可弥合。

【窦文涛】在讲实现之前，有一个安全警告必须先讲。Simon Willison 在 2023 年提出的 Dual LLM Pattern 在浏览器 agent 场景下尤其重要——特权 LLM 持有工具控制浏览器，隔离 LLM 处理不可信内容，二者不直接共享 token。

【周迅】为什么要隔离？

【窦文涛】因为浏览器 agent 是最容易被 prompt injection 攻击的 agent 类型——每一个网页都可能包含恶意指令。你的 agent 会主动打开攻击者的网页，然后用 LLM 解析它的内容。不做隔离等于把 agent 的工具控制权交给了互联网上的任何人。

【窦文涛】好，进入四大挑战。第一个，DOM 无穷大——工具输入的"上下文炸弹"。测量结果：微博首页约六千个 DOM 节点，序列化后约八百 KB；GitHub 仓库页约三千节点四百 KB；Amazon 商品页约八千节点一点二 MB。Claude Sonnet 的 context window 是 200K token，八百 KB HTML 刚好撑满。

【窦文涛】工具的返回值如果不加过滤就交给 LLM，会直接把 context window 爆掉。解法核心来自 browser-use 的核心设计——用 JavaScript 在浏览器端完成 DOM 过滤，把六千个节点压缩到五十到两百个可交互元素，再序列化为结构化文本列表传给 LLM。过滤率通常三十到一百倍。

【窦文涛】Convention——"DOM 感知"等于从完整 DOM 中提取可交互元素子集的过程；"DOM 完整序列化"等于把整个 DOM 转为 HTML 字符串的过程。浏览器 agent 必须用前者，绝不用后者。

【周迅】三十到一百倍压缩比，这是关键。

【窦文涛】第二个挑战，页面跳变——Planning 的状态机挑战。三种跳变：硬跳转，点击链接页面完全重新加载，可以用 `page.on('load')` 检测；SPA 路由切换，只有 URL 的 hash 或 pushState 变化，DOM 局部更新，`page.on('load')` 不触发，只能靠 DOM diff 感知；异步内容加载，滚动到底部时新内容动态插入，需要等待 networkidle 或轮询。

【窦文涛】WebArena（2023，Shen et al.）是浏览器 agent 的标准评测集，包含八百一十二个真实 web 任务。评测中页面跳变错误是第二大失败原因，占总失败数的百分之二十七。这个数字说明——页面跳变处理能力是 browser agent 成熟度的重要指标。

【窦文涛】第三个挑战，反爬与人机验证——Safety 的外部边界。反爬分四个层次。L1 请求特征，User-Agent 和 Headers，简单字符串匹配；L2 浏览器指纹，`navigator.webdriver` 和 Canvas 指纹，JS 检测；L3 行为模式，鼠标轨迹、点击间隔、滚动速度，机器学习分类器；L4 风险信号，IP 声誉和账号行为历史。

【窦文涛】Headless Chromium 天然触发 L2，`navigator.webdriver` 默认为 true，可被 JS 检测到。Lena-v0.24 的设计选择是不对抗反爬。L3 和 L4 需要极复杂的模拟，军备竞赛没有终点。使用用户真实 Chrome profile 天然绕过 L1 和 L2，是合法且稳定的方案。三层 fallback 保证浏览器路径失败时有退路。

【窦文涛】第四个挑战，登录态——Memory 的最大价值场景。一个能操作用户真实 Chrome profile 的 agent，天然继承了用户在所有网站上的登录状态。不需要密码，不需要绕过 2FA，不需要维护 Cookie 池。Cookie 存储在 Chrome profile 的 Cookies 数据库文件里，CDP 连接到该 profile 时天然可以访问。

【窦文涛】登录态唯一真正的难点是 Cookie 过期。会话过期时浏览器跳转到登录页，agent 必须感知"我不在预期的页面"，然后暂停任务并通知用户重新登录——而不是继续在登录页上做无意义的操作。

【周迅】四大挑战都讲了，怎么组装？

【窦文涛】进入脚手架。最小可运行的 Browser Agent 骨架只做一件事：接受任务描述，返回结果。关键是连接到已有 Chrome，不是启动新的 headless 实例。BrowserConfig 里 cdp_url 指向 `ws://localhost:9222`，headless=False。为什么选 Sonnet 不选 Haiku？浏览器任务需要多步推理，Haiku 在三步以上决策失败率约百分之三十五，Sonnet 约百分之十二。

【窦文涛】有一个踩坑必须注意——Clash 的 fake-ip 模式拦截所有 DNS 包括 localhost，导致 CDP socket 连接被路由到代理。在任何 CDP 操作前必须清除代理环境变量，把 http_proxy、https_proxy、all_proxy 等全部 pop 掉，这行代码必须在 import 完毕后、第一次 CDP 连接前执行一次。

【窦文涛】骨架能跑之后，渐进加四个扩展，每次只加一个。扩展一是 Tab 保护——铁律，Chrome profile 里可能有用户正在编辑的文档、未保存的表单、活跃的视频会议，不能覆盖。实现：任务开始前快照所有 tab ID，任务结束时关闭所有新增 tab，清理逻辑放在 finally 块确保异常也执行。

【窦文涛】关键细节：关闭 tab 用 `PUT /json/close/{tabId}`，不是 GET。CDP HTTP 接口规范要求 PUT，用 GET 在新版 Chrome 上会 404。很多老教程写的是 GET，读者照着做会踩这个坑。同样，创建新 tab 用 `PUT /json/new`，不是 `GET /json/new`。

【窦文涛】扩展二是三层 fallback，浏览器路径失败时有退路。FallbackChain 类用装饰器把函数加入 fallback 链，每层失败自动降级。以微博任务为例——层一 RSSHub，无需登录，响应最快，成功率约百分之九十，缺点只有推送内容通知无法获取；层二本地 CLI 工具，约百分之七十；层三 browser-use 真实浏览器，约百分之四十到六十，速度最慢但能访问完整内容。

【周迅】三层合起来成功率多少？

【窦文涛】各层独立失败的联合概率——百分之十乘以百分之三十乘以百分之五十约等于百分之一，所以整体约百分之九十九。

【窦文涛】扩展三是审批门控，浏览器有真实副作用——点击"提交订单"就真的下单了。approval_gate 检查 action_description 是否含 submit、purchase、buy、order、delete、transfer、pay、checkout、confirm、book 这些词，如果是则打印警告等待用户确认，输入 yes 才继续，否则取消。

【窦文涛】扩展四是进程锁。cron 任务可能重叠执行，两个 CDP 进程同时操作同一 Chrome 会导致截图错误和 tab 状态混乱。BrowserLock 类用 fcntl.flock 文件锁实现，加锁失败时抛 RuntimeError 提示另一个 browser agent 正在运行，本次跳过。

【窦文涛】三个端到端任务验证，按复杂度递增。任务一查微博新消息，browser-use 内部决策步骤：navigate 到 weibo.com、wait_for_load 到 networkidle、截图感知、analyze 寻找通知图标、点击进入通知页面、extract_content、返回 JSON。常见失败路径之一是 Cookie 过期进入登录页，检测 URL 是否为 login.weibo.com，若是则返回 AUTH_EXPIRED 并通知用户。

【窦文涛】任务二表格导出 CSV，让 agent 找到页面主要数据表格并提取为 JSON。这个任务验证的是 browser-use 的 DOM 语义分析能力——agent 需要区分导航栏、文章内容和数据表格，这三者的结构差异是语义层面的，不是 CSS 类名层面的。

【窦文涛】任务三查高铁票，约十二步操作：navigate 到 12306、填写出发站和到达站、处理自动补全下拉、选择日期（12306 的日期组件是自定义的，不是标准 input type=date，需要截图分析才能交互）、点击查询、等待结果、提取 G 字头车次列表、返回 JSON 数组。安全声明：此任务只执行查询，不执行购买，购票通过单独的审批门控保护。

【周迅】三个任务难度递增，设计很清晰。

【窦文涛】下面是三个 Design Note。Design Note 一：为什么 Browser Agent 是 agent 工程的"期末考试"？替代方案是为每个网站写专用爬虫，问题是维护成本随网站数量线性增长，网站改版所有爬虫失效，无法处理通用任务。Browser Agent 的维护成本是固定的，不随网站数量增长，且能随 LLM 能力提升自动变好。

【窦文涛】生产系统的平衡点是三层 fallback 架构——对高频任务写专用 RSS 或 API 层作为 L1，browser agent 降为 L3 保底；对低频、不确定的任务，browser agent 就是首选路径。这不是"全用 browser agent"，而是按任务频率和可靠性要求选路径。

【窦文涛】Design Note 二：为什么不全用原生 CDP 而要用 Playwright？CDP 延迟最低精确控制，但 API 动词是 methodName 格式，比如 `Page.captureScreenshot`，认知成本高；无自动等待，Playwright 的 auto-waiting 需要自己实现；无内置重试，连接丢失需要自己处理。browser-use 在 Playwright 上构建，对于"让 LLM 操作 DOM"这个目标，Playwright 的 `page.click(selector)` 比 CDP 的 `Input.dispatchMouseEvent` 组合方便得多。

【窦文涛】决策树：需要 LLM 动态决策每一步，选 browser-use；步骤固定，选 Playwright；需要精确控制且 Chrome 专属，选 CDP 直接调。直接 CDP 仍有适用场景——截图采集精确控制 viewport 和 DPR、tab 创建和管理、不需要 LLM 参与的固定流程。

【窦文涛】Design Note 三：六大支柱都到齐了。Tool 统一性——浏览器操作等于工具，click、type、scroll、screenshot 都是 agent 工具；Planning——ActionHistory 加 max_steps 保护多步任务；Long-horizon——截图序列加 DOM 感知加页面跳变处理；Memory——Chrome profile Cookie 继承登录态加 ActionHistory；Safety——Tab 保护加审批门控；Specialization——LenaBrowserAgent 继承 LenaAgent 基类。

【窦文涛】这不是偶然的。Browser Agent 是唯一一个能同时考验所有六个支柱的场景，这就是它作为全书大结局的原因。

【窦文涛】六条 CDP 血泪教训，来自真实生产系统。教训一，不能发 Origin 头。CDP WebSocket 被 403 拒绝，根因是 Chrome CDP 只允许 localhost Origin 或无 Origin，发任何其他 Origin 头都被拒。websockets 库默认不发 Origin，直接连就好，不要手动加 extra_headers Origin 头。

【窦文涛】教训二，必须清除代理环境变量——Clash fake-ip 拦截 localhost DNS，CDP socket 被路由到代理。教训三，进程锁防并发——cron 任务重叠时两个 CDP 进程同时操作同一 Chrome 导致截图错误，用 fcntl.flock 解决。

【周迅】其他三条呢？

【窦文涛】教训四，Tab 必须主动清理。Chrome 运行两百次采集后内存耗尽 CDP 超时，打开一看有两百多个空白 Tab。CDP 创建的 Tab 不会在脚本退出时自动关闭，脚本崩溃或超时 Tab 会永久留存。清理逻辑放在 finally 块，无论成功失败都执行。

【窦文涛】教训五，截图小于八十 KB 是空白页。页面加载失败或白屏错误会返回一张全白截图，大小通常五到三十 KB。把这张截图直接交给 LLM，LLM 会判断"页面是空白的"导致错误决策。八十 KB 阈值来自真实数据统计——空白页通常小于二十 KB，有内容的最小页面通常大于八十 KB。

【窦文涛】教训六，`/json/new` 和 `/json/close` 用 PUT 不用 GET。Chrome CDP HTTP 接口规范要求——`GET /json` 列出所有 Tab；`PUT /json/new` 创建新 Tab；`PUT /json/close/{tabId}` 关闭 Tab。很多老教程写的是 GET /json/new，在旧版 Chrome 上可能偶然工作，新版直接 404。

【窦文涛】全书回顾快走一遍。第一章到第三章，Lena 诞生，五十行 Python，六个模块：Config、Provider、Memory、ToolRegistry、AgentLoop、Skills。第二章理解了 ReAct 循环，Reasoning、Acting、Observing 无限重复，这个循环是几乎所有 agent 框架的基础原子。

【窦文涛】第四章到第七章，工具系统和流式并发，工具有 isReadOnly 和 isDestructive 标志，让 LLM 知道这个工具安不安全能不能并发。第八第九章，记忆和 RAG，Lena 从"每次对话重新认识你"变成"记得你上次说什么"。第十章 Context Engineering，不是如何让模型更聪明，而是如何在有限 context window 里表现最好。

【窦文涛】第十一章 Planning 和 Subagent，Lena 从单线程执行变成能拆任务能派子 agent。第十三十四章安全双章，执行层八道防线。第十五到十七章，Gateway、MessageBus、Heartbeat，Lena 不再是被动工具而是有主动性的助手。第十八章 Cron 和长任务，能处理跨天任务能从断点续传。

【窦文涛】第十九章 MCP 协议，两百行代码让 Lena 连接任何 MCP server。第二十章 Docker Sandbox，生产级代码执行环境。第二十一章 Evals，量化评估 agent 质量。第二十二章可观测性与部署，结构化日志、token 预算、launchd 守护进程。第二十三章专用化，一行 fork 一个专用 agent。第二十四章，你在这里。

【窦文涛】你真正构建了什么？表面上是一个 Python 写的 agent runtime，集成了 LLM API、Tool 系统、记忆、规划、安全、部署、评估、MCP、浏览器。更深层，你理解了一件事——agent 是"感知加记忆加推理加行动加自我监控"的组合，这个结构在五十行代码里成立，在三千行代码里也成立，在 Python 里成立，在 TypeScript 里也成立。

【窦文涛】六大支柱是这个结构的六个维度——Tool 统一性是 action 层，能做什么；Planning 是推理层，如何分解目标；Long-horizon 是记忆层，如何跨步骤保持状态；Memory 是知识层，知道什么记得什么；Safety 是监控层，什么不能做；Specialization 是身份层，我是谁我擅长什么。通用 agent 不是目标，理解这个结构才是目标。一旦理解了结构，就能构建任何专用 agent。

【窦文涛】三条接下来可以做的方向。方向 A 自动化晨报 agent——浏览器能力加 Cron 定时任务加 Telegram 推送，每天早七点自动浏览五个你关注的信源，LLM 提取今日重要内容生成五百字摘要，TTS 合成音频八点整推送，估计工作量两到三天，难点是内容去重和摘要质量评估。

【窦文涛】方向 B 闲鱼挖宝 agent——每三十分钟扫描特定关键词，LLM 判断性价比，发现阈值以上商品立即推送，估计工作量一周，难点是闲鱼反爬较强（L3 和 L4 级），行为模拟复杂，闲鱼频繁改版。方向 C 自己的 AI 编程结对——Lena 读你的代码仓库，当你打开某个 issue 时自动分析相关代码生成上下文摘要，估计工作量两周，难点在 IDE 集成。

【周迅】涛哥，这二十四章走下来，真不容易。

【窦文涛】是的。最后一句话——agent 不是某个产品，而是一种构建软件的新范式。以前我们把逻辑硬编码，程序按预设路径执行；现在有了 agent，程序可以根据环境动态决策，自己选择路径。从确定性到概率性，从预设路径到动态规划，从被动执行到主动感知。Lena 从 v0.1 走到 v0.24，你亲手经历了这个转变的每一步。技术这本书已经教给你了，接下来就看你怎么用它去改变工作和生活了。
