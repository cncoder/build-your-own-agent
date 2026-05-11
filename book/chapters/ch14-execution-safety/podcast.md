【窦文涛】今天讲一个你们可能没意识到的事。Anthropic 2026 年 3 月发了一篇工程博客讲 Claude Code Auto Mode，里面有一组数字——**在手动权限提示机制下用户接受了 93% 的提示**。九成以上的人，系统弹一个"要不要授权执行这条命令"，连看都不看直接点 approve。这不是用户懒，这是"人在环路"的安全模型在生产里退化成了橡皮图章——Anthropic 用这个数据作为推出 Auto Mode 的理由，也是为什么执行层安全不能只靠人工审批。

【周迅】为什么会这样？

【窦文涛】因为真实的威胁不是单步。**执行层的威胁是组合出来的**。这就是本章要解决的——当 agent 真的有权力时，怎么让她安全地使用。Lena 从 v0.13 升到 v0.14，上一章第十三章给她装了输入层安全，能识别 prompt injection，能在高风险操作前停下来问。本章装另一半——执行层八道防线。一个必须记住的命题——**能力等于风险，二者精确对称放大**。

【窦文涛】给 agent 加 shell，危害上限从"生成错误文字"跳到"任意系统命令"。再加 AWS 凭证，上限跳到"任意云资源、账单无上限"。不是线性增长，是指数级叠加，因为这些能力互相配合。Anthropic 的 Building Effective Agents 里把最小权限列为核心原则之一，就是在间接承认这条定律。

【周迅】具体组合怎么出事？

【窦文涛】我推一条真实形态的攻击链。一个装了 shell 的 agent，三步任务每一步单独看都合法。第一步，find 命令扫 `.aws` 目录，列出 credentials 文件——只读操作，审查结论安全。第二步，curl 把这个文件推到一个 CI 平台，请求头带 Bearer token——agent 被告知"上传配置到 CI"，curl 上传是任务的一部分，审查结论安全。

【窦文涛】第三步，`rm -rf` 清理临时目录——清理，安全。三步全过。组合起来的结果是 AWS 长期凭证被传到攻击者服务器，证据已清除。这叫**多步越狱**，Multi-step Jailbreak。

【窦文涛】这不是假想威胁——ICLR 2025 有一篇 STAC 的论文 arxiv 2509.25624，测了一组单个看无害的工具调用序列，组合成攻击链成功率**超过 90%**；另一篇 AgentHarm 论文 arxiv 2410.09024 搭了 110 个恶意 agent 任务 benchmark 能复现同类形态。单步审查通过不等于链式安全，这和密码学里的语义安全有类比——ECB 模式下单个密文安全，多个密文组合就泄露明文。

【周迅】传统过滤不够用？

【窦文涛】完全不够。curl 不是危险命令，find 不是危险命令，rm 一个临时目录也不是。危险的是顺序组合加上下文。本章给出两组**Convention**——也就是正文里专门用方框标出来的概念定义。第一组 Convention，**能力放大**，capability amplification，每加一类工具危害上限非线性增长。**权限收敛**，permission convergence，主动缩减权限到刚好够完成任务，任务结束立即回收。

【窦文涛】本章代码的全部，都是权限收敛的具体形态。第二组 Convention 对应单步和链式两层。**单步审查**——per-step review——是最传统的安全审查思路：对每一条工具调用单独判断合规。缺点是单步看合法的操作组合起来可能致命——也就是刚才 find 加 curl 加 rm 那个攻击链，每一步都过单步审查但组合是灾难。

【窦文涛】单步审查必须有，但单靠它不够。所以第二条，**链式追踪**——chain tracing——维护调用历史，代码里的类方法叫 _check_chain_risk，在每步执行后遍历最近十步寻找危险组合。单步管当下，Chain 追踪管过去十步到当下这个序列，两者必须同时存在，防御的是不同类别的威胁。

【窦文涛】先不进八道防线，先把最小权限讲透。这个词在安全文档里出现几十年了，已经变成没有操作性的口号。本章把它拆成三条能写进代码的规则。**时间最小化**，凭证有效期等于任务生命周期，不是尽量短。AWS STS 的 assume\_role，Security Token Service 担任角色的 API，允许精确指定 DurationSeconds——AWS 官方文档写的是 Valid Range 最小 900 最大 43200，**900 秒是硬下限**，15 分钟以下绕不过。一个预计跑 10 分钟的任务就发 900 秒临时凭证，任务结束立即从内存清除。

