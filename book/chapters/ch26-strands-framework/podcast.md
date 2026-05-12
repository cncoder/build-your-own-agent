【窦文涛】第 26 章讲框架——用 Strands 重写 Lena v0.3，同样的最小 ReAct 循环，手写版约 80 行，Strands 版含注释约 60 行、去掉注释和空行约 35 行纯逻辑，少了大约 44%。

【窦文涛】少掉的那 44% 收进了框架核心：循环的进入条件（约 8 行）、消息历史的追加逻辑（约 10 行）、stop_reason 的分支判断（约 6 行）、工具 schema 的手写声明（约 20 行），框架把这些统一到 Agent 实例里——你只需声明 @tool 装饰的函数，创建 Agent 实例，然后调用。

【窦文涛】框架管理的不止这些——OTEL trace_attributes 参数开箱即用，每次 LLM 调用和工具调用自动生成 span；callback_handler 支持 token 粒度流式响应；GraphBuilder（有向依赖图）和 Swarm（并发子任务汇总）等多 agent 拓扑内置。这套架构叫"model-driven"——模型决定何时调用哪个工具，不需要开发者写硬编码路由。

【窦文涛】对话历史默认由 SlidingWindowConversationManager 管理——窗口大小 window_size=40，保留最近 40 条消息，超出时滑动截断旧消息，工具调用对不会被拆分；window_size=0 是特殊值，含义是"清空所有历史"，与 TypeScript SDK 行为一致。

【窦文涛】SummarizingConversationManager 是可选替换方案，触发时机有两种：context window 使用超过 70% 时自动触发（ContextWindowOverflowException），或主动探测开启时到达阈值；默认 summary_ratio=0.3（压缩最旧的 30% 消息），preserve_recent_messages=10（最近 10 条永不压缩），压缩而不是截断。

【窦文涛】@tool 装饰器内部调用 Pydantic 的 create_model() 动态生成 JSON Schema——通过 inspect.signature() 读取参数名和默认值，通过 get_type_hints() 读取类型注解，支持 str、int、float、bool、Optional[T]、嵌套 BaseModel 以及 Annotated[T, "纯字符串描述"] 共 7 种类型；name 来自函数名，description 来自 docstring，required 来自无默认值的参数。

【窦文涛】注意 Annotated[T, pydantic.Field(...)] 不被支持，会抛出 NotImplementedError，必须用纯字符串代替。手写版你手动声明 schema 字典，每次加参数要同时改两处；@tool 装饰器让函数签名成为唯一事实源，加一个带类型注解的参数，schema 自动更新。

【窦文涛】callback_handler 是普通 Python 函数，接受 **kwargs，在 data（流式 token 到达）、current_tool_use（工具调用开始）、force_stop（循环被强制终止）等细粒度事件发生时被调用，适合实时处理流式输出。

【窦文涛】HookProvider 是协议类，在调用级别触发，通过实现 register_hooks 注册 8 种生命周期节点的回调：BeforeInvocationEvent、AfterInvocationEvent、BeforeToolCallEvent、AfterToolCallEvent、BeforeModelCallEvent、AfterModelCallEvent、MessageAddedEvent、AgentInitializedEvent。

【窦文涛】BeforeToolCallEvent 在工具调用前触发，适合硬边界检查——"单笔下单不超过账户余额的 2%"这条规则必须进代码，写进 system prompt 是概率性保证。AfterToolCallEvent 在工具调用后触发，适合把结果送审计系统。

【窦文涛】HookProvider 让你在调用级别注入逻辑，但有一个更底层的约束它管不到——进程生命周期。单机 Strands agent 的上下文绑定在进程里，进程崩溃 context 直接丢失，长期任务要从头重跑。Amazon Bedrock AgentCore 是 Strands 的托管运行时（2025 年 7 月公开预览），支持最长 8 小时连续执行，把这个约束从进程生命周期延伸到小时级别。

【周迅】工具调用之间没有依赖关系，框架是并发还是串行执行？

【窦文涛】Strands 的默认工具执行器是 ConcurrentToolExecutor——当模型在一次响应里请求多个工具调用时，它们会被并发执行，而不是串行等待。对多工具组合查询场景（比如同时查天气 + 查日历 + 查联系人）响应延迟有显著影响。

【窦文涛】并发执行带来的一个自然问题是：怎么知道哪个工具调用慢了、出了什么问题？这就是 OTEL span 的用途——每个 LLM 调用的 span 包含：model_id、prompt tokens、completion tokens、time-to-first-byte 和总完成时间；每个工具调用的 span 包含：工具名、输入参数（JSON 序列化）、返回值、执行时间。多个 span 按调用顺序串成一条 trace。

【窦文涛】trace_attributes 字典支持自定义标签：加 user_id、session_id 后，在后端观测系统里能过滤出特定用户的所有 agent 调用。exporter 支持 AWS X-Ray（跨 Lambda/ECS/EKS 全链路）和 Amazon CloudWatch（已有告警面板直接看 trace），切换只需改配置文件，不改 agent 代码。

【周迅】OTEL span 覆盖 LLM 调用和工具调用——循环的停止条件能从 span 里看到吗？

【窦文涛】Strands 的 StopReason 枚举比手写版的 end_turn/tool_use 要丰富得多：还有 cancelled（外部取消）、stop_sequence（遇到预设停止序列）、interrupt（循环被中断）、guardrail_intervened（Bedrock Guardrails 安全拦截）。guardrail_intervened 意味着 Bedrock 的内容安全规则在 agent 层级生效，不需要在工具代码里手动实现。这些设计——可观测性、停止原因、hook 拦截——都预设了 Strands 在多 agent 场景里运行。

