【窦文涛】第 27 章，托管这件事——Amazon Bedrock AgentCore 把什么收进云里。Lena 从 v2.6 演进到 v2.7，不是新写一行代码，而是理解一件事：你手写过的那六大支柱，在托管平台里是怎么被服务化的，以及什么时候该用、什么时候反而不该用。

【窦文涛】先说这一章存在的理由。上一章你用 Strands 框架重写了 Lena，感受到"框架把实现细节收起来"是什么意思——以前 200 行的 ReAct 循环，现在 20 行搞定。那往上还有一层吗？有，叫托管服务。框架解决"怎么写代码"，但解决不了"代码跑在哪、谁来保证它 24 小时不宕机、100 个用户同时请求时 session 怎么隔离"。这些是运维问题。

【窦文涛】Amazon Bedrock AgentCore 是 AWS 在 2025 年发布的 agent 托管平台，官方定义是"无需基础设施管理，即可构建、部署和大规模运行 AI agent 的全托管平台，支持任意框架和模型"。重点在"任意框架"——它不绑定 Strands，LangGraph、CrewAI、LlamaIndex、甚至 OpenAI Agents SDK 都可以跑在它上面。

【窦文涛】AgentCore 有五个核心服务：Runtime、Memory、Gateway、Identity、Observability。这五件套和你手写的东西是有精确对应关系的。第 3 章的 while 循环和 session 管理，对应 Runtime；第 8、9 章的记忆系统和向量检索，对应 Memory；第 6、19 章的工具注册和 MCP 协议，对应 Gateway；第 13、14 章的安全沙箱和最小权限，对应 Identity 加 Runtime 的隔离层；第 22 章的可观测性，对应 Observability。

【窦文涛】这张映射是本章的核心框架。我们逐件讲。先说 Runtime。Runtime 是 agent 代码的运行容器——每个用户 session 独享一个 microVM，有独立的 CPU、内存和文件系统，与其他 session 完全物理隔离。session 结束后，整个 microVM 销毁并清零内存。AWS 官方文档把这叫做"在非确定性 AI 过程中实现确定性安全"。

【窦文涛】几个关键参数：最长执行 8 小时，空闲超时 15 分钟，单个 payload 上限 100 MB，计算架构是 ARM64（AWS Graviton）。8 小时这个上限很重要——第 18 章讲 Cron 和长任务时你感受过"跨天执行不能因进程重启就从头来"这个痛点，Runtime 原生支持这个场景，session 在整个 8 小时窗口里保持上下文。

【窦文涛】再说 Memory。第 8 章你手写了情景记忆、语义记忆、程序记忆的三层分法。AgentCore Memory 把这个抽象落地成两层：短期记忆覆盖单 session 内的对话 turns，长期记忆覆盖跨 session 的知识提取。官方文档对 Memory 的定位很直白："AgentCore Memory 解决了 agent AI 的一个根本挑战——无状态性。没有记忆能力，AI agent 把每次交互都当作一个全新的实例，对之前的对话一无所知。"

【窦文涛】长期记忆有两种提取策略。SEMANTIC 策略从对话里提取事实性信息，以向量形式存储，后续用语义搜索检索；SUMMARIZATION 策略把对话摘要化，适合"上次聊什么"这类场景。选哪种策略取决于场景：SEMANTIC 适合"这个用户偏好什么、用过哪些工具"这类结构化事实检索；SUMMARIZATION 适合"上次我们聊到哪里了"这类叙事性回顾。

【窦文涛】Gateway 的作用是把工具注册这件事服务化。第 6 章你手写了 ToolRegistry 和每个工具的 JSON Schema，第 19 章你实现了 MCP 客户端接入外部工具服务器。Gateway 把这两件事合并成一个托管端点：你提供 OpenAPI spec 或 Lambda 函数，Gateway 转成统一的 MCP 工具端点，agent 通过单一接口访问所有工具。

【窦文涛】Gateway 还内置了语义工具发现——agent 不需要知道工具的确切名字，只需描述要做什么，Gateway 用 embedding 加向量搜索找到最匹配的工具。官方文档说 Gateway "消除了数周的自定义代码开发、基础设施搭建和安全实现"。你在第 6、13、19 章加起来花的篇幅，就是这句话在说的那些工作。这正是第 6 章"任何能力 = 工具；加工具不改核心"这个原则在托管层的体现。

【窦文涛】Identity 解决 agent 自己的身份问题。第 13、14 章的安全是"agent 代码层面的安全"——不信任外部输入、沙箱化执行。但还有一个维度没有手写：当 Lena 需要访问 GitHub API，它用谁的身份？用个人 token？还是 service account？AgentCore Identity 给 agent 提供独立的工作负载身份，区别于人类用户身份。

【窦文涛】Identity 支持两种出站模式：用户委托（agent 代表用户，用用户授权的 token），以及自主访问（agent 用预授权的服务凭据，适合定时任务这类没有用户在线的场景）。入站认证支持 AWS IAM（SigV4）和 OAuth 2.0。

【窦文涛】最后是 Observability。第 22 章你用 OpenTelemetry 手动给 Lena 加了 trace 和 metric，还要维护 collector 基础设施。AgentCore Observability 把这个流水线托管了：agent 运行时自动产生 OTEL 格式的 trace、metric 和 log，直接写入 CloudWatch，无需自建 collector。内置指标包括 session 数量、每次调用延迟、总执行时长、token 用量、错误率；Trace 数据记录了每步 agent 决策路径和工具调用中间输出。