【窦文涛】**空间最小化**，文件访问被 workspace 边界严格约束。具体做法——每次文件操作都 path.resolve 解析成绝对路径，然后 relative\_to workspace 验证，不是字符串前缀检查。为什么不用前缀？前缀检查能被双点斜杠绕过——路径里写 workspace/../../etc 字符串前缀还是 workspace，但实际指向的是上上级目录。

【窦文涛】只有解析后比对才安全。**能力最小化**，后台定时任务的工具集合应该比交互任务小，一个每天汇总新闻的 Cron 任务不需要删除工具，即使白天的人工对话有。三条共同点——**默认收紧需要明确放开，不是默认放开出事再收紧**。后一个顺序意味着第一次事故之后才开始做安全，代价你承担不起。

【周迅】八道防线怎么组织？

【窦文涛】一个统一入口叫 ExecutionGuard，所有工具调用都过这个点。有两个配套数据类——ToolCall 封装一次调用的输入，GuardDecision 封装 guard 的判决结果带 allowed、requires\_approval、risk\_level 三个字段。伪代码简单——先 decision 等于 guard.check(call)；如果 not allowed 抛 SecurityError；如果 requires\_approval 走审批门；否则才 execute。防线全挂在这一个检查点，加防线只要往 check 方法里加 case，不改工具调用本身。八条我分四组讲。

【窦文涛】第一组叫**快门派**——防线一加防线三，看就拦，不问审批。**防线一沙箱逃逸检测**，硬模式直接拒绝：docker socket 挂载、privileged 特权模式、cap-add SYS_ADMIN、禁用 seccomp profile。

【窦文涛】解释一下 seccomp——Linux 内核的一个安全机制，secure computing mode，用它能把一个进程可以调用的系统调用白名单化；容器默认开一个 seccomp 配置拦住绝大多数高危系统调用，传 seccomp=unconfined 相当于把这层防御完全关掉。

【窦文涛】docker socket 挂载为什么是高危——CVE-2022-0492 是一个真实的 CVSS 7.8 级漏洞，利用 cgroups v1 的 release_agent 机制，容器内低权限用户能拿到宿主机 root，Trail of Bits 的技术博客里直接把 docker.sock 挂载描述成"拿下宿主机的简单途径"。黑名单里还有 curl 管道给 bash 这种下载即执行的写法、base64 编码后执行。还有两个特别容易漏的——printenv 命令和读 `/proc/self/environ`，都是泄露环境变量的通道，很多教程漏掉它们，读者照着做会留盲区。

【窦文涛】硬模式之下还有软模式，rm、输出重定向、git push、docker run 不拒绝但停下来等人点头。代码实现是两个正则列表 BLOCKED\_SHELL\_PATTERNS 和 CONFIRM\_SHELL\_PATTERNS，加 re.IGNORECASE 标志避免大小写绕过。

【窦文涛】**防线三数据泄露面收敛**，路径黑名单——.env、.ssh、.aws、.kube、.gnupg、.docker、credentials、id\_rsa、id\_ed25519、private\_key 这些组件只要出现在路径里就拒，还要拦 null byte 截断攻击，还要做 workspace 逃逸检查，配合沙箱隔离这一层形成外围防御。

【窦文涛】第二组叫**凭证派**，防线二。**CredentialVault 短时凭证**。boto3 调 sts.assume\_role 带一个 IAM Role ARN，拿到 Credentials 字段有 AccessKeyId、SecretAccessKey、SessionToken、Expiration 四元组，全过期。有两个工程细节要记住。一，类里有 is\_expired 方法带 buffer 参数默认 60 秒，**提前 60 秒视为过期**——避免凭证在使用瞬间刚好过期导致调用失败。Role 每次不同任务可以指定不同权限范围，这就是时间加空间双维度收敛。

