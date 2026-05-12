# 第十五章播客脚本：Gateway 与 Channel——让 Agent 住进你的 Telegram

> 风格：tutorial（科普教学）
> 主持人：涛哥（窦文涛）≥95% + 小周（周迅）<5%
> 时长目标：约 30 分钟
> 人名规则：Bob 代替任何真实工程师名，绝不出现作者名

---

【窦文涛】听众朋友好，欢迎来到《从零构建你的 AI Agent》配套播客，我是涛哥。今天聊第十五章，主题是 Gateway 与 Channel——让 Lena 住进你的 Telegram。这是全书架构跨越最大的一章，不是因为代码复杂，大概只有两百行新代码，而是因为它改变了 Lena 的"存在方式"。

【窦文涛】之前 v0.14 的 Lena，你在命令行输入，她回答，然后进程退出。这叫 CLI 模式——来一次，活一次，然后消失。今天结束，Lena 变成 v0.15，她在后台常驻，Telegram 和 Console 两个入口都可以找到她，断线了会自动重连，你关掉终端她还在。

【窦文涛】为什么需要常驻？先从一个具体场景说起。假设你让 Lena 每小时监控某个数据，BTC 跌破七万八就通知你。CLI 模式下这件事完全做不到——你不问她，她就不存在，她无法主动做任何事。你手机上的 Telegram 也联系不到她，因为没有一个持续监听的进程。想让 Lena 真正成为"助手"而不是"计算器"，她必须一直存在、一直等待、一直可达。这就是 Always-on 进程的核心动机。

【窦文涛】你可能会想，那简单，在脚本里写一个 while True 无限循环不就行了？答案是：这是一个直觉陷阱。while True 只能处理一个输入源，你写死了从 stdin 读，想同时接 Telegram 和 Discord？你就得在同一个循环里处理两种协议。

【窦文涛】Telegram 的 polling 是异步的，Discord 的 gateway 协议需要维持长连接的心跳，两套协议生命周期完全不同，硬塞在一个循环里很快变成一堆 if/elif，维护起来是噩梦。另一个方向也走不通：每个 channel 单独跑一个进程，问题是它们共享同一个 Lena 的对话历史——两个进程无法同步这些状态，除非引入 Redis，把应用级问题变成基础设施问题。

【窦文涛】真正的答案是：一个常驻的 Gateway 进程，统一管理所有连接入口，把消息路由到单一的 AgentLoop，每个 channel 作为插件注册进来，只负责"如何收消息、如何发消息"。这是本章要建的东西。

【窦文涛】先把三个核心概念说清楚。第一个概念是 Gateway。Convention 是这样定的：Gateway 是管理连接生命周期加消息路由的进程。乍看它像"一个监听消息的服务器"，但更准确的说法是它是消息交通枢纽——不生产消息，不消费消息，只负责把来自不同入口的消息统一格式化，送到 AgentLoop；把 AgentLoop 的输出，送回到对应的出口。

【窦文涛】Gateway 有两个关键后果。后果一：它对 channel 是透明的——不知道消息是从 Telegram 来的还是从 Discord 来的，只知道"有一条消息需要处理，来自用户 ID=xxx，内容是 yyy"。AgentLoop 也不知道自己的回复最终被发到哪个平台，Gateway 承担了两层之间的适配责任。

【窦文涛】后果二：Gateway 的核心状态是连接表，而不是对话历史。连接表记录哪个 channel 当前处于什么状态；对话历史是 AgentLoop 的内部状态，Gateway 完全不碰。这个分工让两者都保持简单——Gateway 可以崩溃重启而不丢失对话上下文，因为上下文在 AgentLoop 里。

【窦文涛】第二个概念是 Channel。Convention：Channel 是具体的消息入口/出口插件，Telegram/Discord/Console 等都是 Channel。"插件"这个词的含义：Channel 不是核心的一部分，是可以热插拔的扩展。第三个概念是 AgentLoop，就是处理消息、调用工具、生成回复的核心逻辑，前十四章一直在做的东西。

【窦文涛】三个概念的关系：Channel 收到消息，交给 Gateway，Gateway 路由给 AgentLoop，AgentLoop 处理完交回 Gateway，Gateway 通过原来的 Channel 把回复发出去。三者职责不重叠，是本章架构的三个独立关注点。

【窦文涛】为什么 Channel 要做成插件，而不是直接写进 AgentLoop？想象两种实现方式。方式 A，编译时集成：AgentLoop 直接 import TelegramBot，在自己的消息循环里处理各种协议，每次新增一个平台就要改 AgentLoop 的核心代码，接入十个平台就要 import 十个 SDK，处理十种格式差异。

【窦文涛】方式 B，channel as plugin：AgentLoop 只知道一个抽象接口——"发消息"和"收消息"。每个平台实现这个接口，在配置时注册，运行时按需加载。新增飞书 channel 不需要动 AgentLoop 一行代码。方式 A 的问题不只是"不优雅"，它把两类完全不同的变化原因耦合在一起。