【窦文涛】五件套讲完，来看一个假设性的架构场景演示。如果用 AgentCore 搭一个 AWS 基础设施安全审计 agent，工具集可以覆盖 CloudTrail 审计日志、Config 合规性检查、GuardDuty 威胁情报——agent 自主决定调用哪些工具，按严重度分类后生成修复建议。代码层面，用 Strands 的 @tool 装饰器定义工具，Agent 接受工具列表和 system prompt。这部分代码结构不变；变化的是部署方式。

【窦文涛】部署流程：先 npm install -g @aws/agentcore 装 CLI，然后 agentcore create 选好框架和 Memory 策略，agentcore dev 本地调试带 trace 可视化，agentcore deploy 用 CDK 自动创建 IAM role、ECR 镜像仓库和 Runtime endpoint。部署后得到一个 Runtime ARN，之后通过 boto3 的 invoke_agent_runtime 方法调用，传入 agentRuntimeArn、runtimeSessionId 和 payload。

【窦文涛】这个部署路径里有一个重要细节：agentcore deploy 生成的 CDK 脚手架会自动处理容器镜像的构建和推送。但你需要注意架构限制——Runtime 目前只支持 ARM64（AWS Graviton），x86 镜像不能用。如果你的 agent 依赖 x86-only 的二进制库，这个限制会是一个实际摩擦来源。

【窦文涛】现在把这五件套映射回六大支柱，做一个整体对比。Tool universality 支柱：Gateway 新增了手写做不到的能力——语义工具发现，让模型不需要预知工具名也能调到正确工具。Planning 支柱：Policy（Cedar 规则，Preview 阶段）是手写方案里完全没有的一层——它在工具调用前实时拦截，把安全策略从 agent 代码里解耦成独立的声明式规则文件。

【窦文涛】这个映射最重要的含义是：托管服务不只是"把你手写的东西搬上云"，它在某些支柱上提供了手写很难达到的能力。比如 Safety 支柱——你手写的 sandbox 是代码层的，Runtime microVM 是基础设施层的物理隔离，这两层防御的强度是完全不同的。但有一点是托管服务改变不了的：你的 system prompt、工具逻辑、安全策略仍然是你的代码，业务逻辑没有被托管。

【窦文涛】接下来说边界和取舍。什么时候该考虑托管服务？三个场景最清晰。第一，合规要求明确——如果 agent 处理 HIPAA 医疗数据或 SOC 2 金融数据，每个 session 的物理隔离不是"最好有"而是"必须有"，自己实现 microVM 隔离的成本和专业度要求极高，这是托管服务价值最清晰的场景。第二，团队规模小、运维成本敏感——3 到 5 人团队没有专职 DevOps，基础设施维护会占据大量精力。第三，多租户隔离——多个客户的 session 必须完全隔离时，Runtime 的 microVM 把隔离做在基础设施层，而不是靠应用代码里的 if-else。

【窦文涛】什么时候不值得用托管服务？同样三个场景。第一，高度定制化的执行环境——ARM64 架构限制加上目前主部署区域集中在 us-west-2，如果你的数据主权要求决定了不能离开特定区域，托管服务的限制会成为摩擦来源。第二，极致延迟要求——量化交易等需要亚 50ms 响应的场景，托管服务的调用链比 in-process 执行多几跳，延迟是否可接受需要先评估。第三，团队已有成熟 Kubernetes 运维能力——如果在 EKS 上已经运维过生产级服务，把 agent 跑在 Kubernetes 上的成本不会比 AgentCore 高多少，同时控制权更完整。

【窦文涛】定价有一个对 agent 场景特别友好的特性：AgentCore 采用消费计费模式，按实际 CPU 和内存使用量收费。agent 执行时间里相当大比例是在等 LLM 返回，这段时间 CPU 空闲不做事，AgentCore 不收这段时间的钱。官方文档里把这称为"按实际主动处理时段计费"。这和普通 Lambda 按总请求时长计费是不同的逻辑——对 agent 这种 I/O 密集型工作负载，实际费用通常低于按总时长估算的数字。

【窦文涛】但要把所有组件的成本加起来算全。Runtime 按实际 CPU 和内存用量计，Memory 按写入事件和检索次数计，Gateway 按 API 调用次数计，Observability 按 CloudWatch 摄取量计。小流量场景整体便宜，高流量需要做明确的成本测算，不要只看 Runtime 一项。

【窦文涛】最后说 Vendor lock-in，这个问题必须正视。agentcore deploy 命令生成的 CDK 脚手架、arn:aws:bedrock-agentcore 格式的 ARN、boto3 的 invoke_agent_runtime 调用——这些都是 AWS 专有接口。把 agent 迁移到其他云需要重写运维层。这不是 AWS 独有的问题，任何托管服务都有这个特性，但决策时需要明确接受这个约束，而不是假装它不存在。

【窦文涛】一个容易忽略的选型时机问题：很多团队在"Lena 跑通了但还没上生产"时就开始纠结要不要托管服务，其实这时候太早了。托管服务的价值在多用户并发和合规压力出现时才真正显现——单机单用户阶段，自建反而更灵活，迭代更快。正确的判断时机是：当你开始思考"如何让五个同事同时用 Lena，且各自的对话互不干扰"时，这才是评估 Runtime microVM 隔离是否值得引入的合适时间点。

【窦文涛】这一章做了一件事：把你手写过的六大支柱，和 AgentCore 的五件套做了精确映射，并诚实地列出了托管服务在哪些场景下是正确选择、哪些场景下反而是绑缚。这张清单对 AgentCore 成立，对其他任何 agent 托管平台同样适用。下一章 Lena 面对的是更大的挑战：当 agent 需要跨组织调用时，身份和信任模型是怎么演进的。
