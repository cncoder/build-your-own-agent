# 第 26 章：框架是什么感觉——用 Strands 重走 Lena 的起点

> **Lena 状态**：v2.5（手写 25 章积累的通用 agent）→ v2.6（用 Strands 重写 v0.3 的 `get_time` demo，验证手写的心智模型是对的，并扩展到多 agent 图拓扑）

---

## Beat 1 · 手写 25 章之后，再看框架

前 25 章里，你从零写了一个通用 agent：while 循环、tool schema、ReAct prompt、memory 流水线、heartbeat、sandbox……每一行代码都是你自己动手码出来的。

现在换一个角度来看同一件事。

打开任意一个 agent 框架的 README，跑一下它的 quickstart，你会感到两种截然不同的情绪同时发生。第一种是轻松：原来要写 200 行的东西，框架 20 行就跑通了。第二种是不安：这 20 行背后藏着什么？循环是怎么停的？tool 的 schema 是谁生成的？出错了去哪里改？手写过 25 章的人能同时感受到这两种情绪，因为你知道那 20 行之外还藏着什么。这就是本章的出发点：**你现在有能力真正读懂一个 agent 框架在做什么**，也有能力判断它替你省掉的哪些工作是值得省的，哪些控制权是你不应该轻易交出的。

本章聚焦 Strands Agents SDK——AWS 在 2025 年开源的 Python agent 框架（GitHub: `strands-agents/sdk-python`，v1.39.0，Python 3.10+）。选它的原因很具体：它的设计哲学足够极简，极简到能在一章里讲清楚它和手写版本之间的差异；同时它在生产环境里有真实的大规模验证背书（Kiro、Amazon Q、AWS Glue、VPC Reachability Analyzer 等 AWS 内部服务）。

本章核心问题：Strands 替你处理了手写 25 章里的哪些工作，代价是什么，以及当框架出错时你去哪里找。

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

- `@tool` 装饰器内部调用 Pydantic 的 `create_model()` 动态生成 JSON Schema：它通过 `inspect.signature()` 读取参数名和默认值，通过 `get_type_hints()` 读取类型注解，支持 `str`、`int`、`float`、`bool`、`Optional[T]`、嵌套 `BaseModel` 以及 `Annotated[T, "纯字符串描述"]` 等 Python 类型[^10]（注意：`Annotated` 的第二个参数必须是纯字符串，`Annotated[T, pydantic.Field(...)]` 会抛出 `NotImplementedError`[^10]）——这是你在第 6 章手写 `ToolRegistry` 时实现的逻辑
- `Agent.__call__` 触发 event loop cycle，把工具列表打包进每轮请求——这是你在第 2 章手写 ReAct loop 时的 `while not done` 结构
- 模型的 stop condition 以 `stop_reason` 字段标识（`stop_reason` 是模型 API 响应里说明"为什么停止生成"的字段：`"end_turn"` = 模型认为任务完成主动停止，`"tool_use"` = 模型请求调用工具后等待结果，`"max_tokens"` = 达到最大输出长度）[^12]——这是你在第 3 章处理 `stop_reason` 的地方

框架把这些实现细节收起来了，但它们还在那里。

### 2.2 model-driven loop 是什么

Strands 的官方文档把这个设计叫做"LLM-first"——模型充当 planner，消除硬编码的 workflow 逻辑。[^1]

在手写版 Lena 里，你也是这么做的：你没有写 `if task == "查天气" then call_weather_tool()`，而是让模型自己决定要调用哪个工具。这就是 model-driven。

Strands 的 agent event loop 在每一轮做三件事：读取当前对话 → 规划下一步动作 → 可能调用工具。重复这个循环，直到模型判断任务完成为止。这个循环的停止条件不是硬编码的步骤数，而是模型自己的 `"end_turn"` 信号——这正是第 2 章 ReAct（Reasoning + Acting 交替循环）模式的框架化实现：模型推理（Reasoning）选择工具，执行动作（Acting）得到结果，再推理再行动，直到不需要更多工具调用为止。

当 API 调用出错时，event loop 有内置的指数退避重试机制：源码（`src/strands/event_loop/event_loop.py`）中定义了 `MAX_ATTEMPTS = 6`、`INITIAL_DELAY = 4`（秒）、`MAX_DELAY = 240`（秒，即 4 分钟），共 6 次重试机会，初始等待 4 秒，最长等待 4 分钟，覆盖了绝大多数网络抖动和临时限流场景。[^5]

Strands 的 model-driven 和你的手写版本在语义上是一样的。区别在于：手写版你能看到循环的每一行，能在任意位置插入逻辑；Strands 版本的循环在框架内部，你通过两种机制与它交互：

- **`callback_handler`**：一个普通 Python 函数，接受 `**kwargs` 参数，在 agent loop 的每个细粒度事件发生时被调用。常见 kwargs 键名：`data`（流式文本 token）、`current_tool_use`（工具调用流，含 `toolUseId`/`name`）、`force_stop`（循环强制终止）、`init_event_loop`（循环初始化），适合处理实时流式输出。[^8]
- **`HookProvider`**：一个协议类（Protocol），通过实现 `register_hooks(registry)` 方法注册对粗粒度生命周期事件（`BeforeInvocationEvent`、`AfterInvocationEvent`、`BeforeToolCallEvent`、`AfterToolCallEvent`、`BeforeModelCallEvent`、`AfterModelCallEvent`、`MessageAddedEvent`、`AgentInitializedEvent`）的回调，适合审计、拦截和统计。

两者都不需要改循环代码，只是切入点不同：`callback_handler` 是 token 粒度，`HookProvider` 是调用粒度。

这个区别在简单场景里感受不到，在需要精确控制的场景里就变成了真实的代价。Beat 4 会详细讨论。

### 2.3 Strands 自动接管了什么

用一个映射来直观化框架替你做了什么：