【窦文涛】"消息路由逻辑变了"和"接入的平台变了"，这两件事应该独立演进。一句话总结：Telegram 今天改了 API，不应该让 AgentLoop 文件出现 git diff。这个分离让"把每日摘要任务从 Discord 切换到飞书推送"变成只改配置文件一行的事——delivery channel 是配置，intelligence 是代码。

【窦文涛】现在看代码。Beat 4 的脚手架阶段，最小骨架约 45 行。核心是 BaseChannel 接口，定义五个方法：connect、disconnect、onMessage、send、snapshot，加上一个 id 只读字段。onMessage 由 Gateway 注入一个 handler，channel 收到消息后调用这个 handler，handler 返回 Lena 的回复。

【窦文涛】GatewayServer 有一个 register 方法，在运行时调用，把 channel 加进去，不修改 GatewayServer 源码。start 方法做三件事：启动 WebSocket 服务器默认端口 8765、启动 HTTP 服务器默认端口 3000、然后遍历所有注册的 channel，注入 handler，调用 connect。

【窦文涛】骨架阶段的 handler 是一个 echo——直接返回 "[echo] 输入内容"，用来验证消息流转通路。跑起来应该看到三行日志：Gateway WebSocket :8765、Gateway HTTP :3000、Channel [console] connected。这证明通路打通了——用户输入 → channel 收到 → handler 被调用 → 返回值 → channel 发回用户。只是 handler 现在还是 echo，AgentLoop 还没接进来。

【窦文涛】Beat 5 是渐进组装，有四个扩展点。扩展一：接入 AgentLoop。把 onMessage 的 handler 从 echo 换成 agentLoop.run。只需修改 GatewayServer 的构造函数注入 AgentLoop 实例，在 start 里把 handler 换成 const reply = await this.agent.run(content)。接入之后，Gateway 和 channel 退到了"管道"角色，只负责传递，不参与任何 LLM 推理。

【窦文涛】扩展二：ExponentialBackoff 类。这是指数退避机制，处理 Telegram 断线重连。断线重连最朴素的策略是立即重试，但如果服务器短暂不可达，所有客户端同时立即重试会产生惊群效应——服务器刚恢复就被大量请求同时打到，可能再次因过载崩溃，形成正反馈循环。指数退避打破这个循环。

【窦文涛】ExponentialBackoff 类的构造函数有四个参数：initialMs 默认 5000，第一次等 5 秒，覆盖绝大多数网络抖动；maxMs 默认 300000 即 5 分钟，超过 5 分钟的中断通常意味着需要人工干预；maxRetries 默认 10，十次等待窗口约 25 分钟；jitter 默认 0.1 即 ±10% 随机抖动。

【窦文涛】jitter 这个细节值得单独说一下。假设你同时跑了五个 bot，都断线了，没有 jitter 的话它们会在完全相同的时刻发出重连请求；加了 ±10% 随机之后，五个请求分散在 4.5 到 5.5 秒这个区间里，负载平滑很多。Convention：退避是每次重试前等待的延迟策略；抖动是在延迟上加随机量，让多个客户端的重试时间错开。两者通常同时使用。

【窦文涛】这套参数与生产实现 server-channels.ts 第 12 到 17 行一致，是经过生产验证的参数组合，直接复用。nextDelay 方法计算：base = min(initialMs × 2^attempt, maxMs)，然后加上 base × jitter 的随机量，attempt 自增。exhausted 方法判断是否达到最大重试次数，用于外层循环决定是否放弃重连。

【窦文涛】扩展三：带重连的 TelegramChannel。它同时处理三件事：初始连接、断线检测、退避重连。核心结构是两层嵌套：外层 connect 方法是退避循环，内层 tryConnect 是一次真实连接尝试。外层逻辑：先 reset backoff，然后 while not aborted，try tryConnect，成功就 reset 然后 return；失败就检查 backoff.exhausted，没耗尽就 nextDelay 等待后继续。

【窦文涛】内层 tryConnect：创建 TelegramBot 实例并传入 token 和 { polling: true }，设置 message 事件处理，打印"已连接 polling 中"，然后等一个 polling_error 事件——一旦收到 polling_error 就 reject，触发外层 catch 进入退避。disconnect 方法设 aborted = true 然后调用 bot.stopPolling，防止 disconnect 之后继续重连。

【窦文涛】TelegramChannel 还有一个重要设计：allowFrom 白名单检查。allowFrom 是字符串数组，传 ["*"] 表示允许所有人，传 ["123456"] 表示只允许特定用户 ID。白名单检查在 channel 层完成，不在 AgentLoop 层。为什么？第一：防止白名单绕过——在 channel 层检查，未授权消息连 AgentLoop 都进不了，更早更干净。

【窦文涛】第二：不同 channel 有不同策略——Telegram 私聊不需要 requireMention，群组里的 bot 通常需要 @botname 才触发，这个逻辑属于 channel，不属于 AgentLoop。第三：fail-safe 设计——channel 层拒绝是静默丢弃；AgentLoop 层拒绝意味着已经做了 LLM 调用然后说"对不起我不能回复你"，浪费了 token，还向未授权用户泄露"这个 agent 在运行"的信息。

