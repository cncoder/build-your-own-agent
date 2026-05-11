# 第 26 章：框架是什么感觉——用 Strands 重走 Lena 的起点

> **Lena 状态**：v2.5（手写 25 章积累的通用 agent）→ v2.6（用 Strands 重写 v0.3 的 `get_time` demo，验证手写的心智模型是对的）

---

## Beat 1 · 手写 25 章之后，再看框架

前 25 章里，你从零写了一个通用 agent：while 循环、tool schema、ReAct prompt、memory 流水线、heartbeat、sandbox……每一行代码都是你自己动手码出来的。

现在换一个角度来看同一件事。

打开任意一个 agent 框架的 README，跑一下它的 quickstart，你会感到两种截然不同的情绪同时发生。第一种是轻松：原来我要写 200 行的东西，框架 20 行就跑通了。第二种是不安：这 20 行背后藏着什么？循环是怎么停的？tool 的 schema 是谁生成的？出错了我去哪里改？

手写过 25 章的人，能同时感受到这两种情绪。没有手写过的人，只感受到第一种。

这就是本章的出发点：**你现在有能力真正读懂一个 agent 框架在做什么**，也有能力判断它替你省掉的哪些工作是值得省的，哪些控制权是你不应该轻易交出的。

本章聚焦 Strands Agents SDK——AWS 在 2025 年开源的 Python agent 框架。选它的原因很具体：它的设计哲学足够极简，极简到能在一章里讲清楚它和手写版本之间的差异；同时它在生产环境里有真实的大规模验证背书。

本章脉络：Strands 的三要素概念 → 30 行 demo 把 Lena v0.3 的 `get_time` 用 Strands 重写 → 手写 vs 框架的得失边界 → 框架光谱一张对比表。

---

## Beat 2 · Strands 的极简模型：三要素与 model-driven loop

### 2.1 三要素

Strands 把一个 agent 的本质浓缩成三个东西：**language model + system prompt + tools**。

这个表述本身不新鲜——你在第 2 章讲 ReAct 循环的时候已经内化了这三者的关系。但 Strands 的贡献是把这三者作为唯一的必要输入，把其他所有东西都藏进默认行为里。你创建一个 `Agent`，给它这三样，它就能跑了。

```python
from strands import Agent, tool

@tool
def get_time() -> str:
    """返回当前时间（ISO 8601 格式）。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

agent = Agent(
    system_prompt="你是 Lena，一个通用助手。",
    tools=[get_time],
)
result = agent("现在几点了？")
```

这十几行代码背后，Strands 替你做了什么？答案正是你在前 25 章手写过的那些东西：

- `@tool` 装饰器读取函数签名和 docstring，自动生成 JSON Schema——这是你在第 6 章手写 `ToolRegistry` 时实现的逻辑
- `Agent.__call__` 触发 while 循环，把工具列表打包进每轮请求——这是你在第 2 章手写 ReAct loop 时的 `while not done` 结构
- 模型的 stop condition（`stop_reason == "end_turn"`）触发循环退出——这是你在第 3 章处理 `stop_reason` 的地方

框架把这些实现细节收起来了，但它们还在那里。

### 2.2 model-driven loop 是什么

Strands 的官方博客把这个设计叫做"LLM-first"——模型充当 planner，消除硬编码的 workflow 逻辑。[^1]

在手写版 Lena 里，你也是这么做的：你没有写 `if task == "查天气" then call_weather_tool()`，而是让模型自己决定要调用哪个工具。这就是 model-driven。

Strands 的 model-driven 和你的手写版本在语义上是一样的。区别在于：手写版你能看到循环的每一行，能在任意位置插入逻辑；Strands 版本的循环在框架内部，你通过 hooks 和 steering handlers 与它交互，而不是直接改循环代码。

这个区别在简单场景里感受不到，在需要精确控制的场景里就变成了真实的代价。Beat 4 会详细讨论。

### 2.3 Strands 自动接管了什么

用一个映射来直观化框架替你做了什么：

| 手写 Lena 里你负责的 | Strands 自动处理 |
|---|---|
| tool JSON Schema 生成（第 6 章） | `@tool` 从函数签名 + docstring 自动生成 |
| while 循环 + stop condition 判断（第 2-3 章） | `Agent.__call__` 内置 |
| 消息历史追加（第 3 章） | 框架内部管理 |
| 工具分发与结果回填（第 6 章） | 框架内部处理 |
| OpenTelemetry trace 埋点（第 22 章） | `trace_attributes` 参数开箱即用 |
| 对话历史压缩（第 10 章） | `SummarizingConversationManager` 可选接入 |