| 手写 Lena 里你负责的 | Strands 自动处理 | 默认实现细节 |
|---|---|---|
| tool JSON Schema 生成（第 6 章） | `@tool` 从函数签名 + docstring 自动生成 | Pydantic `create_model()` + `model_json_schema()` |
| while 循环 + stop condition 判断（第 2-3 章） | `Agent.__call__` 内置 event loop cycle | 停止条件：`end_turn` / `max_tokens` / `cancelled` |
| 消息历史管理（第 3 章） | `SlidingWindowConversationManager` | 默认窗口 40 条消息 |
| 工具分发与结果回填（第 6 章） | `ConcurrentToolExecutor` | 默认并发执行多个工具 |
| OpenTelemetry trace 埋点（第 22 章） | `trace_attributes` 参数 + OTEL span 开箱即用 | 记录 LLM 调用、工具调用、token 消耗、时延 |
| 对话历史压缩（第 10 章） | `SummarizingConversationManager` 可选接入 | 超 70% context 触发，默认保留最近 10 条 |
| 流式响应处理 | `callback_handler` 或 `stream_async()` | token 粒度回调 |
| 多 agent 路由 | `GraphBuilder` / `Swarm` / agent-as-tool 内置 | 四种拓扑（Beat 5 详述） |

表格中的几个组件值得单独解释：

**`SlidingWindowConversationManager`**：Strands 的默认对话历史管理器（**注意：不是** `SummarizingConversationManager`，后者是可选替换）。默认保留最近 40 条消息（`window_size=40`），超出时滑动截断旧消息。工具调用对（`ToolUse` + `ToolResult`）不会被拆分截断。特殊值 `window_size=0` 表示清空所有历史，与 TypeScript SDK 行为一致。

**`SummarizingConversationManager`**：可选替换 `SlidingWindowConversationManager` 的压缩方案。默认 `summary_ratio=0.3`（压缩最旧的 30% 消息），`preserve_recent_messages=10`（最近 10 条永不压缩），触发时机：context window 使用超过 70%（`ContextWindowOverflowException`），或主动探测开启时到达阈值。

**`GraphBuilder`**：Strands 内置的多 agent 有向图构建器。你把每个 agent 作为节点（node），把执行依赖关系作为边（edge）添加进去，`GraphBuilder.build()` 返回一个可执行的图对象。适用于步骤之间有严格先后依赖的场景（详见 Beat 5.1 拓扑 3）。

**`ConcurrentToolExecutor`**：Strands 的默认工具执行器，当模型在一次响应中请求多个工具调用时，它们会被并发执行，而不是串行等待。这对多工具组合查询的响应延迟有显著影响。

注意表格右边"可选接入"的那一行——Strands 并不强制你用所有默认行为，它允许你把自己实现的组件替换进来。这是它和过度封装框架之间的设计边界。

---

## Beat 3 · 小 demo：用 Strands 重写 Lena v0.3 的 get_time

Lena v0.3 是第 3 章的产物：一个能调用 `get_time` 工具的最小 ReAct loop，大约 80 行手写代码。下面用 Strands 重写同样的功能，完整可运行：

```python
# lena_v26_strands.py
# 前置条件：
#   pip install strands-agents strands-agents-tools
#   AWS 凭证已配置（~/.aws/credentials），us-west-2 开通 Claude Sonnet 访问权限
#   或者: export ANTHROPIC_API_KEY=sk-... 并切换 AnthropicModel（见注释）

from datetime import datetime, timezone
from strands import Agent, tool
from strands.models import BedrockModel

# --- 工具定义 ---
# @tool 会从函数签名和 docstring 生成 JSON Schema，无需手写
# 内部通过 Pydantic create_model() 动态生成；注意：
# - 参数无默认值 → 必填字段（Pydantic required）
# - 参数有默认值 → 可选字段
# - 参数名 self / cls / agent 会被自动排除不生成进 schema
#
# 关于 model_id 格式：
# Bedrock 的跨区域推理配置文件 ID（Cross-Region Inference Profile）格式为 "us.<provider>.<model>"
# 前缀 "us." 表示在 us-east-1/us-west-2 之间自动路由，不是模型版本号的一部分
# 普通模型 ID 格式为 "anthropic.claude-3-5-sonnet-20241022-v2:0"（不带 "us." 前缀）
# 实际可用的 model_id 请从 AWS 控制台 → Bedrock → Cross-region inference 查看最新列表

@tool
def get_time(timezone_name: str = "UTC") -> str:
    """
    返回当前时间。
    参数 timezone_name: 时区名称，目前仅支持 'UTC'，其他值按 UTC 处理。
    返回格式：YYYY-MM-DD HH:MM:SS TZ
    """
    now = datetime.now(timezone.utc)
    return f"当前时间（{timezone_name}）：{now.strftime('%Y-%m-%d %H:%M:%S %Z')}"

@tool
def greet(name: str) -> str:
    """向指定名字的用户打招呼。参数 name: 用户姓名（字符串）。"""
    return f"你好，{name}！我是 Lena v2.6。"

# --- 流式事件处理 ---
# callback_handler 在每个事件发生时被调用，包括流式 token 和工具调用通知
tool_use_ids: list[str] = []
def callback_handler(**kwargs):
    if "data" in kwargs:
        print(kwargs["data"], end="", flush=True)
    elif "current_tool_use" in kwargs:
        tool = kwargs["current_tool_use"]
        if tool.get("toolUseId") not in tool_use_ids:
            print(f"\n[调用工具: {tool.get('name')}]")
            tool_use_ids.append(tool["toolUseId"])

# --- Agent 定义 ---
# 三要素：model + system_prompt + tools
# trace_attributes 自动生成 OTEL span，兼容 AWS X-Ray 和 CloudWatch

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
    callback_handler=callback_handler,
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

    # 测试 2：不触发工具调用
    print("\n=== 测试 2：直接对话 ===")
    result = lena("你能做什么？")

    # 测试 3：工具 + 自然语言组合
    print("\n=== 测试 3：打招呼 ===")
    result = lena("用中文向 Alice 打个招呼")
```