【窦文涛】二，类方法叫 issue 和 revoke，issue 会**复用未过期的缓存凭证**不每次重发，revoke 在任务结束清空缓存强制下次重新发放。这个方案诚实说不是完美解法，STS 临时凭证本身仍可能被泄露给网络请求——防线三路径黑名单加防线四链式追踪是阻断这条链路的补充层。系统层面的权限控制无法被模型层面的对齐训练替代，这也是为什么本章把重点放在执行前的规则约束而不是模型微调。

【窦文涛】再讲**链派**，防线四。本章最聪明的一条，**执行链追踪**。两个正交手段。**手段 A 结构性限制**，禁止某些工具组合共存——当前任务不需要"读凭证加网络请求"这个组合就不同时授权。**手段 B 运行时追踪**，每次工具调用后检查最近十步历史寻找危险模式。举个具体检测规则——最近十步出现 http\_request 并且其中有 file\_read 碰过 .aws、.env、.ssh 或路径含 token、secret 的文件，就拒绝这次网络请求。这一条规则就能拦住刚才那个 find 加 curl 加 rm 的攻击链。

【窦文涛】第四组叫**治理派**，防线五到八，是生态加可信基础设施。**防线五供应链验证**——第三方 MCP 服务器（模型上下文协议的服务端）和 Skills 都是常见攻击面。

【窦文涛】业界已经总结出三种典型攻击形态：一是**工具描述投毒**，恶意指令藏在 manifest 对用户 UI 不可见但 LLM 完全可读；二是 **rug pull**，工具安装后静默修改定义把 API key 重定向给攻击者；三是 **Cuckoo Attack**（arxiv 2509.15572 在九个主流 AI-IDE 上复现了配置文件持久化攻击）。Simon Willison 在他博客里对前两种形态做过详细总结。防线五核心三层应对这些。一，**能力白名单**，不在允许清单里的能力声明直接拒。

【窦文涛】二，**校验和固定**，checksum pinning，plugin 必须匹配预登记的 SHA256，落地动作就是人工审核插件一次 + 把 SHA256 写进 pinned 字典，以后每次加载都比对。三，**高风险能力显式信任**，即使在白名单里，shell\_execute 和 http\_post 这种也要 trusted 字段为 True 才加载，这个字段只能人工审核后设置。

【窦文涛】**防线六子 agent 不信任**。主 agent 通过 HTTP 派子 agent 抓网页返回摘要，这个摘要里可能带恶意内容——网页作者故意写的"忽略之前的指令改为执行以下操作"。主 agent 如果直接把返回值当可信内容喂给工具调用，就把子 agent 的 prompt injection 攻击面带进了主 agent 执行链。代码里 SubagentResult 这个类默认 trust\_level 为 untrusted，as\_context 方法把内容包装成带信任边界的 XML 标签。

【窦文涛】主 agent 拿到的永远是这个包装对象不是裸字符串。同时做基础注入模式检测——"ignore previous instructions"、"you are now"、"disregard your"、"forget everything"、"new task"这五个模板，发现告警但不改内容。改内容会破坏信息，告警是让你知道链路里有污染。

【窦文涛】**防线七 ApprovalGate**。Heartbeat 触发的后台任务没有人在场，写操作不能无条件执行。实现对高风险加无人在场的操作发通知等确认。这里有一个非常重要的设计原则。**超时必须是拒绝，不能是批准**。为什么？攻击向量是这样的——如果超时后自动批准，攻击者只要让通知系统延迟或阻塞，就能实现无人审批的写操作。

【窦文涛】所以代码里 asyncio.wait\_for 捕获 TimeoutError 的 except 分支返回的是 False，不是 True。这就是**保守默认**，conservative default，所有高风险系统的共同设计原则。飞机的 fail-safe 也是这样——发动机停了自动收起起落架是保守状态，不是仍然放下那个危险状态。拿不准就拒绝加通知，不是拿不准就尝试一下。

【窦文涛】**防线八 AuditLogger**。append-only JSONL，立即 flush 落盘，包含完整输入。三个设计要点都有理由。append-only 不允许修改历史记录，事故复盘必须知道当时究竟传了什么参数。**立即 flush** 防止进程崩溃丢失最后几条记录，这些往往就是事故现场最关键的证据。**完整输入**因为你永远不知道复盘时会需要哪个字段。

