【窦文涛】听众朋友好，欢迎来到《从零构建你的 AI Agent》配套播客，我是涛哥。今天我们聊第十六章，标题叫 MessageBus 与事件驱动——解耦 Channel 与 Agent。副标题我自己给补一句：一个 Channel 崩了，不能拖垮整个 Agent。

【窦文涛】先给大家交代一下路线图。上一章，Lena 从命令行工具变成了常驻进程，有了 Telegram 和 Console 两个 Channel 入口，这是 v0.15。那 v0.15 有什么遗留问题？表面上看好像挺完整的，但里面有一颗定时炸弹，一旦 Lena 连接的 Channel 多了，这颗炸弹就会引爆。今天这章的核心任务，就是拆弹，把 Lena 升级到 v0.16。

【周迅】听着倒是还好，炸弹在哪？

【窦文涛】我先用一段代码来展示这颗炸弹长什么样。v0.15 的 Lena 大概是这么写的——构造函数里直接创建 TelegramChannel 和 DiscordChannel，把自己的 `_handle` 方法作为回调传进去。收到消息时，`_handle` 里面顺序调用三件事：agent_loop 处理消息、logger 记录日志、analytics 统计数据。

【窦文涛】现在想加第三个 Channel：HTTP。你要改构造函数，加一行。同时想加一个新的 subscriber——NotificationService，VIP 用户消息时发邮件。你要改 `_handle`，加一行调用。4 个 Channel、4 个 subscriber，`_handle` 就要处理 16 次显式调用，全挤在一个函数里。

【周迅】等等，一个函数管 16 个调用？

【窦文涛】对，N 乘 M，这是第一个问题，耦合爆炸。但更要命的是第二个问题：运行时的崩溃传播。很多人意识到串行调用慢，会改成 asyncio.gather，让所有 subscriber 并发执行。asyncio.gather 的默认行为是什么？如果 gather 里面任何一个 coroutine 抛出异常，gather 立即把那个异常向上传播，同时取消所有其他仍在运行的 coroutine。

【窦文涛】所以你的 analytics 服务如果因为数据库连接失败抛了个 RuntimeError，gather 收到这个异常，立刻 cancel 掉正在处理消息的 agent_loop 和正在写日志的 logger。结果就是：Telegram 用户发了一条消息，Lena 没有回复。不是 Telegram 出问题了，是 analytics 的异常通过 gather 传播到了整个处理管道，一个组件崩了，全局受影响。

【窦文涛】这在真实场景里就是"厨房着火，全船沉没"。造船工程里有个叫做隔仓设计（Bulkhead Pattern）的方案——船体分成多个独立水密仓，一个仓进水，水密壁阻止水流扩散，整艘船不沉。我们 Agent 里需要同样的东西。

【周迅】船不沉就够了，不是一定得全好。

【窦文涛】没错。那解决方案是什么？很简单，8 行代码。在每个 handler 的调用外面各包一层 try/except，把每个 handler 变成一个"安全版本"，然后把这些安全版本一起 gather。这个包裹层就是 `_safe_call`，或者叫 safeHandlerCall。

【窦文涛】它的行为规范非常清晰：调用 `await handler(message)`，如果抛出任何 Exception，捕获它，记录 logger.error 保留可追溯性，然后 return，不 rethrow。从 gather 的视角看，每个 safe_call 都是正常完成的 coroutine，不会触发 gather 的异常传播逻辑。

【窦文涛】这是本章最重要的工程决策，8 行代码。粒度是关键——不是在 gather 外面套一个大的 try/except，而是在每个 handler 外面各套一个小的 try/except。大的 try/except 是"一个出错全体停"，小的 try/except 是"谁出错谁自己扛，不影响别人"。

【窦文涛】不过，safeHandlerCall 只解决了第二个问题——崩溃传播。第一个问题，N×M 耦合，还没解决。每加一个 channel 或 handler，代码改动依然会扩散。这就需要第二个工具：pub/sub。

