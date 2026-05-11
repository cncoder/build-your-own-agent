# 第 27 章：手写 → 框架 → 托管——AgentCore 把什么收进云里

> **Lena 状态**：v2.6（Strands 框架版）→ v2.7（概念版：理解托管服务把哪些职责托管出去）

---

## Beat 1 · 从框架再往上：为什么还要有托管服务这一层

上一章你用 Strands 重写了 Lena v0.3，感受到了"框架把实现细节收起来"的感觉。那往上还有一层是什么？

框架解决的是"怎么写代码"的问题——它让你用更少的代码表达同样的 agent 逻辑。但它解决不了以下这些问题：

这个 agent 跑在哪台机器上？谁来保证它 24 小时不宕机？当 100 个用户同时请求时，session 之间怎么隔离？agent 访问外部服务（Slack、数据库、GitHub）时，OAuth token 存在哪里、由谁来刷新？跨 session 的长期记忆怎么持久化？

这些是**运维问题**，不是代码问题。框架不管运维，托管服务管。

Amazon Bedrock AgentCore 是 AWS 在 2025 年发布的 agent 托管平台。它的自我定位是"无需基础设施管理，即可构建、部署和大规模运行 AI agent 的全托管平台，支持任意框架和模型"。[^1] 重点在"任意框架"——它不要求你用 Strands，LangGraph、CrewAI、LlamaIndex 都可以跑在它上面。

从你亲手写过的东西来看，AgentCore 把这几章的内容"服务化"了：

- 第 3 章的 while 循环和 session 管理 → **Runtime**
- 第 8-9 章的记忆系统和向量检索 → **Memory**
- 第 6、19 章的工具注册和 MCP 协议 → **Gateway**
- 第 13-14 章的安全沙箱和最小权限 → **Identity + Runtime 隔离**
- 第 22 章的可观测性 → **Observability**

这一章的目标是把这个映射讲清楚，让你知道当你真的需要"把 Lena 搬上 AWS 生产环境"时，每块砖对应哪个托管服务，以及什么情况下你反而不应该用托管服务。

本章不部署真实 AWS 账号，代码全部使用 mock 数据。这不只是为了安全，也是因为理解托管服务的第一步是**理解它在做什么**，而不是先学会命令行参数。

---

## Beat 2 · AgentCore 五件套

### Runtime：session 就是执行环境

Runtime 是 AgentCore 的核心——它是 agent 代码的运行容器，每个 session 独享一个 microVM。

当你在手写 Lena 里做一次对话，session 状态活在进程内存里。进程死掉，状态就没了。AgentCore Runtime 把这个进程包进了一个 microVM：独立的 CPU、内存和文件系统，与其他 session 完全物理隔离。session 结束后，整个 microVM 被销毁并清零内存——AWS 的官方文档把这叫做"在非确定性 AI 过程中实现确定性安全"。[^2]

几个关键参数：最长执行 8 小时，空闲超时 15 分钟，单个 payload 上限 100 MB，计算架构是 ARM64（AWS Graviton）。8 小时这个上限在第 18 章讲 Cron 和长任务时你已经感受过为什么重要——跨天执行的 agent 任务，不能因为进程重启就从头来。

### Memory：托管的两层记忆

第 8 章你手写了情景记忆、语义记忆、程序记忆的分层。AgentCore Memory 把这个抽象具体化成两层：短期记忆（single session 内的对话 turns）和长期记忆（跨 session 的知识提取）。

长期记忆有两种提取策略。SEMANTIC 策略从对话里提取事实性信息，以向量形式存储，后续用语义搜索检索；SUMMARIZATION 策略把对话摘要化，适合需要"上次聊什么"的场景。

官方文档对 Memory 存在意义的描述很直白："AgentCore Memory 解决了 agent AI 的一个根本挑战：无状态性。没有记忆能力，AI agent 把每次交互都当作一个全新的实例，对之前的对话一无所知。"[^3]

### Gateway：工具注册的服务化

第 6 章你手写了 ToolRegistry，手写了每个工具的 JSON Schema。第 19 章你实现了 MCP 客户端，接入外部工具服务器。

Gateway 把这两件事合并成一个托管服务：你提供 OpenAPI spec 或 Lambda 函数，Gateway 把它转成统一的 MCP 工具端点，agent 通过一个接口访问所有工具。更进一步，Gateway 内置了语义工具发现——agent 不需要知道工具的确切名字，只需要描述它要做什么，Gateway 用 embedding + 向量搜索找到最匹配的工具。