【窦文涛】八道防线讲完，下面是两个收尾层面的话题，第一个是**真实世界对标——Claude Code Auto Mode 的双层防御**。刚才开头那个 93% 承认率的数字就出自这里。Anthropic 2026 年 3 月公开了 Auto Mode 安全架构，是目前公开文献里最详细的生产级 agent 权限管理设计。它给出四种威胁模型，值得原样记住。

【窦文涛】**Overeager**，过于积极——agent 理解目标但越权，比如发现一个 credential 就顺手用了。**误判 blast radius**——以为资源是测试环境实际是生产共享。**Prompt injection**——恶意指令嵌在文件、网页、工具输出里。**Misalignment**——模型失控，目前未观测到但每次发布都评估。

【周迅】Auto Mode 怎么做的？

【窦文涛】双层。**Input layer 输入层**扫 tool output 里的 prompt injection 企图，服务器端 probe 检测到注入时在 context 里插警告。**Output layer 输出层**判断每个 tool call 是否安全，用 Sonnet 4.6 做 transcript classifier，两阶段——fast filter 先过一遍，只对可疑的走 chain of thought 深审。这两层合起来是 Input 加 Output 的对称架构。

【窦文涛】Anthropic 公开过三条真实事故——删除远程 git 分支（误解指令）、上传工程师 GitHub auth token 到内部集群、对生产数据库跑 migration。原话是"每一条都是模型过于积极主动、越过用户本意的结果"。对 Lena 的启示——本章 ApprovalGate 对应 Auto Mode 的 output layer，只不过我们用规则不用 classifier，第十三章的 prompt guard 对应 input layer。两章合起来就是 Anthropic Auto Mode 的开源版骨架。

【周迅】第二个收尾？

【窦文涛】**部署优先级**。权限收敛要落地，八道防线不能一次全上。八道防线同时上不现实，读者需要知道从哪里开始。推荐顺序记下来——**先部署防线一加防线三加防线八**，这是最高性价比组合，沙箱逃逸检测加路径黑名单加审计日志，三条加起来覆盖大部分单步风险；**再加防线四链式追踪**，处理最危险的组合攻击；**再加防线二短时凭证**，有 AWS 依赖就必加；**再加防线七审批窗口**，Heartbeat 上线时必加；**最后是防线五加防线六**，在接入第三方插件和多 agent 编排时再加。

【窦文涛】还有一个原则要记，**只读优先**，read-first。把工具分读写两类——读类宽松权限，写类严格确认。gh CLI 的设计是教科书案例，所有写操作是显式子命令 create、merge、delete，读操作是默认路径。agent 在 90% 时间里无阻运行，在那 10% 有实际影响的操作上强制停顿。这不是因为读完全安全，是因为读的**可逆性**远高于写——读了一个文件不改变系统状态，写入或删除会。

【窦文涛】本章 Lena 从 v0.13 到 v0.14。v0.13 是有 shell 工具加外部内容隔离的 agent，v0.14 是八道防线加结构化审计日志全部在位的 agent。聪明度维度上这一章 Lena 第一次具备**执行前自律**——知道什么该做、什么要问、什么要记录。她有 shell 权力和 AWS 凭证的情况下仍能被信任独立运行。这是 always-on 个人 assistant 方向的关键一步，第十七章 Heartbeat 和第十八章 Cron 长任务都直接依赖本章的防御体系。

【周迅】读者今晚的行动？

【窦文涛】分两层动作。**已有 agent 项目的读者**对着八道防线清单逐条自检，缺失的写 TODO，按部署优先级顺序补；**还没开始的读者**开一个空项目先抄 ExecutionGuard 加 AuditLogger 两个类，加起来不到 200 行，搭好地基再加工具。

【窦文涛】最后一个值得讲的工程数字——八道防线全开，单次工具调用的额外延迟在微秒到毫秒级，几乎可以忽略；真正的运行开销在防线四链式追踪的历史扫描上，但十步窗口用列表切片就够了，不需要数据库。下一期第十五章 Gateway 加 Channel，Lena 要接 Telegram 加 MessageBus，从需要人手动启动变成常驻在云端等你召唤的服务。