运行结果：
```
=== 测试 1：查询时间 ===
[调用工具: get_time]
当前时间（UTC）：2026-05-11 03:42:17 UTC
现在是 UTC 时间 2026 年 5 月 11 日凌晨 3 点 42 分。

=== 测试 2：直接对话 ===
我可以查询当前时间，也可以向用户打招呼。有什么需要帮助的？

=== 测试 3：打招呼 ===
[调用工具: greet]
你好，Alice！我是 Lena v2.6。
```

代码量：含注释约 60 行，去掉注释和空行约 35 行纯逻辑代码。相比你在第 3 章的 80 行手写版本，核心逻辑少了大约 44%。

少掉的那些行分别是：循环的进入条件（约 8 行）、消息历史的追加逻辑（约 10 行）、`stop_reason` 的分支判断（约 6 行）、工具 schema 的手写声明（约 20 行）。这些都是框架替你完成的。

这个 demo 的价值不在于"看，框架多方便"。价值在于：**你现在知道那些代码背后框架替你藏起来的 44 行逻辑在哪里，以及如果它出错了，你去哪里找**。

demo 跑通了，接下来的问题必然是：那些被框架藏起来的代码，对你意味着什么？什么时候它是省力，什么时候它是负担？

---

## Beat 4 · 手写 vs 框架：你获得了什么，失去了什么

### 你获得的

**上手速度**。从三要素到可运行的 agent，Strands 的路径确实短——不只是代码行数少，还因为你不需要处理工具 schema 生成的边界情况（比如联合类型、可选参数的 JSON Schema 表示；唯一需要注意的是 `Annotated[T, pydantic.Field(...)]` 不被支持，必须用 `Annotated[T, "字符串描述"]` 替代）。

**可观测性开箱即用**。在手写版里，你在第 22 章花了相当篇幅实现 OpenTelemetry（OTEL）集成——OTEL 是业界标准的可观测性框架：每个操作生成一个 span（包含操作名称、开始/结束时间戳、输入/输出数据等属性），多个 span 按调用顺序串成 trace，开发者用 trace 诊断"agent 为什么做了那个决定"，运维用它统计成本和延迟。Strands 把这个路径缩短到一行：`trace_attributes={...}`，自动为每个 LLM 调用和工具调用生成 OTEL span，span 属性包括：提示词内容、token 消耗（prompt tokens + completion tokens 分别计）、工具名称、工具输入/输出、执行时延（time-to-first-byte + 总完成时间），兼容 AWS X-Ray、Amazon CloudWatch 和 Jaeger。[^1]

**生产背书**。Strands 在 Amazon 内部的 Kiro（AI coding IDE）、Amazon Q、AWS Glue 和 VPC Reachability Analyzer 里都有实际运行记录。[^1] 这不是"某个工程师用了"，而是基础设施级别的验证。此外，Amazon Bedrock AgentCore（Strands 的托管运行时）支持最长 **8 小时**的连续任务执行（2025 年 7 月公开预览）。[^1]

**工具生态**。`strands-agents-tools` 包提供了 52 个开箱即用的工具，覆盖文件读写（`file_read`、`file_write`）、Shell 执行（`shell`）、HTTP 请求（`http_request`）、网页搜索（`tavily_search`、`exa_search`）、AWS 服务（`use_aws`、`retrieve`）、浏览器自动化（`browser`）、代码执行（`python_repl`、`code_interpreter`）等场景，直接 `from strands_tools import shell` 即可使用。

**多模型覆盖**。Strands 内置 14 种模型提供商：Amazon Bedrock、Anthropic、Google Gemini、Cohere、LiteLLM、llama.cpp、LlamaAPI、MistralAI、Ollama、OpenAI、OpenAI Responses API、SageMaker、Writer，以及可自定义的 Custom 接口。切换模型只需换 `model=` 参数，agent 逻辑无需改动。

**热重载**。开发阶段把工具文件放在 `./tools/` 目录并设置 `Agent(..., load_tools_from_directory=True)`，修改工具函数后 Strands 自动重新加载工具定义，不需要重启 agent 进程。[^13]

### 你失去的

**循环的直接可见性**。手写版本里，你能在 while 循环里的任意位置加一行 `print`，或者在 stop condition 前面插入自定义逻辑。Strands 的循环在框架内部（`src/strands/event_loop/event_loop.py` 的 `event_loop_cycle` 函数），你通过 `callback_handler` 函数和 `HookProvider` 类与循环交互——这比直接改循环多了一层间接。`callback_handler` 接收事件 kwargs：`data`（流式文本 token）、`current_tool_use`（工具调用信息）、`init_event_loop`（循环初始化）、`force_stop`（强制停止）[^8]；`HookProvider` 则允许你在 8 种生命周期节点（`BeforeInvocationEvent`、`AfterInvocationEvent`、`BeforeToolCallEvent`、`AfterToolCallEvent`、`BeforeModelCallEvent`、`AfterModelCallEvent`、`MessageAddedEvent`、`AgentInitializedEvent`）注册回调。

**复杂条件分支的确定性**。model-driven 的本质是让模型决定下一步，这在直路上（查时间、打招呼）表现完美，但在需要精确条件分支的场景（"如果用户没有登录就调用 A，否则调用 B"）里，你依赖模型能正确理解这个条件。对于需要强制执行的业务规则（比如"仓位不超过总资金的 2%"），推荐的做法是把规则写进工具的实现代码里，而不是写进 system prompt——代码是确定性的，prompt 是概率性的。