【窦文涛】pub/sub 全称 publish-subscribe，发布订阅。核心思想是在消息的生产者和消费者之间插入一个中间层——Bus 或者 Broker 或者 Topic，让两者互不知晓对方的存在。我们先统一术语，后面不混用。Publisher = 往 Bus 发消息的一方，也就是 channel，比如 TelegramChannel；Subscriber = 从 Bus 接收消息的一方，也就是 handler 函数；topic = 消息的路由标签，在本章实现里等同于 channel_type，比如字符串 "telegram"。

【窦文涛】直连架构里，每个 Publisher（channel）必须显式持有每个 Subscriber（handler）的引用并直接调用。N 个 Publisher，M 个 Subscriber，有 N×M 条依赖边。加一个新的 Subscriber，要改 N 个 Publisher 的代码；加一个新的 Publisher，要改 M 个 Subscriber 的代码。系统改动成本随乘积增长。

【窦文涛】引入 Bus 之后，拓扑从全连接图变成星形图。Publisher 只连 Bus（N 条边），Subscriber 只连 Bus（M 条边），总计 N+M 条边。加一个新的 Subscriber，只需在 Bus 上注册一次，不改任何 Publisher。这个从乘法到加法的转变，就是 pub/sub 的核心价值。

【窦文涛】为了让大家知道今天实现的 MessageBus 在整个技术谱系里处于哪个位置，我快速过几个典型实现。Apache Kafka 是跨机器的 pub/sub——topic 是持久化日志，可以从任意时间点回放；Redis pub/sub 是跨进程的，发消息所有订阅进程立刻收到，但不持久化；Dapr 的 pub/sub building block 屏蔽了底层 broker 差异，应用代码不需要知道消息走的是 Redis 还是 Kafka；asyncio.Queue 是 Python 标准库里进程内的消息队列，适合异步协程之间传递数据。这四个都是 pub/sub，区别只在规模和持久化需求，今天我们选最轻的那个。

【窦文涛】本章实现的 MessageBus 是进程内的 pub/sub——没有网络 round-trip，延迟是微秒级，但进程重启消息丢失。个人 Agent 不需要 Kafka，需要的是进程内 Bus 的简洁性和零运维成本。

【窦文涛】我们把这套 pub/sub 思想放到更大的坐标系里定位一下。Anthropic 的架构白皮书里列出了多 Agent 协作系统的三种协调模式：Group chat（agents 通过共享对话线程自然语言协调）、Blackboard（共享知识仓，所有 agent 可读写，是集体记忆）、Event-driven（事件作为共享语言，结构化更新驱动协作）。本章的 MessageBus 对应的正是第三种，event-driven coordination 模式——ChannelMessage 是结构化事件，publish 是事件发布，subscribe 是事件订阅。

【窦文涛】白皮书里还有一句工程警告，值得在实现 MessageBus 时牢记："small changes can unpredictably affect how agents behave"。这正是为什么 pub/sub 解耦比直接调用安全。直连架构里，加一个新的 subscriber 意味着修改 publisher 的代码，是一次"小改动"，却可能触发意外的行为变化。Bus 架构里，加一个 subscriber 只需调用 `bus.subscribe()`，publisher 的代码完全不知道这件事，也不受影响。

【窦文涛】有了 pub/sub 的理论坐标，我们可以直接动手实现了。MessageBus 的核心数据结构非常简洁。维护两类订阅：一个是 `_handlers`，类型是 `dict[str, set[MessageHandler]]`，key 是 channel_type，value 是该 channel 订阅的 handler 集合；另一个是 `_global_handlers`，类型是 `set[MessageHandler]`，全局 handler，任何 channel 的消息都触发。

【窦文涛】为什么是 Set 而不是 list？因为同一个 handler 注册两次，Set.add 是幂等的，不会重复调用。为什么是两个独立的数据结构，而不是在同一个结构里用标签区分？因为数据结构的分离保证了两类 handler 的管理逻辑不互相干扰。nano-claw 是本书配套的参考实现仓库，TypeScript 版本里的 `bus/index.ts` 就是这么设计的：`handlers: Map<string, Set<MessageHandler>>` 和 `globalHandlers: Set<MessageHandler>` 是两个独立字段，Python 版我们保持同样的结构。

