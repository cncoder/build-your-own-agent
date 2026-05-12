【窦文涛】今天讲第二十二章。先说一个症状。你把 Lena 部署到服务器上，周五晚上下班。周一早上回来，打开账单——五百美元。你往日志里看，发现 Lena 周六凌晨陷入了一个死循环，同一个工具调用失败了一千两百次，她不停重试，每次都带着完整的上下文历史，每次都花钱。你什么都不知道。因为你没有可观测性，没有预算熔断，也没有进程守护——你关了终端，Lena 就活在一个黑盒子里。

【周迅】太真实了。

【窦文涛】这就是 v0.22 要解决的核心问题。本章从三个症状出发：第一，三天后你不知道发生了什么；第二，死循环把账单炸了你才知道；第三，你关了终端 Lena 就消失。对应三个答案：结构化日志加 OpenTelemetry、日预算四状态机、systemd 和 launchd 部署。Lena 从 v0.21 升到 v0.22，新增四个生产能力：每次 LLM 调用都有结构化日志和 OTel span 可回放；日预算四状态机自动限速；三份部署文件一条命令自动复活；两个 Hooks 示例把 lint 和通知接进自动化流程。

【窦文涛】先讲可观测性。传统后端服务的可观测性是为请求响应模型设计的：一次请求，一次响应，P99 延迟，错误率。Agent 完全不一样，有三个显著差异。先说第一个，长尾延迟。一次 agent 会话可能包含三次 LLM 调用加十二次工具调用，总耗时从两秒到二十分钟不等。传统 P99 指标对 agent 没有意义，你需要追踪的是每步的决策链——第几次 LLM 调用、用了什么工具、耗时多少、token 花了多少。

【窦文涛】长尾延迟之外是第二个差异，非确定性输出。同样的 system prompt 加 user input，因为模型随机性，Lena 今天选工具 A，明天选工具 B，后天两个都用。你无法用预期输出来判断正确性——你需要追踪的是意图与行为的一致性。第三个差异同样独特：成本是变量。一次 Web 请求的服务器成本是微秒级计算，可以忽略。但一次 agent 任务的 LLM 调用成本从 0.001 美元到 0.5 美元不等，取决于任务复杂度。这让成本监控成为 agent 可观测性的一等公民，而不是事后统计。

【窦文涛】这里有三个 Convention 要先定下来。Trace 等于一次完整的用户请求，有唯一的 trace_id；Span 等于一次具体操作，比如一次 LLM 调用，有开始和结束时间，有父子关系，挂在 Trace 下；Log 等于单个时间点的事件快照，通过 trace_id 和 span_id 关联到 Trace。三者不是可以二选一的替代关系。Log 告诉你发生了什么，Span 告诉你花了多长时间，Trace 告诉你整体调用链是什么样的。生产 agent 需要三者同时在场。

【窦文涛】具体实现。structlog 是 Python 生态里结构化日志的标准选择。调用 setup_logging 时传 json_output=True，每条日志就变成一个 JSON 对象，包含 event、model、input_tokens、level、timestamp 等固定字段。这样你就可以用 jq 查询：select(.event=="tool_fail" and .timestamp>"2026-05-09") 这一条命令，0.3 秒出结果。对比之前的 print 日志，后者需要肉眼读，十分钟也找不到。

【周迅】jq 这个工具真的很好用。

【窦文涛】对。然后是 OpenTelemetry，简称 OTel，CNCF 毕业项目，现在是云原生可观测性的行业标准。用 setup_tracing 初始化一个 TracerProvider，配置 OTLPSpanExporter 导出到 Jaeger。本地开发用 docker run -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one 五秒启动一个 Jaeger 实例。生产迁移只需要把 endpoint 改到 AWS X-Ray ADOT collector，业务代码一行不改。这就是 OTel 的核心价值：换后端只改配置，不改代码。