官方文档说 Gateway "消除了数周的自定义代码开发、基础设施搭建和安全实现"。[^4] 这个说法不夸张——你在第 6 章、第 13 章和第 19 章加起来花的篇幅，就是这句话在说的那些工作。

### Identity：agent 自己的身份

第 13-14 章你处理的安全主要是"agent 代码层面的安全"——不信任外部输入、沙箱化执行。但还有一个维度你没有手写：**agent 本身的身份问题**。

当 Lena 需要访问 GitHub 的 API 时，它用谁的身份？用你的 personal token？还是一个专门的 service account？如果 Lena 代表某个用户访问该用户的 Slack，OAuth token 存在哪里？

AgentCore Identity 给 agent 提供了独立的工作负载身份（workload identity），区别于人类用户身份。它支持两种出站模式：用户委托（agent 代表用户，用用户授权的 token），以及自主访问（agent 用预授权的服务凭据，适合定时任务这类没有用户在线的场景）。入站认证支持 AWS IAM（SigV4）和 OAuth 2.0。

### Observability：OTEL 全托管

第 22 章你用 OpenTelemetry 给 Lena 加了 trace 和 metric。AgentCore Observability 把这个流水线托管了：agent 运行时自动产生 OTEL 格式的 trace、metric 和 log，直接写入 CloudWatch，不需要你维护 collector 基础设施。

内置指标包括 session 数量、每次调用延迟、总执行时长、token 用量、错误率。Trace 里记录了每步 agent 决策路径和工具调用中间输出。

---

## Beat 3 · 架构示意：漏洞情报 agent 如果用 AgentCore 搭是什么样

下面用一个假设性场景演示"如果用 AgentCore 搭"的架构思路。这是一个 AWS 基础设施安全审计 agent，自主决定调用哪些安全服务工具，生成漏洞情报报告。

**声明：以下代码全部使用 mock 数据，不连接任何真实 AWS 账号。目的是展示 AgentCore 的工具注册思路，不是生产代码。**

```python
# 示意代码：security_agent_demo.py
# 运行条件：无需 AWS 凭证，全部 mock
# 目标：演示 AgentCore 的工具注册模式和 agent 工作方式

from strands import Agent, tool

# --- Mock 数据层（替代真实 AWS API 调用）---
MOCK_CLOUDTRAIL = [
    {"event": "PutBucketAcl", "user": "admin",
     "detail": "demo-bucket 被设置为 public-read"},
    {"event": "CreateAccessKey", "user": "ci-bot",
     "detail": "新 IAM access key 已创建"},
]
MOCK_CONFIG = [
    {"rule": "s3-bucket-public-read-prohibited",
     "status": "NON_COMPLIANT", "resource": "demo-bucket"},
]
MOCK_GUARDDUTY = [
    {"type": "UnauthorizedAccess:IAMUser/MaliciousIPCaller",
     "severity": 7.0, "detail": "可疑 IP 调用 IAM API"},
]

# --- 工具定义（三个 mock tool，每个 ~15 行）---

@tool
def audit_cloudtrail(hours: int = 24) -> dict:
    """
    查询 CloudTrail 审计日志，发现可疑 API 调用。
    参数 hours: 查询最近多少小时的记录。
    返回: 事件列表和总数。
    """
    return {
        "queried_hours": hours,
        "total_events": len(MOCK_CLOUDTRAIL),
        "suspicious_events": MOCK_CLOUDTRAIL,
        "note": "数据来自 mock，非真实 AWS 账号",
    }

@tool
def check_config_rules(resource_type: str = "") -> dict:
    """
    查询 AWS Config 合规性结果，识别违反安全基线的资源配置。
    参数 resource_type: 过滤资源类型（如 'S3'，空表示查全部）。
    返回: 不合规项列表。
    """
    findings = MOCK_CONFIG
    if resource_type:
        findings = [f for f in findings
                    if resource_type.upper() in f["rule"].upper()]
    non_compliant = [f for f in findings if f["status"] == "NON_COMPLIANT"]
    return {
        "total_checked": len(findings),
        "non_compliant": non_compliant,
        "note": "数据来自 mock，非真实 AWS 账号",
    }

@tool
def scan_guardduty_threats(min_severity: float = 5.0) -> dict:
    """
    查询 GuardDuty 威胁情报，发现异常行为。
    参数 min_severity: 最低严重分数（0-10）。
    返回: 超过阈值的威胁列表。
    """
    threats = [t for t in MOCK_GUARDDUTY if t["severity"] >= min_severity]
    return {
        "min_severity": min_severity,
        "threats_found": len(threats),
        "threats": threats,
        "note": "数据来自 mock，非真实 AWS 账号",
    }

# --- Agent 定义 ---
# 如果部署到 AgentCore，以下代码结构不变，
# 变化的是部署方式（agentcore deploy）和 Memory/Identity 的注入方式

security_agent = Agent(
    system_prompt=(
        "你是一名 AWS 基础设施安全分析师。"
        "自主决定调用哪些安全工具，汇总发现的漏洞，"
        "按 HIGH/MEDIUM/LOW 严重级别分类，给出修复方向。"
        "所有数据来自 mock 环境，这是演示用途。"
    ),
    tools=[audit_cloudtrail, check_config_rules, scan_guardduty_threats],
)

if __name__ == "__main__":
    result = security_agent("对当前环境进行安全审计，生成摘要报告")
    print(result)
```