**调试栈的透明度**。当 Strands agent 出现非预期行为时，错误往往发生在框架内部的工具分发逻辑或消息格式转换里。有完整 OTEL trace 的情况下这个问题可以缓解，但和手写版"直接看源码第几行"相比，还是多了一层摩擦。特别是 `@tool` 装饰器中 `Annotated[T, pydantic.Field(...)]` 的用法会抛出 `NotImplementedError`（原因：`@tool` 的 schema 生成只支持纯字符串作为 `Annotated` 的第二参数），这类错误只有在运行时才暴露，而非静态检查时。

**一句话总结**：框架是以控制权换开发速度的交易。你在第 1 章就亲自体验了用框架的感觉（用封装产品），也选择了走"直调 API + 手写"的路。现在你有了足够的背景，可以在每个具体项目里重新做这个选择，而不是教条地偏向任何一边。

多 agent 协作和生命周期控制是 Strands 区别于极简框架的地方——它内置了四种拓扑和 8 种生命周期 hook 事件，覆盖了大多数生产场景。

---

## Beat 5 · 多 agent 拓扑与 Hooks：框架扩展到生产的两条路

### 5.1 Strands 的四种多 agent 拓扑

单 agent 能解决大多数问题，但有些任务天生适合多 agent 协作：并行搜索多个知识源、把"编辑"和"审核"的职责分离、让专家 agent 处理超出通才 agent 能力边界的任务。

Strands 内置了四种多 agent 拓扑：

**拓扑 1：Agent as Tool（最简单）**

把一个 agent 包装成另一个 agent 的工具。这是最低摩擦的多 agent 入口：

```python
from strands import Agent, tool
from strands_tools import retrieve, http_request

# 专家 agent 被包装成工具
@tool
def research_assistant(query: str) -> str:
    """调用研究专家 agent，对给定查询进行深度调研。返回调研报告字符串。"""
    research_agent = Agent(
        system_prompt="你是调研专家，擅长信息检索和事实核查。",
        tools=[retrieve, http_request],
    )
    return str(research_agent(query))

# 编排 agent 把 research_assistant 当工具用
orchestrator = Agent(
    system_prompt="你是项目负责人，需要时调用研究专家完成调研任务。",
    tools=[research_assistant],
)
result = orchestrator("调研一下 2025 年 AI agent 框架的主要趋势")
```

这种模式的核心优势：orchestrator 和 research_assistant 的系统提示完全解耦，可以独立调整；research_assistant 对 orchestrator 来说就是一个黑盒工具，接口稳定。

**拓扑 2：Supervisor（中等复杂度）**

主 agent 接收任务，动态决定把哪部分子任务派给哪个专家 agent：

```python
from strands import Agent, tool
from strands.models import BedrockModel

MODEL = BedrockModel(model_id="us.anthropic.claude-sonnet-4-6", region_name="us-west-2")

@tool
def math_assistant(problem: str) -> str:
    """调用数学专家 agent 解决计算问题。参数 problem: 数学问题描述。"""
    agent = Agent(model=MODEL, system_prompt="你是数学专家，精通代数、微积分、统计学。")
    return str(agent(problem))

@tool
def code_assistant(task: str) -> str:
    """调用代码专家 agent 编写或调试代码。参数 task: 代码任务描述。"""
    from strands_tools import shell
    agent = Agent(model=MODEL, system_prompt="你是编程专家，熟悉 Python/TypeScript。", tools=[shell])
    return str(agent(task))

supervisor = Agent(
    model=MODEL,
    system_prompt=(
        "你是任务调度员。遇到数学问题调用 math_assistant，"
        "遇到代码问题调用 code_assistant，其他问题直接回答。"
    ),
    tools=[math_assistant, code_assistant],
)
```

**拓扑 3：Graph（最大控制权）**

当任务的执行顺序需要显式定义时，`GraphBuilder` 提供有向图拓扑。节点是 agent，边是执行依赖关系：

```python
import asyncio
from strands import Agent
from strands.multiagent import GraphBuilder

# 三个专家 agent
researcher = Agent(
    name="researcher",
    system_prompt="你是调研专家，负责信息收集。",
)
analyst = Agent(
    name="analyst",
    system_prompt="你是分析专家，负责提炼调研结论。",
)
writer = Agent(
    name="writer",
    system_prompt="你是写作专家，负责把结论写成报告。",
)

# 构建有向图：researcher → analyst → writer
builder = GraphBuilder()
builder.add_node(researcher, "research")
builder.add_node(analyst, "analysis")
builder.add_node(writer, "writing")
builder.add_edge("research", "analysis")
builder.add_edge("analysis", "writing")
graph = builder.build()

# 异步执行
async def main():
    result = await graph.invoke_async("研究 AI agent 框架趋势并写一篇技术报告")
    print(result)

asyncio.run(main())
```

**拓扑 4：Swarm（最大并行度）**

当任务可以被分拆成多个独立子任务并行处理时，`Swarm` 把多个 agent 组成协作群：

```python
import asyncio
from strands import Agent
from strands.multiagent import GraphBuilder, Swarm

# 三个并行调研 agent
research_agents = [
    Agent(name="medical_researcher", system_prompt="你是医疗领域研究专家。"),
    Agent(name="tech_researcher", system_prompt="你是技术领域研究专家。"),
    Agent(name="economic_researcher", system_prompt="你是经济领域研究专家。"),
]
research_swarm = Swarm(research_agents)  # 并行执行；Swarm(nodes: list[Agent], max_handoffs=20, max_iterations=20, execution_timeout=900.0, node_timeout=300.0) [^11]

# 汇总 agent 接收三路结果
analyst = Agent(system_prompt="综合多领域调研结论，给出综合分析。")

builder = GraphBuilder()
builder.add_node(research_swarm, "parallel_research")
builder.add_node(analyst, "synthesis")
builder.add_edge("parallel_research", "synthesis")
graph = builder.build()

# GraphBuilder 的执行同样需要异步调用
async def run_swarm():
    result = await graph.invoke_async("研究 AI 对医疗/科技/经济三个领域的综合影响")
    return result

asyncio.run(run_swarm())
```

