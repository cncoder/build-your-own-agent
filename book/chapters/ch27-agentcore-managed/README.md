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

本章代码全部使用 mock 数据。Beat 6 包含一段基于官方定价数字的成本估算代码：以实际 CPU 活跃秒数为单位，展示 AgentCore 计费模型与 Lambda 按总时长计费模型的差异，读者可以用自己的 workload 数字代入。

---

## Beat 2 · AgentCore 五件套

### Runtime：session 就是执行环境

Runtime 是 AgentCore 的核心——它是 agent 代码的运行容器，每个 session 独享一个 microVM。

当你在手写 Lena 里做一次对话，session 状态活在进程内存里。进程死掉，状态就没了。AgentCore Runtime 把这个进程包进了一个 microVM：独立的 CPU、内存和文件系统，与其他 session 完全物理隔离。session 结束后，整个 microVM 被销毁，内存经过 memory sanitization（内存清零：把物理内存页覆写为零值，确保数据无法从已终止 session 的内存里恢复）——AWS 的官方文档把这叫做"在非确定性 AI 过程中实现确定性安全"。[^2]

几个关键参数（来自官方文档[^2]）：session 最长存活 8 小时（total runtime），空闲超时 15 分钟（idle timeout），计算架构是 ARM64（AWS Graviton）。8 小时这个上限在第 18 章讲 Cron 和长任务时你已经感受过为什么重要——跨天执行的 agent 任务，不能因为进程重启就从头来。

### Memory：托管的两层记忆

第 8 章你手写了情景记忆、语义记忆、程序记忆的分层。AgentCore Memory 把这个抽象具体化成两层：短期记忆（single session 内的对话 turns）和长期记忆（跨 session 的知识提取）。

长期记忆有两种提取策略。SEMANTIC 策略从对话里提取事实性信息，以向量形式存储，后续用语义搜索检索；SUMMARIZATION 策略把对话摘要化，适合需要"上次聊什么"的场景。

官方文档对 Memory 存在意义的描述很直白："AgentCore Memory 解决了 agent AI 的一个根本挑战：无状态性。没有记忆能力，AI agent 把每次交互都当作一个全新的实例，对之前的对话一无所知。"[^3]

### Gateway：工具注册的服务化

第 6 章你手写了 ToolRegistry，手写了每个工具的 JSON Schema。第 19 章你实现了 MCP 客户端——MCP（Model Context Protocol）是 Anthropic 发起的开放工具调用标准，核心是 `tools/list` 和 `tools/call` 两个 JSON-RPC 接口，让任何框架的 agent 都能发现和调用遵循这套协议的工具服务器。当时你手写了 MCP 客户端；Gateway 的角色是把 MCP 服务端托管了。

Gateway 把这两件事合并成一个托管服务：你提供 OpenAPI spec 或 Lambda 函数，Gateway 把它转成统一的 MCP 工具端点，agent 通过一个接口访问所有工具。更进一步，Gateway 内置了语义工具发现——agent 不需要知道工具的确切名字，只需要描述它要做什么，Gateway 用 embedding + 向量搜索找到最匹配的工具。

官方文档说 Gateway "消除了数周的自定义代码开发、基础设施搭建和安全实现"。[^4] 这个说法不夸张——你在第 6 章、第 13 章和第 19 章加起来花的篇幅，就是这句话在说的那些工作。

### Identity：agent 自己的身份

第 13-14 章你处理的安全主要是"agent 代码层面的安全"——不信任外部输入、沙箱化执行。但还有一个维度你没有手写：**agent 本身的身份问题**。

当 Lena 需要访问 GitHub 的 API 时，它用谁的身份？用你的 personal token？还是一个专门的 service account？如果 Lena 代表某个用户访问该用户的 Slack，OAuth token 存在哪里？

AgentCore Identity 给 agent 提供了独立的**工作负载身份（workload identity）**：与"用户登录后凭借 session cookie 操作"不同，workload identity 是分配给程序本身的身份凭证——agent 进程有自己的 IAM role 或服务账号，不依赖任何人类用户在线。这解决了一个常见的反模式：很多早期 agent 实现用开发者的个人 API token 访问外部服务，导致 token 意外泄漏时无法单独吊销。AgentCore Identity 支持两种出站模式：用户委托（agent 代表用户，用用户授权的 OAuth token）和自主访问（agent 用预授权的服务凭据，适合定时任务）。