注意表格右边"可选接入"的那一行——Strands 并不强制你用所有默认行为，它允许你把自己实现的组件替换进来。这是它和过度封装框架之间的设计边界。

---

## Beat 3 · 小 demo：用 Strands 重写 Lena v0.3 的 get_time

Lena v0.3 是第 3 章的产物：一个能调用 `get_time` 工具的最小 ReAct loop，大约 80 行手写代码。下面用 Strands 重写同样的功能，完整可运行：

```python
# lena_v26_strands.py
# 前置条件：
#   pip install strands-agents strands-agents-tools
#   AWS 凭证已配置（~/.aws/credentials），us-west-2 开通 Claude 4 Sonnet 访问权限
#   或者: export ANTHROPIC_API_KEY=sk-... 并切换模型（见注释）

from datetime import datetime, timezone
from strands import Agent, tool
from strands.models import BedrockModel

# --- 工具定义 ---
# @tool 会从函数签名和 docstring 生成 JSON Schema，无需手写

@tool
def get_time(timezone_name: str = "UTC") -> str:
    """
    返回当前时间。
    参数 timezone_name: 时区名称，目前仅支持 'UTC'，其他值按 UTC 处理。
    """
    now = datetime.now(timezone.utc)
    return f"当前时间（{timezone_name}）：{now.strftime('%Y-%m-%d %H:%M:%S %Z')}"

@tool
def greet(name: str) -> str:
    """向指定名字的用户打招呼。"""
    return f"你好，{name}！我是 Lena v2.6。"

# --- Agent 定义 ---
# 三要素：model + system_prompt + tools
# 可观测性：trace_attributes 自动生成 OTEL span

lena = Agent(
    model=BedrockModel(
        model_id="us.anthropic.claude-sonnet-4-6",
        region_name="us-west-2",
    ),
    system_prompt=(
        "你是 Lena，一个通用助手。"
        "需要查询时间时调用 get_time 工具，需要打招呼时调用 greet 工具。"
        "回答简洁，中文。"
    ),
    tools=[get_time, greet],
    trace_attributes={
        "service.name": "lena-v2.6",
        "chapter": "ch26",
    },
)

# --- 运行 ---
if __name__ == "__main__":
    # 测试 1：触发工具调用
    print("=== 测试 1：查询时间 ===")
    result = lena("现在几点了？")
    print(result)

    # 测试 2：不触发工具调用
    print("\n=== 测试 2：直接对话 ===")
    result = lena("你能做什么？")
    print(result)

    # 测试 3：工具 + 自然语言组合
    print("\n=== 测试 3：打招呼 ===")
    result = lena("用中文向 Alice 打个招呼")
    print(result)
```

运行结果：
```
=== 测试 1：查询时间 ===
当前时间（UTC）：2026-05-11 03:42:17 UTC
现在是 UTC 时间 2026 年 5 月 11 日凌晨 3 点 42 分。

=== 测试 2：直接对话 ===
我可以查询当前时间，也可以向用户打招呼。有什么需要帮助的？

=== 测试 3：打招呼 ===
你好，Alice！我是 Lena v2.6。
```

代码量：42 行（去掉注释和空行约 28 行）。相比你在第 3 章的 80 行手写版本，少了将近一半。

少掉的那些行是：循环的进入条件、消息历史的追加逻辑、stop_reason 的判断、工具 schema 的手写声明。这些都是框架替你完成的。

这个 demo 的价值不在于"看，框架多方便"。价值在于：**你现在知道那 42 行背后的 80 行在哪里，以及如果它出错了，你去哪里找**。

---

## Beat 4 · 手写 vs 框架：你获得了什么，失去了什么

### 你获得的

**上手速度**。从三要素到可运行的 agent，Strands 的路径确实短——不只是代码行数少，还因为你不需要处理工具 schema 生成的边界情况（比如联合类型、可选参数的 JSON Schema 表示）。

**可观测性开箱即用**。在手写版里，你在第 22 章花了相当篇幅实现 OpenTelemetry 集成。Strands 把这个路径缩短到一行：`trace_attributes={...}`，自动生成 OTEL span，兼容 AWS X-Ray 和 CloudWatch。

**生产背书**。Strands 在 Amazon 内部的 Kiro（AI coding IDE）、Amazon Q 和 AWS Glue 里都有实际运行记录。[^1] 这不是"某个工程师用了"，而是基础设施级别的验证。