【窦文涛】消息体 ChannelMessage 是一个 dataclass，5 个字段：channel_type 消息来源、user_id 发送者标识、content 消息正文，再加上有默认值的 id（uuid4 生成）和 metadata 字典。

【周迅】global 和 specific 同时存在，一条消息会被处理两次吗？

【窦文涛】这就要讲 globalHandlers 和 channel-specific handlers 的区分，这个设计选择是避免重新引入 N×M 问题的关键。channel-specific handlers 用 `subscribe("telegram", handler)` 注册，只在 channel_type 等于 "telegram" 的消息来时触发。AgentLoop 是典型的 channel-specific subscriber——它需要知道消息来自哪个 channel，Telegram 有 chat_id，Discord 有 guild_id，这些都在 metadata 里。

【窦文涛】global handlers 用 `subscribe_all(handler)` 注册，任何 channel 的任何消息都触发。Logger、Analytics、成本统计、安全审计这类横切关注点对消息来源无感知，只关心"有消息发生了"，不关心"消息从哪里来"。

【窦文涛】把横切关注点注册成 global handler 的关键好处是：加一个新的 channel，Logger 不需要任何改动。Logger 注册了一次 `subscribe_all`，之后无论有多少个 channel，它都自动收到所有消息。如果 Logger 是 channel-specific，加 channel 就必须同步更新 Logger 的注册，这是在 Bus 层复现 N×M 的耦合。判断规则很简单：handler 需不需要知道消息来自哪个 channel？需要的用 subscribe，不需要的用 subscribe_all。

【窦文涛】publish 方法的实现有一个细节必须注意。不能直接 `asyncio.gather(h(msg) for h in self._handlers.get(ct, set()))`，而要先快照——先 `list(self._handlers.get(ct, set()))` 转换成 list，再 gather。不快照直接 gather 的话，handler 执行期间若有 unsubscribe 调用，会触发"set changed size during iteration"的运行时错误。快照之后再 gather，可以避免这个并发修改的竞争。

【窦文涛】好，现在我们一步步组装。第一步，验证 safeHandlerCall 的隔离效果。注册三个 handler：agent_loop 正常，buggy_logger 故意 raise RuntimeError，analytics 正常。运行之后，应该看到 agent_loop 和 analytics 都执行了，buggy_logger 的错误被记录为 ERROR 日志，但没有传播。注意输出顺序可能不固定，因为三个 handler 是并发执行的，谁先打印取决于调度，这是 asyncio.gather 的并发语义，是预期行为。

【窦文涛】第二步，定义 ChannelPlugin 基类。热插拔需要 channel 能独立启动和停止，所以定义一个抽象基类，强制子类实现：一个 channel_type 只读属性、一个 start 方法、一个 stop 方法、一个 receive 方法。

【窦文涛】receive 方法的职责是：把收到的外部消息转换成 ChannelMessage，调用 `self.bus.publish(msg)` 发到 Bus。channel 是 Publisher，不持有任何 Subscriber 的引用，这是 pub/sub 解耦的体现。receive 在 self._running 为 False 时会 raise RuntimeError，防止未 start 的 channel 发布消息。

【窦文涛】第三步，ChannelManager，运行时管理所有 channel。内部维护一个 `_channels: dict[str, ChannelPlugin]` 字典。attach 方法：检查 channel_type 是否已存在（已存在就 raise ValueError，不允许重复 attach），然后把 channel 存入字典，调用 `await channel.start()`。detach 方法：从字典 pop 出 channel，调用 `await channel.stop()`，channel_type 不存在时静默忽略。

【窦文涛】验证热插拔的顺序是：只 attach telegram 时发消息（确认正常），运行中 attach discord 发消息（确认新 channel 立即生效），detach telegram 再发 discord 消息（确认 telegram 消失但 discord 不受影响）。三个中间状态都有打印输出作为检查点。最后确认 handler_count() 返回 4——2 个 channel-specific 加 2 个 global。这个数字验证了没有 handler 泄漏。