四种拓扑的选择逻辑：任务是否需要专业分工？是的话用 agent-as-tool 或 Supervisor。任务步骤之间是否有严格的先后依赖？是的话用 Graph。任务能否被拆成独立的并行子任务？是的话用 Swarm。

### 5.2 Hooks 系统：在不改循环的前提下注入逻辑

Hooks 是 Strands 提供的"在不改框架源码的前提下介入 agent 生命周期"的机制。你通过实现 `HookProvider` 协议，把自己的回调函数注册到特定事件上。Strands 当前支持 8 种 Hook 事件，覆盖从 agent 初始化到单次工具调用结果的完整生命周期：

```python
from strands import Agent
from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import (
    BeforeInvocationEvent,
    AfterInvocationEvent,
    BeforeToolCallEvent,
    AfterToolCallEvent,
)

class AuditHook(HookProvider):
    """生产环境审计钩子：记录所有工具调用和模型决策。"""

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self.on_start)
        registry.add_callback(AfterInvocationEvent, self.on_end)
        registry.add_callback(BeforeToolCallEvent, self.on_tool_call)
        registry.add_callback(AfterToolCallEvent, self.on_tool_result)

    def on_start(self, event: BeforeInvocationEvent) -> None:
        import time
        self._start_time = time.time()
        print(f"[Audit] 任务开始：{event}")

    def on_end(self, event: AfterInvocationEvent) -> None:
        import time
        elapsed = time.time() - self._start_time
        print(f"[Audit] 任务完成，耗时 {elapsed:.2f}s")

    def on_tool_call(self, event: BeforeToolCallEvent) -> None:
        # 在这里可以实现 human-in-the-loop：
        # 如果工具是高风险操作，暂停并等待用户确认
        tool_name = getattr(event, "tool_name", "unknown")
        print(f"[Audit] 即将调用工具：{tool_name}")

    def on_tool_result(self, event: AfterToolCallEvent) -> None:
        print(f"[Audit] 工具调用完成")

# 将 hook 注入 agent
lena = Agent(
    system_prompt="你是 Lena v2.6，配备了审计日志。",
    tools=[get_time, greet],
    hooks=[AuditHook()],
)
```

Hook 系统的典型用途：
- `BeforeToolCallEvent`：实现 human-in-the-loop（高风险工具调用前暂停确认）
- `AfterToolCallEvent`：记录工具调用结果，送入外部审计系统
- `BeforeInvocationEvent` / `AfterInvocationEvent`：统计每次调用的 token 消耗和时延
- `BeforeModelCallEvent` / `AfterModelCallEvent`：监控模型调用频率，实现自定义限流

与 `callback_handler` 的区别：`callback_handler` 处理流式事件（token 粒度），hook 处理生命周期事件（调用粒度）。两者可以同时使用，互不干扰。

### 5.3 对话历史管理：滑动窗口 vs 压缩摘要

第 10 章讲过对话历史增长的问题：不管理会超出 context window，硬截断会丢失关键前提。Strands 提供了两个不同策略的实现：

**默认：`SlidingWindowConversationManager`（滑动窗口）**

```python
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

# 默认 window_size=40，超出时删除最旧消息
# 工具调用对（ToolUse + ToolResult）不会被拆分截断
conversation_manager = SlidingWindowConversationManager(window_size=40)

lena = Agent(
    system_prompt="你是 Lena v2.6。",
    tools=[get_time],
    conversation_manager=conversation_manager,
)
```

滑动窗口的优点是零额外 LLM 调用开销，缺点是超出窗口的历史会被直接丢弃。

**可选：`SummarizingConversationManager`（压缩摘要）**

```python
from strands import Agent
from strands.agent.conversation_manager import SummarizingConversationManager

# summary_ratio=0.3：压缩最旧的 30% 消息
# preserve_recent_messages=10：最近 10 条永不压缩
# 触发时机：context window 使用超过 70% 时
conversation_manager = SummarizingConversationManager(
    summary_ratio=0.3,
    preserve_recent_messages=10,
)

lena = Agent(
    system_prompt="你是 Lena v2.6。",
    tools=[get_time],
    conversation_manager=conversation_manager,
)
```

`SummarizingConversationManager` 不是简单截断——它调用同一个模型把早期历史压缩成摘要段落，把摘要作为对话的"记忆前缀"保留。代价是每次触发压缩时多一次 LLM 调用。选择哪个取决于对话长度和对历史完整性的要求：短对话用默认滑动窗口，长期运行的 agent 考虑压缩摘要。

---

## Beat 6 · 运行验证：从 demo 到可诊断的系统

### 6.1 完整安装与运行流程

```bash
# 第一步：安装依赖
pip install strands-agents strands-agents-tools
# strands-agents 和 strands-agents-tools 是两个独立包，需分别安装
# strands-agents：核心 SDK（Agent、@tool、ConversationManager、Hooks 等）
# strands-agents-tools：52 个预置工具（file_read、shell、http_request 等）

# 第二步：配置 AWS 凭证（如果使用 Bedrock 默认后端）
aws configure
# 或直接设置环境变量：
# export AWS_ACCESS_KEY_ID=...
# export AWS_SECRET_ACCESS_KEY=...
# export AWS_DEFAULT_REGION=us-west-2

# 确认 us-west-2 区域已开通 Claude Sonnet 模型访问权限：
# AWS 控制台 → Bedrock → Model access → us.anthropic.claude-sonnet-4-6

# 如果使用 Anthropic 直连（不用 Bedrock）：
# pip install anthropic
# export ANTHROPIC_API_KEY=sk-ant-...
# 代码里把 BedrockModel 替换为 AnthropicModel

# 第三步：运行 Beat 3 的 demo
python3 lena_v26_strands.py
```