【窦文涛】多 agent 方面，Strands 支持 Supervisor 模式：子 agent 在 orchestrator 看来就是一个工具，orchestrator 的 Agent 循环自动决定何时委派、委派给谁，不需要开发者写显式路由规则。

【窦文涛】Strands 是 AWS 内部孵化出来的，在 Kiro（AI coding IDE）、Amazon Q、AWS Glue 和 VPC Reachability Analyzer 里有实际运行记录——Kiro 处理高工具数量的代码审查场景，Glue 处理自然语言到 ETL 的长执行时间场景，VPC Reachability Analyzer 处理依赖外部 AWS API 的网络诊断场景。

【窦文涛】框架引入了两层透明度损失。第一层：调试路径变了——不再是"去循环里加 print"，而是"去 trace 里找哪个 span 出了问题"，这要求提前配好 OTEL exporter。第二层：节点间消息格式被封装，只能通过 AfterToolCallEvent 的 hook 或 OTEL span 的输出参数字段间接验证，比手写版多了一步。

【窦文涛】上手时有一个不明显的卡点：Strands 默认 model 是 BedrockModel，默认 region 是 us-west-2。在 us-east-1 已有 Claude 访问权限，但没有在 us-west-2 单独开通，就会报 ResourceNotFoundException——错误信息不会告诉你是 region 问题，需要对照文档排查。

【窦文涛】修复有两种方式：在 Agent 初始化时传 model=BedrockModel(region_name="us-east-1") 显式指定 region，或者设 AWS_DEFAULT_REGION 环境变量。Strands 也支持 OpenAI 兼容接口、Anthropic 直连和 LiteLLM，换模型只需换 model 参数，agent 代码不变。

【窦文涛】选框架之前，还有一个对立面值得理解——LangGraph。LangGraph 要求你把整个 workflow 显式画成有向图——节点是步骤，边是跳转条件。模型只在单个节点内推理，不决定跳哪条边；控制流在代码里，不在模型里。

【窦文涛】典型场景是确定性流水线：内容审核的 OCR → 违规检测 → 人工复核 → 归档，每步规则固定，状态机能精确建模。这里 Strands 的 model-driven loop 没有优势——你已经知道下一步是什么，不需要模型来"决定"；LangGraph 的有向图能精确捕捉这个确定性结构。

【周迅】如果团队有明确角色分工——编辑、审核、发布——有更贴近业务描述的框架吗？

【窦文涛】那就考虑 CrewAI，它的核心抽象是"角色"——你定义一个 Editor agent、一个 Reviewer agent，每个 agent 有目标和背景描述，框架按预设依赖顺序把任务从一个角色传到下一个；产品经理看角色定义能看懂流程，不需要读调度逻辑。

【窦文涛】smolagents 选择了另一种极端：agent 不调用工具，它直接生成 Python 代码并执行。好处是表达力极强，模型能用任意 Python 逻辑组合操作；坏处是安全边界很难划——生成的代码没有系统级隔离时，能读文件、打网络、改环境变量，从架构设计第一天就要想清楚。

【窦文涛】除了本地工具，Strands 还支持通过 MCP（Model Context Protocol）接入外部服务——MCP 标准化的是"工具层"，第三方服务按 MCP 标准格式发布工具后，Strands 直接接入，模型不区分本地函数还是远程 MCP 服务。

【窦文涛】A2A（Agent-to-Agent）协议标准化的是"agent 层"——一个 Strands agent 如何把任务委派给另一个框架（比如 LangGraph）的 agent，而不需要两边都改代码接入对方的 SDK。MCP 解决工具接入，A2A 解决跨框架 agent 调用，两者解决不同层级的集成问题。

【窦文涛】"agent as tool"是 Strands 多 agent 的最轻量接入方式：用 @tool 装饰一个函数，函数内部实例化另一个 Agent 并调用它，orchestrator 完全不知道工具后面是 agent 还是数据库查询；orchestrator 的 system prompt 和专家 agent 的 system prompt 完全解耦，可以单独迭代专家 agent 的行为。

【窦文涛】常见的多 agent graph 挂起有一套确定性诊断路径：第一步，给每个 Agent 设置 max_parallel_instances 上限，防止无限 spawn 把资源耗尽；第二步，开 OTEL trace，在 CloudWatch 里找哪个 span 的开始时间有记录但没有结束时间——这个 span 对应的节点就是卡死节点；第三步，隔离该节点单独测试。

【窦文涛】model-driven 还有一个失控点：工具调用序列的不确定性。同一个 system prompt + 同一个用户输入，模型在两次执行里可能选不同的工具顺序。如果你需要精确复现执行路径——比如监管审计要求记录决策链——model-driven 是错误选择，应该用 LangGraph 的有向图把路径写死。

【窦文涛】实践上可以混用：Strands agent 通过 @tool 调用一个 LangGraph 流程，Strands 处理开放式对话层（用户意图不可枚举），LangGraph 在工具内部执行固定流程（比如合规审查的 OCR → 检测 → 审核）——两者通过普通函数调用边界隔离，Strands 不需要知道工具内部用了哪个框架。

【窦文涛】最后一个细节：Strands 的 @tool 函数是普通 Python 函数，框架把返回值序列化成字符串再送给模型，工具测试因此完全独立——你可以 `assert my_tool("input") == expected_output` 直接验证，不需要启动 agent，不需要 mock 整个 while 循环，测试隔离性比手写版架构好很多。
