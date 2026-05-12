【窦文涛】第 23 章，Specialization Pattern——一个 Runtime 派生 N 个 Agent。Lena 从 v0.22 演进到 v0.23 的核心跨越：让同一套通用运行时长出量化交易、播客生产、DevOps 运维三个完全不同的专用 agent，而不是把整套系统重写三遍。这一章就讲怎么做到这件事。

【窦文涛】先说动机。把 Lena 部署到线上一周后，你会收到三类请求。第一类：我想要一个只做量化交易的 agent，只看价格和指标。第二类：帮我做一个播客生产 agent，每天自动采集、去重、写脚本、合成音频。第三类：做一个 DevOps agent，专门盯 AWS 告警，自动执行处置流程。

【窦文涛】最直觉的做法是给每类需求重新写一个 agent。算一下代价——重写 ReAct 循环 3 到 4 天，重写工具注册 2 天，重写内存系统 2 天，重写安全护栏 3 天，重写 channel 接入 2 天，重写部署配置 1 天。一个专用 agent 就要 13 到 15 天，三个就是 40 天以上。而且三个月后你改了一个底层工具调用约定，得在三处同步修改。

【窦文涛】更好的类比是操作系统与进程的关系。OS 是不变的内核，每个进程是运行在内核上的专用程序，共享内存管理、系统调用、安全模型。你不会为每个进程重新写一个 OS。Specialization Pattern 就是这个思路：通用 Lena runtime 是内核，专用 agent 是运行在这个内核上的进程。内核只写一次；进程只配置不重写。

【周迅】等等，一份代码升级，三个 agent 全更新了？

【窦文涛】对，升级一次，所有派生 agent 同步受益。这个思路在业界有个标准定义：runtime 是 agent 的不变内核，包含 LLM 调用、工具执行框架、内存管理、安全护栏和 AgentLoop；配置层是可替换的角色定义，包含 system prompt、工具集和 skills。派生就是保持 runtime 不变，只替换配置层——这正是 Anthropic《Building Effective Agents》里描述的 orchestrator-worker 分层的代码层实现。

【窦文涛】想清楚这个分层之后，下一步自然是：能不能把配置层的创建标准化？Lena-SpecKit 就是干这件事的：给出 agent 名称和角色描述，填上工具列表和 skills 列表，一行命令输出完整专用 agent 目录，把派生变成 15 分钟的事。具体有三种派生姿势。

【窦文涛】姿势一是 System Prompt 替换，只换角色定义，不动任何代码，30 分钟就能完成。姿势二是 Tool Profile，替换允许的工具子集，量化 agent 只需要 price_feed 和 orderbook，不需要 news_search 和 file_write。姿势三是 Skills 注入，注入领域 SOP 文档，告诉 agent 风控规则怎么算、仓位怎么管理。三种姿势不是互斥的，生产级专用 agent 通常三者叠加。其中 Skills 注入最有工程深度，原因有两个。

【窦文涛】第一个原因是工程可扩展性，第二个是模型效果。工程侧：理想情况是 skills 来自 Git 管理的 markdown 目录，三个 agent 共用同一目录，改一处拉取即同步——当前 SpecKit 的已知局限是 skills 模板仍然硬编码，没有通过 git pull 更新策略从文件目录动态加载的能力，这是下一步要补的。第二个原因是效果：注入角色身份文档，模型推理质量会真的变吗？这个问题有实验数据——Kong et al.（2023）验证：明确角色身份能让专业推理准确率提升 9 到 12%，不需要改权重。

【窦文涛】现在来看代码实现。Lena-SpecKit 的骨架核心数据结构是 AgentSpec，一个 dataclass，包含五个字段：name、role、tools、skills、output_dir（默认是 agents）。create_agent 函数接受一个 AgentSpec，创建三个文件：system_prompt.md、tool_profile.json 和 config.json。整个骨架只有 30 行代码，目录结构已经确定。

【窦文涛】骨架确定了，开始往里填内容。Skills 注入的实现方式是：在代码里维护一个 SKILL_TEMPLATES 字典，键是 skill 名称，值是 skill 文档内容——这就是"注入"的本体。risk_checker skill 定义了风控清单：单笔风险敞口不超过总资金 2%，今日累计亏损不超过总资金 5%，连续亏损次数小于 3。position_sizer skill 定义了仓位计算公式：仓位大小等于总资金乘以风险比例除以止损距离。

【窦文涛】运行 create_agent(AgentSpec(name="trader", role="crypto analyst", tools=["get_price"], skills=["risk_checker"])) 之后，agents/trader 目录里有四个文件：system_prompt.md、tool_profile.json、config.json，以及 skills 子目录下的 risk_checker.md。这是中间验证的关键步骤——每加一层能力，先验证目录结构是否正确。

【窦文涛】第二步加 CLI 入口。lena_speckit/__main__.py 用 argparse 包装 create_agent，暴露 create 子命令，参数含 name、role、tools、skills、output-dir。一行命令创建专用 agent：python -m lena_speckit create trader --role "crypto market analyst" --tools "price_feed,orderbook,news_search" --skills "risk_checker,position_sizer"。

【窦文涛】第三步是 SupervisorAgent。有了多个专用 agent，需要一个智能路由入口。Convention：SupervisorAgent 等于以其他 agent 为工具的 meta-agent，负责意图理解和任务委托；leaf agent 等于被包装成工具的专用 agent，只执行不路由。Agent Squad（2FastLabs/agent-squad，8k stars）就是用这个解法的，OpenAI 叫 Handoffs，Anthropic 叫 orchestrator，核心都是"上层意图路由、下层专用执行"。