预期输出（Beat 3 demo）：
```
=== 测试 1：查询时间 ===
[调用工具: get_time]
现在是 UTC 时间 2026 年 5 月 11 日凌晨 3 点 42 分。

=== 测试 2：直接对话 ===
我可以查询当前时间，也可以向用户打招呼。有什么需要帮助的？

=== 测试 3：打招呼 ===
[调用工具: greet]
你好，Alice！我是 Lena v2.6。
```

### 6.2 多 agent graph 验证

```bash
# 运行 Beat 5 的 Graph demo（需要 asyncio 支持）
python3 -c "
import asyncio
from strands import Agent
from strands.multiagent import GraphBuilder

researcher = Agent(name='r', system_prompt='你是调研专家，用一句话概括关键发现。')
writer = Agent(name='w', system_prompt='你是写作专家，把调研结论整理成一段报告。')

builder = GraphBuilder()
builder.add_node(researcher, 'research')
builder.add_node(writer, 'writing')
builder.add_edge('research', 'writing')
graph = builder.build()

async def run():
    result = await graph.invoke_async('Strands 框架的核心设计哲学是什么？')
    print(result)

asyncio.run(run())
"
```

预期输出：一段经过 researcher → writer 两阶段处理的结构化报告，内容比单 agent 更有层次感。

### 6.3 故障诊断指南

**问题 1：`ModelNotReady` 或 `ResourceNotFoundException`**

原因：Bedrock 模型访问权限未开通。
诊断：`aws bedrock list-foundation-models --region us-west-2 | grep claude`
修复：到 AWS 控制台 → Amazon Bedrock → Model access → 勾选 Claude 系列模型 → Save changes（审批通常在 5 分钟内完成）。

**问题 2：工具从未被调用（agent 直接回答，不触发工具）**

原因最常见的是 docstring 质量问题。`@tool` 装饰器把 docstring 原样传给模型作为工具描述——如果描述含糊，模型无法判断何时应该使用这个工具。
诊断：调用 `agent.tool_names`（`Agent` 的属性，返回已注册工具名列表）查看实际工具注册情况。[^9]
修复：让 docstring 明确说明"什么情况下调用这个工具"和"每个参数的语义"。对比：

```python
# 模糊 docstring（模型不知道何时用）
@tool
def get_time() -> str:
    """时间工具。"""
    ...

# 清晰 docstring（模型明确知道何时用）
@tool
def get_time(timezone_name: str = "UTC") -> str:
    """
    返回当前时间。当用户询问'现在几点'、'当前时间'、'今天日期'时调用此工具。
    参数 timezone_name: 时区名称（如 'UTC'、'Asia/Shanghai'）。
    返回格式：YYYY-MM-DD HH:MM:SS TZ
    """
    ...
```

**问题 3：`NotImplementedError: Using pydantic.Field within Annotated is not yet supported`**

原因：`@tool` 的内部 schema 生成（Pydantic `create_model()`）只支持 `Annotated[T, "纯字符串描述"]` 语法，不支持 `Annotated[T, pydantic.Field(...)]`。
修复：把 `Annotated[T, pydantic.Field(description="...")]` 改为 `Annotated[T, "description string"]`，或者直接去掉 `Annotated`，把描述放到参数 docstring 里。

**问题 4：多 agent graph 挂起或超时**

原因：某个节点 agent 在等待工具结果或进入无限 loop。
诊断：给 Agent 设置 `max_parallel_instances` 和超时；开启 OTEL trace，在 CloudWatch 或 Jaeger 里查看哪个 span 没有结束。
修复：
```python
from strands import Agent
from strands.models import BedrockModel

# 限制最大循环轮数，防止 agent 陷入无限推理
model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-6",
    region_name="us-west-2",
)
agent = Agent(
    model=model,
    system_prompt="...",
    max_parallel_instances=3,  # 并发限制
)
```

**问题 5：`ImportError: No module named 'strands_tools'`**

修复：`strands-agents` 和 `strands-agents-tools` 是两个独立包，需要分别安装：
```bash
pip install strands-agents strands-agents-tools
```

### 6.4 调试的心智模型转变

用 Strands（或任何 agent 框架）后，调试方式发生了一个本质转变：从"在循环里加 print"变成"读 OTEL trace"。

手写版的调试流程是：问题出现 → 在第 N 行加 `print` → 重跑 → 看输出。
Strands 的调试流程是：问题出现 → 找到对应的 OTEL trace → 展开相关 span → 看每一步的输入/输出（包括每轮的 prompt tokens + completion tokens、每个工具的输入参数和返回值、每次 LLM 调用的时延）。

两种流程都能找到根因，但 Strands 的流程更适合生产环境——你不需要重新部署就能看到历史上每一次 agent 执行的完整轨迹。`trace_attributes` 参数让你可以在 trace 上打标签（比如 `user_id`、`session_id`），在 CloudWatch 里过滤出特定用户的所有 agent 调用，直接定位问题出在哪一轮。

---

## Beat 7 · Design Note：model-driven 不等于失控

> **Why Not 直接写死每一步的 workflow？**

Strands 的 model-driven 设计让不少工程师感到不安："如果模型决定下一步做什么，我怎么保证它做的是我想要的？"这是一个合理的疑问，值得正面回答。

**先说 model-driven 的核心价值**

硬编码 workflow 的本质问题是：它只能处理你预先想到的情况。现实世界的用户输入是无限多样的——用户不会按你预设的路径走，他们会在中途改变需求、提出组合问题、用你没想到的方式表达意图。

model-driven 的优势正在这里：模型能处理你没有显式编程的情况。它能把"帮我查一下现在几点，然后告诉我深圳现在是白天还是夜晚"这种组合问题拆分成两个工具调用的序列，而不需要你写 `if question_type == "time_and_timezone"` 的分支。

**然后说它的真实边界**

model-driven 在"模型能理解的范围内"运作良好，但有一类场景它天生处于劣势：**需要强制保证的业务规则**。

