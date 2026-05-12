【窦文涛】今天讲第十七章，Heartbeat，让 Agent 主动找你。先说一个数字。把 Ch16 的 Lena 跑起来，等满 24 小时，统计她主动发出的消息数量——零条。进程一直在跑，通道一直连着，但 24 小时里她一句话都没主动说。这就是"always-on"的悖论：进程活着，但 agent 在行为上是死的。

【周迅】一句话都没有？

【窦文涛】因为 Ch16 的架构是纯 Reactive 的——你发消息她才动。你不发消息，她永远在等。想象一个真实场景：你是工程师，让 Lena 监控生产环境。凌晨 2:30，某个后台任务静默失败。早上 9:00 你才来上班，整整 6.5 小时没人知道。为什么？因为 Lena 在等你问她"有没有问题"。她不会主动开口。

【窦文涛】最直觉的修法是在 agent 外面加一个系统 cron，每小时发一条假消息给 Lena。这能跑，但有三个问题：时间控制逻辑泄漏到了 agent 外部；active-hours 的判断要在两个系统里分别维护；Lena 收到的是假消息，她无法区分用户指令和 cron 指令，这会破坏对话历史的语义完整性。

【窦文涛】真正的解法是把时间感知长进 agent 本身。这就是本章的主题——Heartbeat，心跳机制。Lena 从 v0.16 升到 v0.17，新增的核心能力只有一条：**每天 08:00，不等任何人发消息，主动推送早报到 Telegram**。实现这个能力的增量代码，加起来 178 行。

【窦文涛】在讲实现之前，先把最重要的理论讲清楚，因为很多人会把这件事理解错。Proactive agent 不是"更勤快的 Reactive agent"。这不是实现细节的差异，这是**控制权归属**的根本不同。

【窦文涛】Reactive agent 的控制权完全在用户端：用户决定何时触发、触发什么、触发多频繁。agent 的价值取决于用户的主动性——用户忘了问，agent 永远不说。用户不知道该问什么，agent 也没有价值。这和搜索引擎的结构本质上一样：强大，但被动。

【窦文涛】Proactive agent 的控制权部分转移到 agent 端：agent 持有自己的时间感知，知道"现在是 08:00，这个时间点对用户有价值"，知道"后台任务在 2:30 失败了，用户应该知道"。Karpathy 在 2024 年 Intro to LLMs 里说："increasingly, we'd want models to have agency and to be able to take actions in the world"。在世界里主动采取行动的前提，是 agent 能感知时间、主动判断何时行动。

【窦文涛】Convention 定下来：**Reactive** = 等外部事件触发后才运行；**Proactive** = 自持时钟，主动判断何时运行。这两个词后续统一用。没有 Heartbeat 的 always-on agent，"always-on"只是运维状态描述（进程没挂），不是能力描述（agent 在工作）。两者的区别就像急诊室和健康监测 app——急诊室功能更强，但你必须知道自己需要去，才能得到帮助。

【周迅】把时钟搬进去，就能解决？

【窦文涛】搬进去只是第一步，关键是时钟要有判断力。一个可用的 Heartbeat 系统需要回答三个正交的问题：**何时触发**、**是否推送**、**推到哪里**。这三个问题构成了从 178 行甜点版到 OpenClaw 生产版的能力阶梯，也是本章代码的三个扩展点。

【窦文涛】第一个问题，何时触发，时间门控。最简方案是固定 interval，每 N 分钟检查一次。这已经能工作了，但有一个核心问题：凌晨 3 点的触发毫无意义——用户在睡觉，就算生成了内容也没人能看到。生产方案要加 active-hours，只在用户的活跃时间窗口内推送。

【窦文涛】active-hours 必须做时区感知。服务器可能跑在美国西部（UTC-7），用户在上海（UTC+8），时差 15 小时。服务器的"早上 7 点"是用户的"晚上 10 点"。如果用服务器本地时间做 active-hours 判断，结果是在用户凌晨 3 点推送"早上好"。正确做法是用 Intl.DateTimeFormat（TypeScript）或 ZoneInfo（Python）换算目标时区的当前时间，**不要用 new Date().getHours() 或 datetime.now().hour**，那是服务器本地时间。

【窦文涛】第二个问题，是否推送，内容门控。触发不等于推送。每次节拍都应该问一个问题："现在有值得说的内容吗？"如果日历空空、没有任务完成、也没有系统事件，就静默跳过，不发无意义的"今天没什么"。

【窦文涛】OpenClaw 生产版的实现叫 HEARTBEAT_OK 机制——LLM 回了一个 ok token 表示没有实质内容，Heartbeat 静默跳过。178 行简化版用更直接的方式：payload 生成器返回 null，跳过本次节拍。内容门控是 agent 情商的核心体现：知道什么时候不说话，和知道什么时候说话同等重要。一个每次节拍都发消息的 agent，用不了三天用户就会关掉通知。好的 agent 减少用户认知负担，而不是增加——Heartbeat 设计的终极目标是让用户觉得有它比没它安静，而且更省心。