如果要把这个 agent 部署到 AgentCore，核心步骤是：

```bash
# 1. 安装 CLI（只需一次）
npm install -g @aws/agentcore

# 2. 创建项目（生成脚手架，不改变你的 agent 代码）
agentcore create --name SecurityAuditAgent \
  --framework Strands \
  --model-provider Bedrock \
  --memory longAndShortTerm

# 3. 本地调试（启动带 trace 可视化的本地环境）
agentcore dev

# 4. 部署（CDK 自动创建 IAM roles、ECR、Runtime endpoint）
agentcore deploy
```

部署后你得到一个 Runtime ARN，之后通过 boto3 调用：

```python
import json, uuid, boto3

client = boto3.client("bedrock-agentcore")
# stubbed response — 演示调用格式，不连接真实 endpoint
response = client.invoke_agent_runtime(
    agentRuntimeArn="arn:aws:bedrock-agentcore:us-west-2:ACCOUNT:agent-runtime/SecurityAuditAgent",
    runtimeSessionId=str(uuid.uuid4()),
    payload=json.dumps({"prompt": "生成安全审计报告"}).encode(),
    qualifier="DEFAULT",
)
```

**动态工具注册的思路**：如果这个 agent 需要对接更多安全服务（比如未来加入 Macie 或 Trusted Advisor），通过 Gateway 注册新工具，agent 代码不需要改动。Gateway 的语义工具发现会自动让模型"发现"新工具的存在。这正是第 6 章"任何能力 = 工具；加工具不改核心"这个原则在托管层的体现。

---

## Beat 4 · 映射回六大支柱

下面这张表是本章最重要的一张——它把你在前 25 章手写过的东西，和 AgentCore 的托管化方案对应起来。读这张表的方式：左边是你熟悉的东西，右边是"如果不手写，平台替你做什么"。

| 六大支柱 | 手写 Lena（你在哪章做的） | AgentCore 托管方案 | 托管节省了什么 |
|---|---|---|---|
| **Tool universality** | 第 6 章：ToolRegistry + JSON Schema 生成；第 19 章：MCP 客户端 | Gateway：OpenAPI → 统一 MCP 端点；语义工具发现 | 手写 tool registry 和 schema 维护；外部服务认证管理 |
| **Planning / 自主拆解** | 第 2-3 章：ReAct loop；第 11 章：subagent 调度 | Strands model-driven loop 运行在 Runtime 上；Policy（Preview）负责工具调用前的规则拦截 | 基础设施层的进程管理；安全策略从 agent 代码里解耦出来 |
| **Long-horizon 执行** | 第 18 章：Cron + checkpoint；第 17 章：Heartbeat | Runtime：最长 8 小时 session，microVM 保持上下文；Async 模式支持后台任务 | 手写 checkpoint + 任务恢复逻辑；进程级别的 keepalive |
| **Memory / 世界模型** | 第 8-9 章：向量 DB + 摘要流水线 | Memory：短期（session turns）+ 长期（SEMANTIC/SUMMARIZATION）全托管 | 向量数据库运维；摘要模型调用和成本管理 |
| **Safety / 可控性** | 第 13-14 章：PromptGuard + sandbox + 最小权限 | Identity（工作负载身份隔离）+ Runtime microVM（物理隔离）+ Policy（Cedar 规则，Preview） | 基础设施级别的 session 隔离；外部服务凭证轮换 |
| **Specialization** | 第 23-25 章：能力削减 + 知识强化 + 派生工具 | agentcore CLI：模板化创建 + `agentcore deploy` 一键部署 | 容器构建和推送；IAM role 创建；endpoint 配置 |