与 Identity 配套的是 **Policy**（目前 Preview 阶段），它基于 AWS 开源的 Cedar 授权语言。Cedar 的核心概念是把"谁（principal）对什么资源（resource）能做什么操作（action）"写成结构化的 permit/forbid 语句，而不是嵌在代码里的 if-else 逻辑。一条典型的 Cedar 规则看起来是：`permit(principal == Agent::"security-agent", action == Action::"invoke", resource == Tool::"audit_cloudtrail")`。在 agent 场景里，Policy 在工具调用前拦截检查，验证当前 agent 是否被允许调用该工具，把安全策略从 agent 代码里解耦为可独立审计的声明式文件。

### Observability：OTEL 全托管

第 22 章你手动配置了 OTEL Collector 来采集 Lena 的 trace 和 metric。OpenTelemetry（OTEL）是 CNCF 维护的开放可观测性框架，定义了三类标准遥测数据：trace（调用链，记录一次请求经过哪些组件）、metric（数值指标，如延迟、错误率）、log（结构化日志）；Collector 是 OTEL 的数据管道组件，负责接收、处理和转发这些遥测数据到存储后端（CloudWatch、Prometheus 等）。AgentCore Observability 把 Collector 的运维内化了：agent 运行时自动产生标准 OTEL 遥测数据，直接写入 CloudWatch，无需独立部署 collector 进程。

在调试 agent 行为时，最有价值的是 Trace 数据：每次工具调用的入参和出参都被记录下来，可以在 CloudWatch X-Ray 里可视化完整的推理链条，回溯"模型为什么在这一步选了这个工具"。这在手写版 Lena 里需要你自己在每个工具调用前后插 log；AgentCore 默认把这层可观测性开启，并按 CloudWatch 标准费率计费。

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

如果要把这个 agent 部署到 AgentCore，核心步骤是（CLI 命令来自官方文档[^6]）：

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

部署后你得到一个 Runtime ARN，之后通过 boto3 调用（调用格式来自官方文档[^6]）：

```python
import json, uuid, boto3

# boto3 服务名：'bedrock-agentcore'（对应 API endpoint bedrock-agentcore-2024-02-28）
agent_core_client = boto3.client("bedrock-agentcore")
# stubbed response — 演示调用格式，不连接真实 endpoint
response = agent_core_client.invoke_agent_runtime(
    agentRuntimeArn="arn:aws:bedrock-agentcore:us-west-2:ACCOUNT:agent-runtime/SecurityAuditAgent",
    runtimeSessionId=str(uuid.uuid4()),
    payload=json.dumps({"prompt": "生成安全审计报告"}).encode(),
    qualifier="DEFAULT",
)
```

**动态工具注册的思路**：如果这个 agent 需要对接更多安全服务（比如未来加入 Macie 或 Trusted Advisor），通过 Gateway 注册新工具，agent 代码不需要改动。Gateway 的语义工具发现（embedding + 向量搜索）会自动让模型"发现"新工具——这不仅省去了手动更新 ToolRegistry 的工作，还能处理工具命名不一致的情况：即使新工具的函数名和旧版本不同，语义匹配仍然能找到它。

---

## Beat 4 · 映射回六大支柱

下面这张表是本章的核心对应关系——六大支柱中的每个机制，都有对应的 AgentCore 托管组件接管其运维职责，第四列列出了"托管节省了什么工程工作量"：