【窦文涛】SupervisorAgent 的实现核心在 _build_tools 方法：遍历 agents 目录，为每个专用 agent 生成 tool schema，工具名是 delegate_to_{agent_name}，描述取自 system_prompt.md 第一行。handle 方法是主入口：LLM 选工具，调用 leaf agent，返回结果。trader 和 devops 都是 leaf agent——只执行不路由。LLM 路由比关键字规则鲁棒——"BTC 现在怎么样"里没有"交易"二字，但 LLM 能正确路由给 trader。

【窦文涛】路由靠 LLM 能 work，但这个认识有个副作用：很容易让人觉得"LLM 既然能判断路由，也能执行风控规则"——把"单笔风险敞口不超过 2%"写进 system prompt。测试边界输入：下单，symbol 等于空字符串，数量 10000。LLM 可能直接回复"好的，已下单"——它忽略了规则。这是 LLM 处理边界输入时的结构性局限，不是 prompt 写得不好。

【窦文涛】正确做法是把风控写进代码。place_order 函数在执行前先检查 symbol 是否为空，再检查仓位是否超过 total_capital 乘以 0.02，任何一条不满足就抛 ValueError。代码层的检查是确定性的，不可绕过；prompt 层的指令是概率性的，LLM 在特定输入下可能忽略。原则是：性格和风格写 prompt，安全和护栏写代码。

【周迅】那 system prompt 里写的规则岂不是摆设？

【窦文涛】准确地说，prompt 可以写"性格、风格、领域偏好"，但不能写"必须执行的业务规则"。这个区分是整个 agent 安全架构的基础——知道哪些逻辑该进代码、哪些可以留在 prompt，才能设计出不会被边界输入击穿的系统。

【窦文涛】明确了这条原则，再来看整个流程：pip install anthropic，创建 trader 和 devops agent，运行 supervisor_demo.py 测试路由——发送"BTC 最近的 RSI 趋势如何"，supervisor 应该把任务委托给 trader 而不是 devops。常见失败：ModuleNotFoundError 没装依赖；agents 目录为空没先 create；路由总是同一个说明两个 agent 的 system_prompt 第一行描述差异不够大。

【窦文涛】代码跑通了，SpecKit 可以用了——但这里有个经验：越是便利的工具，越容易被过度使用。三个月后你会发现自己维护着 20 个配置文件，每个都有细微差异，改任何公共逻辑都要翻 20 遍。所以在工具可用的这一刻，就要想清楚：什么时候该派生，什么时候不该？

【窦文涛】替代方案是通用 agent 加临时角色注入——直接在消息里说"接下来你扮演量化分析师"。这种做法零维护成本，但有三个代价：上下文污染（角色渗透后续对话）、工具集无法按角色隔离、无法稳定注入领域 SOP。

【窦文涛】判据：需要持久运行时选派生——比如 7×24 小时监控 AWS 告警的 DevOps agent，或者每天定时运行的播客采集 agent，这类持续任务用临时角色注入根本撑不住；需要工具集隔离（安全需要）时选派生；需要稳定的领域 SOP 时选派生。反过来，一次性任务用完即弃，不派生；快速原型还不确定角色定义，先跑通确认后再固化。

【窦文涛】知道了何时派生，三个专用 agent 就运行起来了——接下来的问题是它们之间怎么协作。CrewAI 把多 agent 协作分成两种根本不同的哲学——Crew 是一次性任务的角色协作，定义好 agent 和 task 让框架根据依赖编排，适合项目制任务；Flow 是事件驱动状态机，每个 agent 的输出触发下一个，适合持续运行的流水线。

【窦文涛】第二个进阶视角是动态 Agent 生成。Anthropic《Building Effective AI Agents》定义：agents created at runtime by assembling components from libraries of prompts, tools, and configurations, then dissolved after task completion。关键区别是生命周期——静态派生的专用 agent 持久存在，动态生成的 agent 任务来了才组装，完成即销毁，一次性任务更经济。

【窦文涛】静态派生还是动态生成，这两种选择在真实业务里是怎么演进出来的？Anthropic 白皮书用电商客服展示了五阶段路径：Phase 1 单 agent 验证可行性；Phase 2 加 Routing 分流；Phase 3 每类路由连接专用 agent；Phase 4 Multi-agent 编排协调库存、支付、物流；Phase 5 加入 Evaluator agents 持续质量改进形成闭环。

【窦文涛】每一步都在前一步验证有效之后才推进。没有 Phase 1 的单 agent 证明价值，就不会有 Phase 2 的路由；没有 Phase 2 的准确率数据，就不知道哪些类别值得建 Phase 3 的专用 agent。这就是白皮书的核心原则：start simple, measure everything, add complexity only when it delivers measurable value。

【窦文涛】这一章的核心结论：Specialization Pattern 让一份 runtime 长出 N 个专用 agent，派生成本从 40 天降到 15 分钟，底层升级只改一处。下一章 Lena 面对的是真正的全栈挑战：Browser Agent 需要同时调度感知（DOM 解析）、规划（点击序列生成）、执行（动态加载等待）三个支柱，是检验通用 agent 架构极限的最好样本。