典型例子：一个金融 agent，规则是"任何单笔操作金额不得超过账户余额的 5%"。把这条规则写进 system prompt，理论上模型应该遵守，但实际上这是概率性的——模型可能在极端的 context 下"忘记"这条约束。

正确的做法是：把业务规则写进工具的实现代码，而不是 system prompt。

```python
@tool
def execute_trade(symbol: str, amount_usd: float) -> dict:
    """
    执行交易。参数 symbol: 交易对；amount_usd: 交易金额（美元）。
    注意：单笔金额不得超过账户余额的 5%，系统会自动拒绝超限请求。
    """
    account_balance = get_account_balance()
    max_allowed = account_balance * 0.05
    if amount_usd > max_allowed:
        # 强制拒绝——这是代码层面的保证，不依赖模型的理解
        return {
            "status": "rejected",
            "reason": f"超出单笔限额：{amount_usd:.2f} USD > {max_allowed:.2f} USD（5% 限制）",
        }
    # 正常执行交易逻辑
    return do_trade(symbol, amount_usd)
```

规则是代码，语气是 prompt。这是从手写 25 章里提炼出来的一个判断标准：**确定性的约束不能依赖概率性的语言模型来执行**，它必须活在代码层。

**关于多 agent 的状态管理**

当多个 agent 并行运行时，状态管理是另一个需要在代码层处理的问题。Strands 的 `Graph` 拓扑提供了显式的执行顺序保证，但节点之间的状态传递依赖框架内部的消息传递机制——你看不到"消息从 researcher 传给 analyst 时的中间格式是什么"。

这不是框架的 bug，这是分层架构的基本取舍：每一层抽象都让你少看一层细节。接受这个取舍的前提是：**你对框架的行为有足够的可观测性，当出现非预期结果时，你能通过 trace 而不是读源码来定位问题**。这也是为什么 Strands 把 OTEL 集成放在设计的核心位置，而不是作为可选插件。

**Design Note 的结论**

model-driven 不等于失控，它等于"让模型做擅长做的决策，让代码处理不该妥协的约束"。

这个判断标准很具体：当你面对一个 agent 设计决策，问自己"这条规则如果被违反，后果可接受吗？"——不可接受的写进工具代码（确定性执行），可接受的写进 system prompt（模型自由发挥）。Strands 不阻止你做这两件事，它只是让前 25 章学会的两件事——手写业务逻辑和 LLM 推理——能在同一个系统里和谐并存。

---

## 框架光谱：六个框架一张表一句话定位

到 2026 年初，主流 agent 框架形成了相对清晰的分工，核心差异集中在三个轴：**控制粒度**（model-driven vs developer-first）、**AWS 集成深度**、**最小启动代码量**。下面这张表帮你找到"我的场景应该看哪个框架"的入口：

| 框架 | 核心哲学 | 最小代码量 | 最适合场景 | 主要取舍 |
|---|---|---|---|---|
| **Strands** | model-driven，LLM-first | ~5 行 | AWS 原生 + 极简入门 + MCP/A2A 扩展 | 强业务规则需写进工具代码层 |
| **LangGraph** | developer-first，显式状态机 DAG | ~20 行 | 需要精确 workflow 控制的复杂流程 | 学习曲线陡，依赖 LangSmith 做可观测性 |
| **AutoGen** | 事件驱动多 agent 对话（微软） | ~15 行 | 多语言分布式 agent，.NET 生态 | 无 AWS 原生集成 |
| **CrewAI** | 角色扮演团队协作 | ~30 行 | 明确分工的业务流程（编辑 + 审核 + 执行） | 动态任务分配弱于 LangGraph |
| **smolagents** | 代码优先（生成代码直接执行） | ~8 行 | 数据科学、HuggingFace 模型、代码生成 | 代码执行安全风险高，需严格沙箱 |
| **Agno** | 全栈平台，SDK→Runtime→控制平面 | ~20 行 | 需要快速部署 + 多接口暴露的企业团队 | 控制平面付费，无 AWS 原生 |

**与 LangGraph 的关键区别**

LangGraph 和 Strands 代表了多 agent 系统的两端：前者要求开发者显式定义状态机（State 类 + 每个节点的状态转换逻辑），后者让模型自己决定流程。这两种取舍都有真实场景支持：

- 场景 A：一个内容审核流水线，每一步的规则是固定的（OCR → 违规检测 → 人工复核 → 归档）。LangGraph 更合适——每步是确定性的，状态机能精确建模。
- 场景 B：一个通用客服 agent，需要根据用户的具体问题动态组合工具。Strands 更合适——模型能处理千变万化的用户意图，不需要你预先把所有路径都编程进去。

选择框架的判断顺序：先看你的部署目标（AWS 还是自托管），再看你的控制粒度需求（精确状态机还是模型自主），最后看你的团队背景（已有哪个框架的投入）。

---

## 本章核心判断（可复述版）

读完本章，带走这五条判断：

**判断 1：框架是一笔交易，手写背景决定你能否平等签约**
用框架不是懒，是用你的手写背景做担保——你知道框架替你做了什么，出问题时你知道去哪找。没有手写背景的人用框架，是在一张自己读不懂的合同上签字。

**判断 2：确定性约束写进工具代码，概率性指导写进 system prompt**
"仓位不超过 5%"这条规则，代码执行 100%，prompt 执行概率性。安全线永远在代码层。这条判断适用于所有 model-driven 系统，不只是 Strands。

**判断 3：Strands 的默认值有具体数字，值得记住**
- 对话历史：默认滑动窗口 `window_size=40` 条
- 重试机制：`MAX_ATTEMPTS=6`，初始 `4` 秒，最长 `4` 分钟（240 秒）
- 压缩触发：context 超 70%，压缩最旧 30%，保留最近 10 条
- 工具生态：52 个预置工具，14 种模型提供商