| 六大支柱 | 手写 Lena（你在哪章做的） | AgentCore 托管方案 | 托管节省了什么 |
|---|---|---|---|
| **Tool universality** | 第 6 章：ToolRegistry + JSON Schema 生成；第 19 章：MCP 客户端 | Gateway：OpenAPI → 统一 MCP 端点；语义工具发现 | 手写 tool registry 和 schema 维护；外部服务认证管理 |
| **Planning / 自主拆解** | 第 2-3 章：ReAct loop；第 11 章：subagent 调度 | Strands model-driven loop 运行在 Runtime 上；Policy（Preview，基于 Cedar 授权语言，用声明式规则定义"agent 能调哪些工具、传什么参数"）负责工具调用前的规则拦截 | 基础设施层的进程管理；安全策略从 agent 代码里解耦出来 |
| **Long-horizon 执行** | 第 18 章：Cron + checkpoint；第 17 章：Heartbeat | Runtime：最长 8 小时 session，microVM 保持上下文；Async 模式支持后台任务 | 手写 checkpoint + 任务恢复逻辑；进程级别的 keepalive |
| **Memory / 世界模型** | 第 8-9 章：向量 DB + 摘要流水线 | Memory：短期（session turns）+ 长期（SEMANTIC/SUMMARIZATION）全托管 | 向量数据库运维；摘要模型调用和成本管理 |
| **Safety / 可控性** | 第 13-14 章：PromptGuard + sandbox + 最小权限 | Identity（工作负载身份隔离）+ Runtime microVM（物理隔离）+ Policy（Cedar 规则，Preview） | 基础设施级别的 session 隔离；外部服务凭证轮换 |
| **Specialization** | 第 23-25 章：能力削减 + 知识强化 + 派生工具 | agentcore CLI：模板化创建 + `agentcore deploy` 一键部署 | 容器构建和推送；IAM role 创建；endpoint 配置 |

一个值得注意的点是：表格最右列（"托管节省了什么"）在跨行上下文里暗示了一个决策框架——当某个基础设施职责在你的团队里是**重复造轮子**时，托管服务的 ROI 最高；当它是你的核心差异化能力时，自建更合适。下一节从实际场景角度展开这个判断。

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

## Beat 6 · 运行验证

### 本地 mock 演示跑通

把 Beat 3 里的 `security_agent_demo.py` 保存到本地，直接运行验证工具注册和 agent 执行路径（无需 AWS 凭证）：

```bash
# 安装依赖（如果还没有）
pip3 install strands-agents

# 运行 mock agent
python3 security_agent_demo.py
```

**预期输出关键词**：

```
[audit_cloudtrail] 调用：queried_hours=24, total_events=2
[check_config_rules] 调用：non_compliant=[s3-bucket-public-read-prohibited]
[scan_guardduty_threats] 调用：threats_found=1, severity=7.0

安全审计摘要报告（mock 环境）
━━━━━━━━━━━━━━━━━━━━━━━━━━
HIGH：
  · GuardDuty 威胁：UnauthorizedAccess:IAMUser/MaliciousIPCaller（严重度 7.0）
  · S3 合规违规：demo-bucket 被设置为 public-read

MEDIUM：
  · CloudTrail 可疑事件：admin 执行 PutBucketAcl

修复方向：
  1. 立即检查可疑 IP 的 IAM API 调用来源
  2. 撤销 demo-bucket 的 public-read ACL
  3. 审查 ci-bot 的新 access key 必要性
```

**预期耗时**：3-8 秒（含 LLM 推理；mock 工具调用本身 < 1ms）。

---

### 模拟 AgentCore 调用格式验证

如果已有 AWS 账号和 AgentCore Runtime ARN，可以用以下代码验证调用格式（本节用 stub 演示，实际运行需要替换 ARN）：