【窦文涛】第三个问题，推到哪里，通道门控。这就引出本章的一个核心教训——独立告警通道为什么不能省。考虑这个场景：你用 Watchdog 监控 OpenClaw，出问题时发 Telegram 告警，告警消息通过 OpenClaw 的 Telegram bot 发出。某天 OpenClaw 崩溃了。Watchdog 检测到崩溃，准备发"OpenClaw 崩溃了"。问题是：这条消息需要通过 OpenClaw 的 bot 发出——而这个 bot 依赖 OpenClaw 的 gateway，gateway 刚刚崩溃了。结果：告警消息静默丢失。故障发生，无声无息。

【窦文涛】这不是一个靠加重试能解决的问题。根因是告警通道和被监控的系统共享了同一个故障点。无论重试多少次，只要 OpenClaw gateway 不可达，所有通过它发的消息都会丢失。Convention：**主通道** = agent 正常工作时的消息通道；**独立告警通道** = 独立于主 agent 运行时的备用告警路径。两个词后续统一用。

【窦文涛】独立告警通道的最小约束：独立进程或独立类；独立 bot token（另一个 Telegram bot）；最小依赖，只用系统级网络库，不依赖任何 agent 模块；单一职责，只做一件事，发 Telegram 消息。这个模式在生产系统里有一个名字：Out-of-band alerting，带外告警——告警信号走的通道，独立于被监控系统的主数据通道。

【周迅】这三层我理解了，怎么跑起来？

【窦文涛】178 行分三个扩展点，逐步组装。首先是最小骨架，约 30 行，一个按计划触发并发出事件的计时器，叫 Heartbeat 类，继承 EventEmitter，构造函数只接收 config（intervalMs 和 enabled 两个字段），没有 generatePayload。这个骨架只证明节拍器能跑通。第一步验证：运行之后每隔 intervalMs 应该看到 beat #N 打印。

【窦文涛】骨架里有一个设计细节值得单独说：调度用递归 setTimeout，不用 setInterval。原因是 LLM 调用可能耗时 5-30 秒，setInterval 会导致节拍重叠——上一次还没完成，下一次就触发了。setTimeout 递归保证：上一次完成，等 intervalMs，才触发下一次。骨架验证通过后，把 Heartbeat 升级成 HeartbeatRunner，增加 generatePayload 注入，加入三个扩展点。

【窦文涛】第一个扩展点，在 tick() 里加 isActiveHours() 判断。这个函数接受 IANA 时区字符串，用 Intl.DateTimeFormat 换算目标时区的当前小时，不在活跃窗口内就直接 return，不调用内容生成器。Python 等价实现用 ZoneInfo，同样不要用 datetime.now().hour。

【窦文涛】第二个扩展点，调用注入的 generatePayload 生成器，返回值是 string 或 null。如果生成器抛异常，只记录日志，**不重新抛出**。Heartbeat 是持续运行的后台系统，单次内容生成失败不应该让整个节拍器崩溃。丢一次节拍比整个系统停止要好。这和 finally(() => scheduleNext()) 的设计一致——无论 tick 成功还是失败，下一次节拍都会按时调度。

【窦文涛】第三个扩展点，生成内容后 emit("outbound", payload)，调用方监听并决定推到 Telegram 还是 Discord 还是飞书。这个解耦让"何时推送"（Heartbeat 的职责）和"推到哪里"（channel 的职责）完全分离——delivery channel 是配置，intelligence 是代码。

【窦文涛】完整组装之后，agent.ts 的入口大约是这样的结构：HeartbeatRunner 注入早报生成器，监听 outbound 事件直接调用 Telegram HTTP API，不走任何 agent gateway。这里直接用 Node.js 内置的 https 模块，不引入任何第三方库，也不依赖 agent 的任何模块——这就是独立告警通道的最小实现。

【窦文涛】运行方式：改 config.json 把 intervalMs 设成 10000（10 秒），weekdays 改成 start:0 end:24（全天 active），npm run dev。10 秒后应该看到 Heartbeat tick#1 打印，然后 Telegram 手机收到早报。验证通过后，把 intervalMs 改回 3600000（1 小时），weekdays 改回 8-22。Heartbeat 每小时唤醒一次检查，第一个落在 08:00 窗口内的节拍发出早报。

【周迅】实际写一个 watchdog，大概多少代码？

【窦文涛】AlertChannel 这个独立类，零依赖主 agent 任何模块，只有 botToken、chatId 两个构造参数。关键方法是 shouldAlert，实现指数退避：第一次失败 60 秒后告警，第二次 5 分钟后，第三次 15 分钟后，第四次 30 分钟后，之后每小时一次。时间档位写在常量数组 BACKOFF_MS 里：60_000、300_000、900_000、1_800_000、3_600_000，五档逐步拉开间隔。