【窦文涛】有几个常见报错值得提一下。"RuntimeError: Channel 'X' not started"——直接调用了 channel.receive() 没先 await manager.attach(channel)；"set changed size during iteration"——handler 执行时有 unsubscribe 调用，修复是 publish 里先 list() 快照再 gather；"TypeError: object bool can't be used in 'await'"——handler 忘了加 async。三个报错各有明确修复，遇到时对照即可。

【窦文涛】v0.16 跑通了，三个场景验证通过。但我猜有人这时候会有一个疑问：这套进程内 Bus 和 Kafka、Redis Streams 解决的不是同一个问题吗？为什么不直接用那些成熟系统？这是个好问题，值得认真回答。

【窦文涛】我来做一个对比。进程内 MessageBus：运维成本零，无依赖，消息延迟约 1 微秒（函数调用级别），没有消息持久化，不支持回放，不支持水平扩展，适合每秒消息量在 10,000 以下的场景。Redis pub/sub：需要 Redis 实例和连接管理，延迟 0.5 到 2 毫秒，没有持久化，支持多消费者，适合每秒 100,000 以下。Kafka：Kafka 加 ZooKeeper 或 KRaft 加监控，延迟 5 到 20 毫秒，有持久化和消息回放，支持 consumer group，适合每秒超过 100,000 的场景。

【窦文涛】Lena 是单机 personal agent，channel 数量个位数，消息量每分钟几十条，峰值每分钟几百条。在这个规模下，进程内 Bus 的 1 微秒延迟对比 Redis 的 1 毫秒延迟，差距是 1000 倍。对交互式 agent 来说，这个延迟差在"快到感觉不到"和"已经感觉到轻微迟滞"之间。更重要的是，引入 Redis 引入了 5 个新的运维问题来解决一个在当前规模下根本不存在的问题，这不是工程决策，是工程债务。

【窦文涛】什么时候该换成分布式 MQ？当 Lena 需要跨机器运行时——主 agent 在服务器 A，Telegram channel 在服务器 B，两个进程之间的通信必须有网络传输，Redis pub/sub 是最简单的选择。或者消息量因为多租户超出单进程处理能力时。切换成本很低：替换 MessageBus.publish 的实现，改成 redis.publish()；把 subscribe 改成 Redis 订阅逻辑。上层 channel 代码和 handler 代码完全不变。这是进程内 Bus 设计的最大优点：接口稳定，实现可替换。

【窦文涛】今天这章的三个核心决策值得记下来。第一，两类 handler 的设计：channel-specific 负责有上下文依赖的业务逻辑，global 负责横切关注点，这个区分把"是否在 Bus 层复现 N×M"变成了一个有答案的判断题，新增 channel 时 global handler 零改动。

【窦文涛】第二，_safe_call 不是 return_exceptions=True——前者把隔离做在每个 handler 内部、保留日志和错误事件，后者是静默吞掉错误，两者在可观测性上天差地别。第三，publish 里的 list() 快照不是优化，是正确性保证——Set 在迭代期间不能被修改，这是 Python 语义约束。v0.16 的 Lena 由此获得三项新能力：任意 handler 崩溃不影响同批；运行时 attach 不重启；运行时 detach 不重启。

【窦文涛】下一章，Lena 有了 MessageBus，任何 channel 崩了不影响整体。但 Lena 现在还是完全被动的——只有用户发消息，她才响应。第十七章，我们给 Lena 加 Heartbeat。Heartbeat 是 MessageBus 的一个特殊 Publisher：消息不来自用户，来自时钟。每次 tick，Heartbeat 向 Bus 发布一条 system:heartbeat 消息，AgentLoop 订阅它，检查有没有 pending 的定时任务需要触发。这是 Lena 从"被动响应"升级到"主动出击"的基础设施——Heartbeat 给了她自己的生物钟。我们下期见。

【周迅】Lena 终于不只是等人叫了。下期见！