【窦文涛】OTel 社区在 2025 年发布了 GenAI 语义约定规范，统一了 LLM 调用的 span attribute 命名。字段包括 gen_ai.operation.name、gen_ai.provider.name、gen_ai.request.model、gen_ai.usage.input_tokens、gen_ai.usage.output_tokens，还有专门追踪 Prompt Cache 命中的 gen_ai.usage.cache_read.input_tokens。遵循这个约定，你的 agent 数据可以直接被 Grafana、Langfuse、Honeycomb 识别，不需要适配层。

【窦文涛】还有个 agent 专属字段。gen_ai.agent.name 等于 agent 名称，gen_ai.agent.id 等于 agent 唯一 ID，gen_ai.conversation.id 等于会话 ID。Span 命名规范：推理 span 叫 chat 加模型名，工具执行 span 叫 execute_tool 加工具名，调用 agent 的 span 叫 invoke_agent 加 agent 名。这些规范让 Langfuse 这类专门为 agent 设计的可观测性平台能直接解析你的数据，不需要写适配代码。

【窦文涛】有了 OTel 数据，还需要一个可视化后端。本地开发最快的选择是 Jaeger：docker run 一行命令，五秒启动，原生支持 OTLP，打开 localhost:16686 就能看到完整调用树，每次 LLM 调用下挂着若干工具 span，点开任意 span 可以看到 token 数、cost、耗时。

【窦文涛】如果需要把 trace 和 eval 联动，Langfuse 是更好的选择。它是开源的 agent 专属可观测性平台，可以自托管，把第二十一章的 eval pipeline 直接接进来，trace 里每个 span 旁边就能显示 judge 评分。如果不想改代码，Helicone 提供了零侵入方案：在 API base URL 前加一层代理，你的 OpenAI 或 Anthropic 调用自动被记录分析，适合快速原型验证。RAG agent 需要追踪 embedding 漂移和幻觉率时，可以看 Phoenix。

【窦文涛】现在讲 cost 熔断为什么必须前置。这是一个在传统 Web 服务里没有对应概念的设计模式。事后报警的逻辑是：花完钱，账单推送，收到告警，手动停止。这个链路有两个根本缺陷。第一是时间差：AWS Cost Explorer 的账单数据延迟通常是 8 到 24 小时，一个死循环 agent 在一小时内就能花掉 20 美元以上，等告警到的时候损失已经发生。第二是无法自愈：告警通知的是人，人需要时间响应，这和 agent 自主运行的设计目标根本矛盾。

【窦文涛】前置熔断的设计是：在每次调用 LLM 之前检查预算状态。如果已超过阈值，当场拒绝调用，agent 自动停止或限速。这是 agent 自治的一部分——它不仅需要知道能做什么，还需要知道现在能花多少。

【周迅】这个设计思路很清晰。

【窦文涛】Lena v0.22 的实现叫 BudgetController，用四状态机管理日预算。四个状态：NORMAL 是 0 到 80% 正常运行；WARNING 是 80 到 90% 记录告警日志但不减速；THROTTLE 是 90 到 100% 每次调用前 sleep 2 秒主动降速；STOPPED 是 100% 以上拒绝调用返回 False。配置项有四个：daily_usd 默认 5 美元，warn_pct 默认 0.80，throttle_pct 默认 0.90，throttle_delay_sec 默认 2.0 秒。

【窦文涛】为什么是四状态而不是二状态正常或停止？THROTTLE 状态给正在进行的长任务一个优雅降速窗口，而不是在任务进行到一半时突然切断。这是在成本控制和任务可用性之间的务实权衡。nanoClaw 的 budget.py 第 84 行的 check_iteration 方法采用的是静态阈值硬停，v0.22 的改进是引入 THROTTLE 状态，让 agent 在 90% 预算时先降速而不是直接停止。如果你的场景是纯实验性任务，可以把 throttle_pct 设等于 1.0，退化为二状态。

【窦文涛】BudgetController 有三个核心方法。check_and_wait 是 LLM 调用前的预算门控，返回 False 表示已到上限，THROTTLE 状态下会 sleep 后返回 True。record_cost 在每次 LLM 调用完成后记录实际费用，检查状态是否跃迁，有状态变化时触发 state_change 回调。on_state_change 注册跃迁回调，可以用来接 Telegram 告警。另外有一个 _reset_if_new_day 私有方法，每天午夜自动重置计数器——日预算是日历天，不是滚动窗口。