```python
# invoke_demo.py — 验证 AgentCore 调用格式（stub 模式）
import json, uuid

# ── 真实调用格式（替换 ARN 后可直接使用）──
# import boto3
# client = boto3.client("bedrock-agentcore", region_name="us-west-2")
# response = client.invoke_agent_runtime(
#     agentRuntimeArn="arn:aws:bedrock-agentcore:us-west-2:ACCOUNT:agent-runtime/SecurityAuditAgent",
#     runtimeSessionId=str(uuid.uuid4()),
#     payload=json.dumps({"prompt": "生成安全审计报告"}).encode(),
#     qualifier="DEFAULT",
# )

# ── stub 模式：验证数据结构而不产生费用 ──
session_id = str(uuid.uuid4())
request_payload = {
    "prompt": "对当前环境进行安全审计，生成摘要报告",
    "session_id": session_id,
}

print(f"Session ID: {session_id}")
print(f"Payload: {json.dumps(request_payload, ensure_ascii=False)}")
print(f"Payload size: {len(json.dumps(request_payload).encode())} bytes")
print(f"  → 单次 payload 上限 100 MB，本次 {len(json.dumps(request_payload).encode())} bytes，远低于限制")

# 模拟 AgentCore 计费估算
cpu_vcpu = 1
memory_gb = 0.5
active_seconds = 5  # LLM 等待期间不计费，只算实际 CPU 活跃时间

cpu_cost = (cpu_vcpu * active_seconds / 3600) * 0.0895   # $0.0895/vCPU-hour
mem_cost = (memory_gb * active_seconds / 3600) * 0.00945  # $0.00945/GB-hour
total_cost = cpu_cost + mem_cost

print(f"\n费用估算（{active_seconds}s 实际 CPU 时间）：")
print(f"  CPU:    ${cpu_cost:.6f}")
print(f"  Memory: ${mem_cost:.6f}")
print(f"  合计:   ${total_cost:.6f}（约 ${total_cost*1000:.4f} 每千次）")
```

**预期输出**：

```
Session ID: f3a2b1c0-...（每次随机）
Payload: {"prompt": "对当前环境进行安全审计，生成摘要报告", "session_id": "..."}
Payload size: 92 bytes
  → 单次 payload 上限 100 MB，本次 92 bytes，远低于限制

费用估算（5s 实际 CPU 时间）：
  CPU:    $0.000124
  Memory: $0.000007
  合计:   $0.000131（约 $0.1310 每千次）
```

这个费用估算是单次调用的成本。换算成规模：1000 次此类安全审计调用 = 约 $0.13。如果任务量更大，可以用 **Async 模式**（异步调用模式：调用方提交任务后立即返回，不等待 agent 执行完毕；agent 在后台 microVM 里运行，任务完成后通过回调或轮询 `/ping` 端点获取结果，适合超过 HTTP 超时限制的长时间任务）批量提交，AgentCore 会在后台排队执行，避免并发超出账号的 Runtime 配额。

---

### 失败诊断

| 症状 | 可能原因 | 排查方式 |
|------|----------|----------|
| `ModuleNotFoundError: strands` | Strands 未安装 | `pip3 install strands-agents` |
| `NoCredentialsError` | AWS 凭证未配置（只影响真实调用） | `aws configure` 或设置 `AWS_PROFILE` |
| `AgentRuntimeNotFoundException` | ARN 错误或 Runtime 未创建 | 检查 ARN 格式 `arn:aws:bedrock-agentcore:REGION:ACCOUNT:agent-runtime/NAME` |
| session 调用返回 503 | microVM 冷启动未完成 | 重试（microVM 启动通常 < 2 秒）；生产场景可用 keep-alive 预热 |
| Memory 检索返回空 | 短期记忆跨 session 不保留 | 长期记忆需显式调用 Memory API 写入；short-term 只在当前 session 内有效 |

运行验证完成后，有一个设计问题值得深入：Beat 6 失败诊断表里提到"microVM 冷启动"，这是 AgentCore Runtime 选择 microVM 而不是普通容器的直接代价。为什么要付这个代价？

---

## Beat 7 · Design Note

> **为什么 AgentCore 选择 microVM 而不是 Docker 容器做 session 隔离？**

直觉上，Docker 容器就能做 session 隔离——每个 session 一个容器，互相看不见文件系统和进程。这个方案成本低、启动快，很多内部 agent 平台确实是这么做的。

AgentCore 选择更重的 microVM 方案，原因在于 AI agent 的特殊威胁模型：

**容器共用内核**。Docker 容器共享宿主机的 Linux 内核。有一类攻击（container escape）利用内核漏洞从容器内逃逸到宿主机，进而访问其他容器的内存。普通 Web 服务受这类攻击的影响有限——进程间没有理由互相访问内存。但 AI agent 不同：agent 的推理过程可以被 prompt injection 操控，让模型主动尝试"逃出"当前 session，读取其他用户的上下文数据。microVM 给每个 session 一个独立的 Linux 内核，container escape 无从施展。