【窦文涛】扩展四：ConsoleChannel 和 /status 端点。ConsoleChannel 是本地调试利器——零依赖，无需 token，用 readline 模块监听 stdin，每行输入调用 handler，把回复打印出来。在接入真实 Telegram 之前，用它测试整个 Gateway + AgentLoop 的流程，不需要申请 Bot Token，不需要配置 webhook。

【窦文涛】Gateway HTTP 服务增加 GET /status 端点，返回各 channel 的 snapshot：id、status（running 或 stopped）、retries（重连次数）；还有 wsConnections 和 uptime（进程运行秒数）。uptime 的价值：如果你看到 uptime 是 5 秒，说明进程刚刚重启过，这是隐性的崩溃信号。retries 是 3，说明发生过三次断线重连而你毫无感知——这正是退避机制正常工作的证明。

【窦文涛】Beat 6 是运行验证。完整的 lena-v0.15 的 main.ts：创建 AgentLoop 实例，创建 GatewayServer 注入 AgentLoop，注册 ConsoleChannel，如果环境变量 TELEGRAM_BOT_TOKEN 存在就注册 TelegramChannel，传入 token 和从 TELEGRAM_ALLOW_FROM 解析的白名单，最后 await gateway.start。SIGINT 信号处理会优雅关闭所有 channel。

【窦文涛】申请 Telegram Bot Token：打开 Telegram，搜索 @BotFather，发送 /newbot，按提示操作，拿到形如 7xxxxxxxx:AAxxx 的 token。再发消息给 @userinfobot 获取你的用户 ID，填入 TELEGRAM_ALLOW_FROM。如果发了消息没有回复但也没报错，大概率是 TELEGRAM_ALLOW_FROM 填的不是你的用户 ID——先去掉这个变量默认允许所有人，确认可用后再加白名单。

【窦文涛】本章 TelegramChannel 有一个已知局限性：每次接收消息都创建新的 AgentLoop run 调用，同一用户发两条消息，第二条不会记得第一条——messages 数组没有按用户 ID 分隔。多用户会话管理是第十六章 MessageBus 之后加入的能力，本章假设"只有一个用户在使用"，在单人私用场景完全够用。

【窦文涛】Beat 7 是 Design Note，正式回答这个问题：为什么不把 channel 编译进 AgentLoop？直接编译进去代码量减少约 30%，目录更扁平，看起来更简单。但 tradeoff 有三条：测试困难、新增 channel 等于改核心、无法运行时动态控制。这三条都指向同一个根因：把两类变化速率不同的东西放在了一起。

【窦文涛】plugin 方案的代价是模板代码：BaseChannel 接口约 20 行，每个 channel 实现五个方法，有一定的样板代码。但换来的是：Telegram 的 API 更新、Discord 的 gateway 协议变化，这些都不触碰 AgentLoop。delivery 路径是配置，intelligence 是代码，两者的变化原因不同，就应该放在不同模块里。

【窦文涛】这个设计在生产级别可以走到更极致的形态：每个 channel 是一个独立的 npm 包，通过 package.json 里的 openclaw 字段声明自己是 channel，gateway 启动时动态扫描已安装的包，不需要重新编译就能新增 channel。本章的 lena-v0.15 是这个设计的教学版，用静态注册代替动态发现，保留核心思想的同时大幅降低复杂度。

【窦文涛】另一个值得直视的差距：nano-claw 的 gateway/server.ts 是 219 行，描述了完整的消息路由骨架；而生产系统的 src/gateway/ 目录下有约 230 个文件，处理鉴权、TLS、Tailscale 暴露、配置热重载、多账号管理、健康检查、metrics 等数十个生产级关切。这不是过度设计，而是生产系统真实的复杂度。本章带你建的是 219 行教学版；230 个文件的产品级细节，在你需要它们的时候，你已经有了足够的上下文去阅读和理解。

【窦文涛】这一章的本质用一句话说：Lena 第一次跨界面运行，从"运行完就死"的 CLI 工具变成常驻后台进程。这章之前所有章节都在增强 Lena 的大脑，这章改变的是她的存在方式——从"工具"变成"助手"。约 200 行新代码，是整本书里架构跨越最大的一步。

【周迅】"存在方式"的改变，比单纯加新能力感觉更本质。

【窦文涛】对。一个助手再聪明，如果她只在你敲门时才出现，她能帮到你的就很有限。Always-on 解锁的核心能力不是"能做什么"，而是"什么时候能做"——包括你睡觉的时候，包括你没意识到需要帮助的时候。下一章讲 MessageBus，134 行代码，解决下一个问题：当你同时有 Telegram 和 Discord 两个 channel，Cron job 需要向特定 channel 推送消息时，谁来做路由决策？MessageBus 把"谁发消息"和"谁收消息"彻底解开，用 pub/sub 模式，让 Lena 不用知道谁在听。我们下期见。

---

*约 4000 字 / 预计 TTS 时长 ~26 分钟（语速 1.1x）*