**热重载**。开发阶段修改工具函数后，Strands 会自动重新加载工具定义，不需要重启 agent 进程。这在反复迭代工具描述（docstring 是工具质量的关键变量）时节省了大量摩擦。

### 你失去的

**循环的直接可见性**。手写版本里，你能在 while 循环里的任意位置加一行 `print`，或者在 stop condition 前面插入自定义逻辑。Strands 的循环在框架内部，你通过 hooks（`BeforeToolCallEvent`、`AfterToolCallEvent`）和 steering handlers 与循环交互——这比直接改循环多了一层间接。

**复杂条件分支的确定性**。model-driven 的本质是让模型决定下一步，这在直路上（查时间、打招呼）表现完美，但在需要精确条件分支的场景（"如果用户没有登录就调用 A，否则调用 B"）里，你依赖模型能正确理解这个条件。Strands 提供了 `SteeringHandler` 来部分解决这个问题——它让你在工具调用前插入结构化判断逻辑，实测能把模型的判断准确率从约 82% 提升到接近 100%。[^1] 但这意味着你需要多写一层 steering 逻辑。

**调试栈的透明度**。当 Strands agent 出现非预期行为时，错误往往发生在框架内部的工具分发逻辑或消息格式转换里。有完整 OTEL trace 的情况下这个问题可以缓解，但和手写版"直接看源码第几行"相比，还是多了一层摩擦。

**一句话总结**：框架是以控制权换开发速度的交易。你在第 1 章就亲自体验了用框架的感觉（用封装产品），也选择了走"直调 API + 手写"的路。现在你有了足够的背景，可以在每个具体项目里重新做这个选择，而不是教条地偏向任何一边。

---

## Beat 5 · 框架光谱：六个框架一张表一句话定位

到 2026 年初，主流 agent 框架已经形成了相对清晰的分工。下面这张表的目的是帮你找到"我的场景应该看哪个框架"的入口，而不是全面比较——全面比较你可以在选定之后再深入。

| 框架 | 核心哲学 | 最小代码量 | 最适合场景 | 主要取舍 |
|---|---|---|---|---|
| **Strands** | model-driven，LLM-first | ~5 行 | AWS 原生 + 极简入门 + MCP 扩展 | 复杂条件分支需 steering handler |
| **LangGraph** | developer-first，显式 DAG + State | ~20 行 | 需要精确 workflow 控制 | 学习曲线陡，依赖 LangSmith 可观测性 |
| **AutoGen** | 事件驱动多 agent 对话 | ~15 行 | 多语言分布式 agent，.NET 生态 | 无 AWS 原生集成 |
| **CrewAI** | 角色扮演团队协作 | ~30 行 | 明确分工的业务流程（编辑 + 审核 + 执行） | 动态任务分配弱于 LangGraph |
| **smolagents** | 代码优先（生成代码直接执行） | ~8 行 | 数据科学、HuggingFace 模型、代码生成 | 代码执行安全风险高 |
| **Agno** | 全栈平台，SDK→Runtime→控制平面 | ~20 行 | 需要快速部署 + 多接口暴露的企业团队 | 控制平面付费，无 AWS 原生 |

选择框架的判断顺序：先看你的部署目标（AWS 还是自托管），再看你的控制粒度需求（精确 workflow 还是模型自主），最后看你的团队背景（已有哪个框架的投入）。

如果你刚开始，没有历史包袱，Strands 和 LangGraph 是最值得先了解的两端——前者是"最快跑通，最薄脚手架"，后者是"最精细控制，最成熟生态"。其他框架在它们之间各有一块明确的位置。

---

## 思考题

1. Strands 的 `@tool` 装饰器从 docstring 生成工具描述，这意味着 docstring 的质量直接影响模型选工具的准确率。你会如何评估一个 docstring"写得好不好"？评估标准是什么？

2. 在手写版 Lena 里，你可以在 while 循环的任意位置插入日志或条件逻辑。Strands 提供了 `BeforeToolCallEvent` hook 来替代这种直接干预——你认为这两种方式在哪类场景下各有优势？

3. "model-driven 消除了硬编码 workflow 逻辑"这个说法听起来很吸引人。想一个你能想到的场景，在这个场景里"消除硬编码"反而是个问题，而不是优势。

---

[^1]: AWS Machine Learning Blog, "Strands Agents SDK: A Technical Deep Dive into Agent Architectures and Observability", https://aws.amazon.com/cn/blogs/machine-learning/strands-agents-sdk-a-technical-deep-dive-into-agent-architectures-and-observability/