【窦文涛】在 AgentLoop 里接入是这样的：step 方法开头调用 await self.budget.check_and_wait()，返回 False 就直接 return None。LLM 调用用 with tracer.start_as_current_span 包裹，span 里记录 input_messages 数量，调用完设置 input_tokens 和 output_tokens 两个属性。

【窦文涛】调用完成后计算 cost_usd，Sonnet 4.6 的价格是输入 3 美元每百万 token，输出 15 美元每百万 token，然后调 self.budget.record_cost(cost_usd)。这样每一步都被预算门控和 OTel 双重包裹，cost 实时累计，span 实时导出。

【窦文涛】现在讲 Claude Code Hooks。Hook 机制在 14 个生命周期节点插入外部命令，机制是 child_process.spawn 启动命令，JSON 通过 stdin 传入，stdout 返回决策控制 agent 行为。14 种事件分为五类：工具生命周期有 PreToolUse、PostToolUse、PostToolUseFailure；会话生命周期有 SessionStart、Setup、Stop、StopFailure。

【窦文涛】子代理生命周期有 SubagentStart 和 SubagentStop；用户交互有 UserPromptSubmit 和 Notification；环境变化有 InstructionsLoaded、FileChanged、CwdChanged。这 14 个节点覆盖了 agent 完整生命周期，让你在任意时机插入自定义逻辑。

【窦文涛】三个 Convention。PreToolUse 等于工具执行前，可以返回 block 阻止执行；PostToolUse 等于工具执行成功后，可以触发副作用比如 lint 和埋点，但不能撤回执行；Stop 等于 agent loop 正常退出时，返回 blockingErrors 可以让 loop 继续而不退出。

【窦文涛】最实用的是 PostToolUse 配 ruff 自动 lint：在 .claude/settings.json 里配置 PostToolUse matcher 为 Write，命令指向 lint_on_write.py。这个脚本读 stdin 里的 file_path，如果是 .py 文件就跑 ruff check --fix，失败就返回 block 加错误原因，让 agent 修复后重试。

【窦文涛】第二个 Hook 是 Stop 发 Discord 通知。notify_stop.py 读 stdin 里的 session_id 和 stop_reason，发 Discord webhook，然后返回空对象允许正常退出。有一个局限性要注意：Stop hook 在 StopFailure 也就是异常停止时不触发，需要配合独立的 StopFailure hook 做异常告警。

【窦文涛】现在讲部署。Convention 定下来：launchd 等于 macOS 的原生进程管理器，以 plist XML 配置，随用户登录启动；systemd 等于 Linux 的标准进程管理器，以 .service INI 配置，随系统启动；Docker 等于容器运行时，用 Dockerfile 描述环境，用 docker-compose.yml 描述服务依赖关系。三者不是竞争关系，而是适用不同场景：Mac 个人开发机用 launchd，Linux 服务器用 systemd，多服务组合部署用 Docker Compose。

【窦文涛】三者有一个共同的陷阱叫重启风暴：如果进程启动即崩溃，守护程序会以极高频率反复重启，触发平台保护机制，导致进程被永久停止而没有任何告警。launchd 用 ThrottleInterval 控制，systemd 用 StartLimitBurst 控制，两者都需要显式配置。

【窦文涛】launchd 的配置文件放到 ~/Library/LaunchAgents/，关键字段：Label 是服务标识符，ProgramArguments 是启动命令，KeepAlive 设 true 进程退出后自动重启，WorkingDirectory 设工作目录，ThrottleInterval 设 30 也就是每次重启至少间隔 30 秒。

【窦文涛】不加 ThrottleInterval 的后果：崩溃后 launchd 立即重启，再次崩溃，60 秒内超 5 次触发保护，进程永久停止且没有任何告警。加载命令是 launchctl load，修改 plist 后必须 unload 再 load，因为 SIGUSR1 不会刷新环境变量。