**memory sanitization 是硬性要求**。session 结束后，AgentCore 官方文档明确说明会"终止整个 microVM 并清零内存"（memory is sanitized）。对话内容、工具调用的中间结果、可能被泄漏的 API key——这些数据在 session 结束后物理层面就消失了。Docker 容器销毁只删文件系统，内存里的内容在被覆写之前仍然存在。在医疗（HIPAA）和金融（SOC 2）合规场景里，这个差异从"最佳实践"变成"法规要求"。

**非确定性 AI 过程的不可预测性**。AWS 官方文档的原话是："在非确定性 AI 过程中实现确定性安全"。容器安全的传统假设是"应用代码是可信的，隔离只是纵深防御"。agent 的代码本身就可以被 LLM 的输出影响（工具调用参数、代码执行内容），这个假设不成立。microVM 的隔离级别足以对抗被 prompt injection 操控的 agent 代码。

这个设计选择的代价是启动时间和成本。microVM 的冷启动延迟高于 Docker 容器（每个 session 需要独立启动内核），且每个 microVM 比容器消耗更多宿主机资源。对于交互频繁、要求亚秒响应的场景，这个开销不可忽视。对于需要处理敏感数据或多租户场景的生产 agent，这个开销通常是值得的。

---

### AgentCore vs 自建 EKS：迁移路径对比

对于已有 EKS 运维能力的团队，迁移的实际工作量主要集中在运维层的替换，而不是业务逻辑的重写。下表按"改不改代码"维度拆分：

**业务逻辑（不改）**：agent 的 Python 代码、工具定义（`@tool` 装饰器）、system prompt、Strands/LangGraph 框架。

**运维层（需替换）**：

| 自建 EKS 写法 | AgentCore 替代 |
|---|---|
| `kubectl apply` 部署 Pod | `agentcore deploy` 自动构建推送 ECR + 创建 Runtime |
| `redis://...` session 状态存储 | Runtime 自动管理 microVM 内 session 上下文 |
| 手写向量 DB（pgvector/FAISS）连接 | Memory API（`SEMANTIC`/`SUMMARIZATION` 策略） |
| `client_id/client_secret` 写进 Secret | Identity outbound auth 管理第三方凭证 |
| Prometheus + Grafana 可观测栈 | Observability 自动输出 OTEL → CloudWatch |

迁移时最常见的摩擦来自 x86 依赖——AgentCore Runtime 是 ARM64（AWS Graviton），部分 C 扩展库（如 `ta-lib`、`faiss-cpu`）需要重新编译。提前用 `docker buildx build --platform linux/arm64` 验证是否能成功构建，可以避免部署阶段的意外。

---

## 三道思考题

1. 本章的映射表里，"Safety / 可控性"支柱在 AgentCore 里有三层防御（Identity + microVM + Policy）。你认为这三层里，哪一层在实际工程里最容易被配置错误？错误配置的后果是什么？

2. AgentCore Memory 的长期记忆使用 SEMANTIC 策略（从对话里提取事实）。第 8 章提到人类记忆有一个 consolidation 过程——不只是存储事实，而是提炼原则。SEMANTIC 策略能做到"原则提炼"吗？它缺少什么？

3. 假设你要把 Lena v2.6（第 26 章的 Strands 版本）部署到 AgentCore，你会选择加入 Memory 服务、不加入 Identity 服务。给出你的理由，以及什么样的需求变化会让你改变这个决定。

---

[^1]: Amazon Bedrock AgentCore 产品主页, https://aws.amazon.com/cn/bedrock/agentcore/
[^2]: Amazon Bedrock AgentCore Runtime 工作原理（含 session 生命周期、8 小时/15 分钟参数）, https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html
[^3]: Amazon Bedrock AgentCore Memory 文档, https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html
[^4]: Amazon Bedrock AgentCore Gateway 文档, https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html
[^5]: Amazon Bedrock AgentCore 定价（含 $0.0895/vCPU-hour、$0.00945/GB-hour、I/O 等待不计费细节）, https://aws.amazon.com/bedrock/agentcore/pricing/
[^6]: AgentCore CLI 快速入门（含 npm 包名 `@aws/agentcore`、`agentcore create/dev/deploy` 命令语法）, https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html