用一句话概括：**托管服务托管的是基础设施职责，不是业务逻辑**。你的 system prompt、工具逻辑、安全策略——这些仍然是你的代码。托管服务接管的是"让这些代码在生产环境里跑起来并保持跑着"的那部分工作。

---

## Beat 5 · 边界与取舍：什么时候该考虑托管，什么时候不该

### 值得考虑托管服务的场景

**合规要求明确**。如果你的 agent 处理医疗数据（HIPAA）或金融数据（SOC 2），每个 session 的物理隔离不是"最好有"而是"必须有"。自己实现 microVM 隔离的成本和专业度要求很高，这是托管服务价值最清晰的场景。

**团队规模小，运维成本敏感**。一个 3-5 人的团队，没有专职 DevOps，agent 的基础设施维护（更新、监控、故障恢复）会占据大量精力。AgentCore 的消费计费模式（按实际 CPU/内存使用按秒计费，I/O 等待期间不计费[^5]）在低流量场景下通常比自建集群便宜。

**多租户隔离**。如果你的产品服务多个客户，每个客户的 agent session 必须完全隔离。Runtime 的 microVM 模型把这个隔离做在基础设施层，而不是靠应用代码里的 if-else 区分。

### 不值得的场景

**高度定制化的执行环境**。AgentCore Runtime 的容器镜像必须是 ARM64 架构（AWS Graviton），部署区域目前主要是 us-west-2。如果你的 agent 依赖 x86-only 的二进制库，或者数据主权要求决定了不能离开特定区域，托管服务的限制会成为摩擦来源。

**极致的延迟要求**。量化交易等场景需要亚 50ms 的工具响应。托管服务的调用链（SDK → 网络 → Runtime microVM → 工具）比直接 in-process 执行多几跳。如果延迟是你的关键约束，应该先评估这几跳的开销。

**团队已有成熟的 Kubernetes 运维能力**。如果你的团队在 EKS 上已经运维过生产级服务，把 agent 跑在 Kubernetes 上的成本不会比 AgentCore 高多少，同时控制权更完整。

### 定价要理解

AgentCore 的计费有一个对 agent 场景友好的特性：**等待 LLM 响应期间不计费**。[^5] agent 执行时间里有相当大比例是在等 LLM 返回结果，这段时间的 CPU 是空闲的，AgentCore 不收这段时间的钱。这和普通 serverless（Lambda 按请求时长计费）不同，算下来实际费用通常低于按总时长计算的估值。

但也要把所有组件的成本加起来算：Runtime 按 CPU+内存计，Memory 按写入事件和检索次数计，Gateway 按 API 调用次数计，Observability 按 CloudWatch 摄取量计。小流量场景下整体很便宜，高流量场景下需要做明确的成本测算，不要只看 Runtime 一项。

**Vendor lock-in 是真实的**。`agentcore deploy` 命令生成的 CDK 脚手架、`arn:aws:bedrock-agentcore:...` 格式的 ARN、boto3 的 `invoke_agent_runtime` 调用——这些都是 AWS 专有接口。把 agent 迁移到其他云需要重写运维层。这不是 AWS 独有的问题（任何托管服务都有这个特性），但在决策时需要明确接受这个约束，而不是假装它不存在。

---

## 三道思考题

1. 本章的映射表里，"Safety / 可控性"支柱在 AgentCore 里有三层防御（Identity + microVM + Policy）。你认为这三层里，哪一层在实际工程里最容易被配置错误？错误配置的后果是什么？

2. AgentCore Memory 的长期记忆使用 SEMANTIC 策略（从对话里提取事实）。第 8 章提到人类记忆有一个 consolidation 过程——不只是存储事实，而是提炼原则。SEMANTIC 策略能做到"原则提炼"吗？它缺少什么？

3. 假设你要把 Lena v2.6（第 26 章的 Strands 版本）部署到 AgentCore，你会选择加入 Memory 服务、不加入 Identity 服务。给出你的理由，以及什么样的需求变化会让你改变这个决定。

---

[^1]: Amazon Bedrock AgentCore 产品主页, https://aws.amazon.com/cn/bedrock/agentcore/
[^2]: Amazon Bedrock AgentCore Runtime 工作原理, https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html
[^3]: Amazon Bedrock AgentCore Memory 文档, https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html
[^4]: Amazon Bedrock AgentCore Gateway 文档, https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html
[^5]: Amazon Bedrock AgentCore 定价, https://aws.amazon.com/cn/bedrock/agentcore/pricing/