【窦文涛】systemd 的配置放到 /etc/systemd/system/lena.service，关键字段：Unit 里 After 设 network-online.target，Service 里 Restart 设 on-failure，RestartSec 设 15s，StartLimitIntervalSec 设 300，StartLimitBurst 设 5，意思是 300 秒内最多重启 5 次超过就停止。

【窦文涛】触发 start-limit-hit 之后手动恢复：systemctl reset-failed lena 再 systemctl start lena。安全加固字段：NoNewPrivileges yes，PrivateTmp yes，ProtectSystem strict，ReadWritePaths 只开放 /opt/lena/data 和 /var/log/lena。

【窦文涛】Docker Compose 的配置里 lena 服务设 restart: unless-stopped，依赖 jaeger 服务 service_started。jaeger 用 jaegertracing/all-in-one 镜像，暴露 16686 端口是 Jaeger UI，4317 端口是 OTLP gRPC 接收端。注意 OTEL_EXPORTER_OTLP_ENDPOINT 在 Docker 网络内要设成 http://jaeger:4317，用的是 Docker Compose 内网服务名，不是 localhost:4317，这是一个常见的配置错误。

【窦文涛】讲几个排查场景。launchd 停止了进程，launchctl list 显示非零退出码，通常是 ThrottleInterval 触发，说明进程短时间内多次崩溃。先 launchctl unload 摘掉 KeepAlive，手动 python3 src/main.py 看实际报错，修复后再 load。

【窦文涛】systemd 显示 start-limit-hit，运行 systemctl reset-failed lena 重置计数器再 systemctl start lena，检查 journalctl -u lena -n 50 找崩溃原因。Jaeger UI 看不到 trace，确认 jaeger 容器 running，检查 OTEL_EXPORTER_OTLP_ENDPOINT 是否用了 Docker 网络服务名而不是 localhost。

【窦文涛】budget_state_change 日志没出现，检查 record_cost 的 usd 值是否正确。如果用的是 Haiku 而不是 Sonnet，价格参数需要调整：Haiku 是输入 0.25 美元每百万 token，输出 1.25 美元每百万 token，比 Sonnet 便宜十倍以上。价格传错了，状态机永远不会跃迁。

【窦文涛】设计反思：为什么不用事后告警。最直接的方案是接云账单 API，超阈值发 Slack，然后人工处理。三个缺陷。第一，时间窗口：AWS Cost Explorer 延迟 8 到 24 小时，Google Cloud Billing 延迟 1 到 6 小时，死循环 agent 一小时就能花 30 美元以上，等告警到时损失已发生。

【窦文涛】第二，依赖人工响应：凌晨三点的告警，八点你才醒，五小时损失没人负责，这和 agent 自主运行的目标根本矛盾。第三，无法渐进降速：硬停止在长任务中间会导致数据不一致。THROTTLE 状态给了任务一个优雅降速窗口，在成本可控范围内尽量完成当前任务。

【窦文涛】Anthropic 官方的 Building Effective Agents 强调 Transparency 原则：agent 的每步行为应可审计。本章的结构化日志加 OTel span 正是这个原则的落地——每次 LLM 调用被赋予可追溯的 trace_id，任何历史决策都能回放。

【窦文涛】当前方案有一个局限性：BudgetController 只能控制 LLM 调用频率，无法控制第三方工具的副作用，比如发 email 或数据库写入。需要对所有工具调用限速，应该在 PreToolUse hook 层面加独立 rate limiter。这是尚无通行标准的开放问题。

【窦文涛】v0.22 章末总结。三个症状对三个答案：三天后不知道发生了什么，用结构化日志加 jq 解决；死循环炸账单，用 BudgetController 四状态机前置熔断解决；关了终端 Lena 消失，用 launchd 或 systemd 进程守护解决。

【窦文涛】四个新能力：每次 LLM 调用有结构化 JSON 日志和 OTel span 可回放；日预算四状态 NORMAL-WARNING-THROTTLE-STOPPED 自动限速；三份部署文件一条命令自动复活；两个 Hooks 把 ruff lint 和 Stop 通知接进自动化流程。下一章把通用 runtime 到专用 agent 的通路打通。