【窦文涛】为什么需要退避？如果 OpenClaw 每隔 5 秒崩溃又重启（crash loop），没有退避的 Watchdog 会每 5 秒发一条告警。凌晨 3 点你手机被刷 720 条通知。指数退避把告警频率控制在合理范围：第一次故障立刻通知，连续故障逐渐降频。退避时间表是常量数组 BACKOFF_MS，用 Math.min(failureCount, array.length - 1) 作为索引，实现简单，逻辑清晰。

【窦文涛】一个值得单独记住的细节：AlertChannel 需要另一个 Telegram bot，@BotFather 创建一个 lena_watchdog_bot，token 和主 bot 完全独立。这多了一点运维复杂度，换来的是"主 agent 挂了你一定知道"这条确定性保证。在生产环境里，这个交换是值得的。

【窦文涛】刚才讲的 178 行是一个"刚好够用"的实现。如果你的 agent 规模增长——多个 channel、多个 agent、需要审计记录——178 行就不够了。这时候可以参考 OpenClaw 生产版，它把同样的问题拆成 4 个协作子模块：heartbeat-runner.ts 主控，外加 4 个职责各异的子模块。

【窦文涛】heartbeat-active-hours.ts 把时间精度从整数小时提升到精确分钟，支持 22:00-02:00 这种跨午夜配置，用 Intl.DateTimeFormat 换算。heartbeat-events-filter.ts 区分四种触发类型：interval（定时节拍）、exec-event（后台任务完成通知）、cron（计划任务触发）、wake（手动唤醒）。不同 reason 对应不同 prompt 模板，exec-event 会把任务执行结果注入 prompt，让 LLM 以汇报格式推送给用户。

【窦文涛】heartbeat-visibility.ts 处理用户可达性，三种模式：showAlerts 发真实内容，showOk 发 HEARTBEAT_OK 静默心跳包，useIndicator 发无声指示器。heartbeat-reason.ts 记录每条推送的触发 reason，方便 debug"为什么昨天 08:03 那条消息被发出"。

【窦文涛】OpenClaw 还有一个对教学有价值的细节：transcript prune。当 beat 结果是 HEARTBEAT_OK 时，代码会用 fs.truncate() 把这次 LLM 交互从会话历史里截断，缩回调用前的文件大小。原因是：每天 24 次 Heartbeat，一周后 context window 里有 168 条"没什么可说的"记录。Context 污染影响后续判断，context window 占满把有价值的历史推出窗口。截断是必须的，不是可选优化。

【窦文涛】还有 dedupe 机制：24 小时内不发重复内容。判断条件是三个 AND——normalized text 完全相同，且在 24 小时内，且没有附件。解决的问题是：如果每天早报都是"今天没什么特别的事"，没有 dedupe 时用户每小时收一条格式完全相同的消息。有了 dedupe 后，相同内容只发一次。

【窦文涛】选型建议记下来。nano-claw 178 行：个人项目、单 channel、单 agent。OpenClaw 4 子模块：多 agent、多 channel、需要 audit trail。不要"以防万用"地直接用 OpenClaw 版本——4 子模块的配置复杂度会让维护成本翻倍，而你可能根本用不到 visibility 和 reason 子模块。先用最简方案满足当前需求，需求增长到边界时再升级，这是通用工程原则。

【窦文涛】这个独立调度器模式不是本章首创的。Kubernetes 的 liveness probe 是同一个思路的生产级实例：kubelet 独立于 pod 内的业务进程，从外部周期性发 HTTP 请求探测存活，探测失败触发重启，整个路径不依赖 pod 内任何代码。macOS 的 launchd 和 Linux 的 systemd timer 也是这样——外部调度器负责周期性唤醒，agent 进程只负责执行。本章的 AlertChannel 是同一模式在个人 agent 层面的最小实现：一个类，一个独立 bot，一个 send() 方法。

【窦文涛】Ops 领域有个经典隐喻 Pets vs Cattle，微软工程师 Bill Baker 2012 年演讲里提出，后被 ops 社区广泛引用：宠物是有名字、照料的个体，死了不可替代；牛群是无状态、可替换的个体，挂了自动重生。没有 Heartbeat 的 Lena 是宠物——进程死了你才发现她不在跑。有了 Heartbeat 和独立告警通道，Lena 变成牛群——外部调度器保证她活着，告警通道保证你知道她死了。

【窦文涛】本章 Lena 的聪明度增量是第一次有了脉搏。v0.16 结束时她知道消息怎么路由，但她不知道时间。v0.17 结束时她知道现在是 08:00，知道这个时间对用户有价值，知道主动开口。这是"等人叫才开口的被动工具"和"主动感知时间的助理"之间的边界。178 行代码，改变的是 agent 的存在模式。

【窦文涛】读者的行动清单：先把 intervalMs 改成 10000 全天 active 跑通第一条 Telegram 消息；验证时区，在 isActiveHours 里 console.log 当前 hour 确认是用户时区不是服务器时区；第三步，给生成器加真实内容（接天气 API 或 HackerNews RSS）；第四步，创建独立 watchdog bot，加 AlertChannel 类。四步完成，你有了一个真正 Proactive 的 agent 骨架，下一章 Cron 会在这个骨架上加定时任务执行和汇报能力。