**判断 4：四种拓扑的选择是结构性决策，不是偏好**
专业分工 → agent-as-tool 或 Supervisor；先后依赖明确 → Graph；独立并行 → Swarm（`max_iterations=20`，`execution_timeout=900s`，`node_timeout=300s`）。这个选择决定系统的可调试性和可扩展性，选错了很难重构。

**判断 5：Strands 的关键参数是设计意图的显式化，不是随意默认值**
- `SlidingWindowConversationManager(window_size=40)`：默认保留 40 条，不是无限积累——这是"默认收紧"
- `MAX_ATTEMPTS=6, INITIAL_DELAY=4s`：重试 6 次，初始等待 4 秒——这是"容错但有边界"
- 强制业务规则写进工具代码，不进 system prompt——这是"硬约束不依赖概率性 LLM"
- `Annotated[T, pydantic.Field(...)]` 抛 NotImplementedError 而非静默失败——这是"运行时早失败优于晚误导"

这些默认值不是随意选的，每个背后都有一个"为什么不让用户随意放飞"的设计判断。

---

## 思考题

1. Strands 的 `@tool` 装饰器从 docstring 生成工具描述，这意味着 docstring 的质量直接影响模型选工具的准确率。你会如何评估一个 docstring"写得好不好"？评估标准是什么？如何量化这个质量的影响？

2. 在手写版 Lena 里，你可以在 while 循环的任意位置插入日志或条件逻辑。Strands 提供了 8 种 Hook 事件来替代这种直接干预——你认为这 8 种 hook 在哪类场景下各有优势？有没有哪类需求是 hooks 处理不了的，必须回到手写循环？

3. "model-driven 消除了硬编码 workflow 逻辑"这个说法听起来很吸引人。本章的 Design Note 指出"确定性的约束不能依赖概率性的语言模型来执行"。想一个你能想到的场景，在这个场景里 model-driven 反而是个问题，并设计一个既保留 model-driven 灵活性又能强制执行业务规则的方案。

4. Strands 的四种多 agent 拓扑（agent-as-tool / Supervisor / Graph / Swarm）对应不同的控制权和复杂度。如果你要构建一个"实时新闻播报 agent"（需要并行抓取 10 个新闻源、过滤重复内容、改写成播客脚本），你会选择哪种拓扑？画出节点和边的结构。

5. `SlidingWindowConversationManager`（默认窗口 40 条）和 `SummarizingConversationManager`（默认压缩 30%，保留最近 10 条）各有什么性能代价？在一个需要运行 8 小时的 long-running agent 里，你会如何配置历史管理策略？

---

[^1]: AWS Machine Learning Blog, "Strands Agents SDK: A Technical Deep Dive into Agent Architectures and Observability", https://aws.amazon.com/blogs/machine-learning/strands-agents-sdk-a-technical-deep-dive-into-agent-architectures-and-observability/
[^2]: Strands Agents SDK 官方文档, "User Guide — Multi-Agent Systems", https://strandsagents.com/latest/user-guide/concepts/multi-agent/
[^3]: Strands Agents SDK 官方文档, "User Guide — Hooks", https://strandsagents.com/latest/user-guide/concepts/agents/hooks/
[^4]: Strands Agents SDK 官方文档, "User Guide — Streaming & Callback Handlers", https://strandsagents.com/latest/user-guide/concepts/streaming/callback-handlers/
[^5]: Strands Agents SDK 源码, `src/strands/event_loop/event_loop.py`: `MAX_ATTEMPTS = 6`, `INITIAL_DELAY = 4`, `MAX_DELAY = 240`, https://github.com/strands-agents/sdk-python
[^6]: Strands Agents SDK 源码, `src/strands/agent/conversation_manager/sliding_window_conversation_manager.py`: `window_size=40`, `_PRESERVE_CHARS=200`, https://github.com/strands-agents/sdk-python
[^7]: Strands Agents SDK 源码, `src/strands/agent/conversation_manager/summarizing_conversation_manager.py`: `summary_ratio=0.3`, `preserve_recent_messages=10`, proactive threshold `0.70`, https://github.com/strands-agents/sdk-python
[^8]: Strands Agents SDK 源码, `src/strands/types/_events.py`: `InitEventLoopEvent` (`init_event_loop: True`), `TextStreamEvent` (`data: <text>`), `ToolUseStreamEvent` (`current_tool_use`), `ForceStopEvent` (`force_stop: True`), https://github.com/strands-agents/sdk-python
[^9]: Strands Agents SDK 源码, `src/strands/agent/agent.py`: `Agent.tool_registry`（公开属性，`ToolRegistry` 实例）；`Agent.tool_names`（只读属性，返回已注册工具名 `list[str]`），https://github.com/strands-agents/sdk-python
[^10]: Strands Agents SDK 源码, `src/strands/tools/decorator.py`: `_clean_pydantic_schema()` 仅支持 `Annotated[T, "纯字符串"]`；若 metadata 为 `pydantic.Field`，则抛出 `NotImplementedError: "Using pydantic.Field within Annotated is not yet supported for tool decorators"`, https://github.com/strands-agents/sdk-python
[^11]: Strands Agents SDK 源码, `src/strands/multiagent/swarm.py`: `Swarm(nodes: list[Agent], max_handoffs=20, max_iterations=20, execution_timeout=900.0, node_timeout=300.0)`, https://github.com/strands-agents/sdk-python
[^12]: Strands Agents SDK 源码, `src/strands/types/event_loop.py`: `StopReason` 枚举值包括 `"end_turn"`、`"tool_use"`、`"max_tokens"`、`"stop_sequence"`、`"cancelled"`、`"interrupt"`、`"guardrail_intervened"` 等，https://github.com/strands-agents/sdk-python
[^13]: Strands Agents SDK 官方文档及源码 `src/strands/agent/agent.py`: `Agent.__init__` 参数 `load_tools_from_directory: bool = False`，设为 `True` 时启用 `./tools/` 目录热重载，https://github.com/strands-agents/sdk-python
