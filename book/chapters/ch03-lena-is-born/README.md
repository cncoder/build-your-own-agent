# 第 3 章：Lena 诞生——50 行 Python 写出可跑的 Agent

> **[支柱：Tool 统一性]**

---

## Beat 1 — 路线图

```
Ch 1 → Ch 2 → [Ch 3 ← 你在这里] → Ch 4 → Ch 5 → …
```

上一章你理解了 ReAct 循环是什么，画了一张状态机图，写下了"下次 LLM 调用时把上一步观察结果也带上"这个关键洞察。那是**纸上的 agent**。

本章要把那张图变成**真实可运行的 Python 代码**。

路线是这样的：从一个只能打印 `"OK"` 的空骨架出发 → 加进工具注册机制 → 接通 LLM → 写出 while 循环 → 解析 `tool_use` → 回填 `tool_result`。每步都能运行，每步都打印一个有意义的输出。最终产物是 `lena-v0.3`：在终端里问"现在几点"，Lena 会调用一个真实工具回答你。

本章后 Lena 从 v0.1（裸 API 调用）升级到 **v0.3**，新增能力：**工具调用 + 多轮循环**。

途中会踩一个坑：工具结果回填时，必须先把"LLM 说要调工具"这条消息存入历史，才能追加工具结果——少了这一步，API 会报错。很多人第一次写时都会在这里卡住。

> **🧠 聪明度增量（v0.2 → v0.3）**：Lena 第一次真正"跨 provider 抽象"运行——用统一的 `BaseProvider` 接口对接 Anthropic、OpenAI、Bedrock，切换模型无需改一行业务代码。这一章教读者把 provider 抽象层长在自己 agent 上的方法。

---

## Beat 2 — 动机

Andrej Karpathy 在 2025 年 YC Startup School 演讲中有个精妙的比喻：

> "LLMs are kind of like these fallible people spirits that we have to learn to work with."
> （LLM 就像**容易犯错的精灵**——你不能命令它，只能学会跟它协作。）

这句话定义了本章的核心问题：我们要写的不是一段调用 API 的脚本，而是一个**能跟精灵协作的骨架**——它得容忍精灵出错、引导精灵做对事、在精灵乱来时拦住它。这个骨架就是 Lena 的核心 agent loop。

先感受一下"没有工具时会发生什么"。

```python
# 没有工具的 Lena v0.1（Ch 1 产物）
response = client.messages.create(
    model="claude-haiku-4-5-20251001",  # 2026 Claude 4.X 系列（2024 版已 deprecated）
    max_tokens=64,
    messages=[{"role": "user", "content": "现在几点了？"}],
)
print(response.content[0].text)
```

运行后，你会看到类似这样的输出：

```
我没有访问实时时钟的能力，所以无法告诉你当前时间。
你可以查看手机或电脑的时钟来获取准确时间。
```

这是正确且诚实的回答——LLM 训练时没有接入实时数据，它确实不知道当前时间。

现在设想一个场景：你要构建一个日程助手，用户问"今天下午三点有什么会议"，你希望 Lena 能查日历后再回答。或者用户说"帮我把这个 CSV 里的销售数据汇总一下"，你希望 Lena 能真正读取文件。

这类任务有一个共同点：**LLM 光靠训练数据无法完成，必须访问外部能力**。时钟、文件系统、API、数据库——这些都是 LLM 天然接触不到的。

解法不是换一个更聪明的模型，而是给 LLM 配上"工具"，让它能主动发起调用，拿到结果后再决策。这就是本章要解决的问题。

这个解法的妙处在于它的通用性。你今天给 Lena 配了 `get_time`，明天可以配 `read_file`，后天配 `web_search`，Lena 的"大脑"（AgentLoop）不需要做任何修改——它只需要看工具列表，把工具说明传给 LLM，然后执行 LLM 选择的工具。工具是 agent 能力的边界，而这个边界完全由你定义。这就是为什么 SPEC 文档里把它称为"Tool 统一性支柱"：任何外部能力都可以被工具化，agent 的核心代码对工具的具体内容无感知。

> **Convention：工具（Tool）= 一个 schema + 一个 handler。** schema 是给 LLM 读的使用说明，handler 是真正执行的 Python 函数。LLM 永远只看 schema，不执行代码；执行永远发生在你的 Python 进程里。后续统一用"schema"指使用说明，"handler"指执行函数。

---

## Beat 3 — 理论铺垫

### 3.1 agent 的三个组成部分

把一个最小可行的 agent 拆开来看，你会发现它只有三件事：

**LLM**——决策引擎。它读取当前所有上下文（用户的话、工具的使用说明、历史执行结果），决定下一步做什么：要么调用某个工具，要么直接给出最终答复。

**Loop（while 循环）**——执行引擎。一个单次 API 调用只能让 LLM 决策一次。如果 LLM 这次决定调工具，你需要执行工具、把结果反馈给 LLM、让 LLM 再决策一次——这个反馈回路就是 while 循环的本质。没有 Loop，就只有一次性的 QA，不是 agent。

**Tools（工具）**——行动能力。LLM 能描述动作，但不能执行动作；你的代码能执行动作，但不知道什么时候该执行。工具是两者之间的接口：LLM 输出"我想调用 X(args)"，你的代码接收这个意图并真正运行 X。

> **Convention：agent = LLM + Loop + Tools。** 这三元组是最小可行的定义。LangChain、AutoGen、CrewAI 等所有框架，本质上都是这个三元组加了一层更漂亮的 API。后续统一用这三个词指代各自含义。

这个简洁性是有据可查的。Anthropic 在 [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)（2024-12-19）里写道：

> "Many agents will be overkill. Start with prompting. If prompting doesn't work, start with the simplest agent architecture. Don't add complexity until you demonstrably need it."

这句话的含义是：工具调用的 while 循环，就是"最简 agent 架构"的本体。在需要更多之前，这 50 行就够了。

**三元组的三个维度各自的局限性**，也值得在这里说清楚：

- **只有 LLM，没有 Loop**：每次用户输入只能得到一次 LLM 回复。如果 LLM 需要调工具拿数据、再基于数据推理，这个流程就无法完成。你得到的只是 LLM 的第一步决策，而不是最终结果。
- **只有 Loop，没有 Tools**：LLM 在循环里一遍遍问，但它能做的始终只有文字生成。循环是空转，没有新信息进来。
- **只有 Tools，没有 Loop**：工具是一次性调用。用户问什么，你调一个工具，把结果直接返回——但如果任务需要根据第一个工具的结果决定是否调第二个工具，这个链式决策就无法实现。

三者缺一不可。这也是 Ch 2 里用状态机描述 agent 的原因：Thought → Action → Observation → Thought 这个循环，在代码层面的对应就是 LLM + while loop + tools_execute。

### 3.2 tool_use 协议：LLM 是如何"调用"工具的

LLM 无法直接调用函数——它的输出永远是文本。真正的工具调用分两步：

**第一步，LLM 输出意图**。当 LLM 判断需要调用工具时，它不会输出正常的文字答复，而是在 `content` 数组里输出一个特殊的 JSON 块，格式大致如下（Anthropic 原生格式）：

```
类型: tool_use
名字: get_time
ID:   toolu_01AbCd…（每次唯一，用于关联后续结果）
参数: {}
```

同时，API 返回的 `stop_reason` 字段会是 `"tool_use"` 而不是 `"end_turn"`——这是你的代码判断"是否需要调工具"的信号。

**第二步，你的代码执行并回填**。你的代码读到 `stop_reason == "tool_use"`，解析出工具名和参数，调用对应的 Python 函数，拿到结果。然后把这个结果以特定格式追加到 `messages[]` 里，再次调用 LLM——LLM 这次看到工具结果，给出最终答复。

整个流程里，messages[] 是唯一的状态容器。每次 LLM 调用都会看到完整的历史——用户消息、LLM 的决策、工具结果——然后基于这个完整上下文决策下一步。

> **Convention：stop_reason = "tool_use" 时 LLM 要求调工具；stop_reason = "end_turn" 时 LLM 给出最终答复。** 后续 agent_loop 的分支逻辑完全基于这两个值。

这个机制在 Anthropic 官方文档 [Tool Use Overview](https://docs.anthropic.com/en/docs/build-with-claude/tool-use) 有完整规范。不需要读完，只需要知道一个核心结论：**tool_result 必须以 user 角色回填，且必须跟在含 tool_use 的 assistant 消息之后**——这是最容易出错的地方，后面 Beat 5 会专门讲。

### 3.3 MVA 6 模块：行业公分母

在开始写代码之前，我们先从更高的角度看一眼全局。

对比三个公开的教学级 agent 实现（nano-claw TS 版 247 行 `src/agent/loop.ts`、nanoClaw Python 版 `core/agent.py`、以及一个基于 pydantic-ai 的极简版 `src/agent_app.py`）后，可以提炼出一个**最小可行 Agent（MVA）的 6 模块共识**——这三个项目的作者来自不同背景，用了不同语言，但不约而同地划分出了相同的模块边界：

| 模块 | 职责 | 为什么要独立为一个模块 |
|---|---|---|
| **Config** | 读取环境变量、命令行参数，解耦配置来源 | API key 和模型名不该硬编码，否则换个机器就得改代码 |
| **Provider** | 统一多家 LLM API 的格式差异，让 AgentLoop 无感知 | Anthropic / OpenAI / Bedrock 的格式不同，隔离在 Provider 层后 AgentLoop 零感知 |
| **Memory** | 管理 messages[] 对话历史，维护"当前上下文" | LLM 每次调用都是无状态的，messages[] 是"有状态"的全部秘密 |
| **ToolRegistry** | 注册工具 + 执行工具，按名称路由到正确 handler | 工具种类在增长，AgentLoop 不应该关心"这个工具叫什么" |
| **AgentLoop** | while 循环 + stop_reason 分支决策，是 agent 的神经中枢 | 决策逻辑和工具执行逻辑必须分离，否则一改工具就要动循环 |
| **Skills** | 可复用能力包（SOP + 可选代码），本章不涉及，Ch 10 展开 | 工具是函数，Skills 是"怎么做一类事"的 SOP，两者是不同维度的抽象 |

这 6 个模块是**所有 agent 框架的公分母**。LangChain 有 `LLMChain`（AgentLoop）、`BaseTool`（ToolRegistry）、`ConversationBufferMemory`（Memory）；AutoGen 有 `ConversableAgent`（AgentLoop + Provider）。换了名字，本质相同。明白这一点很重要：框架不是在发明新的概念，而是把已有概念包了更漂亮的外皮。

本章构建策略是**骨架先行**：先把这 6 个模块写成空函数或 stub class，确认管道打通，再逐模块填充真实逻辑。每次只向骨架里增加一个新部件，每次增加后都跑起来验证。这比"写完所有代码再运行"的方式容错率高得多——当你知道"上一步还是好的，这步出了问题"，定位 bug 的时间从小时级缩短到分钟级。

Raschka 在《Build a Large Language Model from Scratch》第 4 章里用的就是这个策略：先建立一个 `DummyGPTModel`，所有子模块用 `pass` 占位，确认整体形状后再逐层填充 `LayerNorm`、`FeedForward`、`MultiHeadAttention`。本章沿用相同思路。

---

## Beat 4 — 脚手架

我们先用**骨架先行策略**（来自 Raschka 在 LLMs from Scratch Ch04 中首先建立 `DummyGPTModel` 再逐层填充的做法）：先把 6 个模块的空 class/函数写出来，每个模块都能"跑"但什么都不做，然后再一个个填充真实逻辑。

下面把 6 个模块的空 class/函数写出来，每个模块都能"跑"但什么都不做，然后再一个个填充真实逻辑：

```python
# lena-skeleton.py — 6 模块空骨架（能跑，但没有真实逻辑）

# ── 模块 1：Config ──────────────────────────────────────────────────────────────
# 职责：读取 .env 和命令行参数，让其他模块无需硬编码配置
import argparse, os

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--provider", default="stub")   # 先用 stub，后面替换
    p.add_argument("--max-turns", type=int, default=10)
    return p.parse_args()

# ── 模块 2：Provider（stub）────────────────────────────────────────────────────
# 职责：统一多家 LLM API 差异，让 AgentLoop 无感知切换 provider
class StubProvider:
    """骨架 provider：直接返回固定答案，不调真实 API。验证管道时很有用。"""
    def chat(self, messages, tools):
        return StubResponse(content="stub 回复", tool_calls=[])

    def make_assistant_with_tool_use(self, response):
        return {"role": "assistant", "content": []}

    def make_tool_result_message(self, tool_id, result):
        return {"role": "user", "content": []}

class StubResponse:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls   # 空列表 = 不调工具

# ── 模块 3：Memory ─────────────────────────────────────────────────────────────
# 职责：维护 messages[] 列表，所有状态都在这里
messages = []   # 本章用最简单的 Python 列表，Ch 7 升级为 SQLite 持久化

# ── 模块 4：ToolRegistry（stub）────────────────────────────────────────────────
# 职责：注册工具 + 按名称路由到正确 handler
def get_tool_schemas():
    return []   # 暂时没有工具

def execute_tool(name, inputs):
    return f"未知工具：{name}"   # 暂时什么都不执行

# ── 模块 5：AgentLoop ───────────────────────────────────────────────────────────
# 职责：while 循环 + stop_reason 分支，是 agent 的神经中枢
def agent_loop(user_input, provider, max_turns):
    messages.append({"role": "user", "content": user_input})
    tools = get_tool_schemas()

    for turn in range(max_turns):
        response = provider.chat(messages, tools)

        if response.tool_calls:           # 工具调用分支（暂时不会触发）
            messages.append(provider.make_assistant_with_tool_use(response))
            for tc in response.tool_calls:
                result = execute_tool(tc["name"], tc["inputs"])
                messages.append(provider.make_tool_result_message(tc["id"], result))
            continue

        messages.append({"role": "assistant", "content": response.content})
        return response.content

    return "（已达最大轮次）"

# ── 模块 6：Skills（本章不实现）────────────────────────────────────────────────
# 职责：可复用能力包（SOP + 可选代码），Ch 10 展开
# skills = []   # 暂时留空

# ── REPL 主循环 ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    args = parse_args()
    provider = StubProvider()
    print("Lena 骨架 ✦ 输入任何内容试试")
    while True:
        user = input("你：").strip()
        if user in ("exit", "quit"):
            break
        print(f"Lena：{agent_loop(user, provider, args.max_turns)}\n")
```

运行这个骨架：

```bash
python3 lena-skeleton.py
你：hello
Lena：stub 回复

你：现在几点
Lena：stub 回复
```

管道是通的：用户输入 → AgentLoop → Provider → 回复。现在把 StubProvider 替换成真实 LLM，把空 ToolRegistry 填上 `get_time`，就是本章的完整实现。接下来我们逐步做这件事。

---

## Beat 5 — 渐进组装

从骨架出发，依次填充三个真实能力：

| 扩展点 | 为何需要 | 如何加 |
|--------|---------|--------|
| ToolRegistry 填入 get_time | 给 LLM 提供可以调用的工具，才能真正"做事" | 定义 schema + handler，注册到 TOOLS 列表 |
| stop_reason 判断 | 区分 LLM 主动结束（返回文字）vs 要求调工具（继续循环） | 检查 `response.tool_calls` 是否为空 |
| tool_result 回填顺序 | LLM 需要看到正确格式的历史才能继续推理 | 先存 assistant 消息，再追加 tool_result |

### 扩展 1：填入 ToolRegistry

下面实现第一个真实工具——一个报告当前时间的时钟：

```python
# tools.py（完整版）

from datetime import datetime
from typing import Any

def get_time_handler(timezone: str = "local") -> str:
    """真正执行 get_time 的函数。只依赖标准库，零副作用。"""
    now = datetime.now()
    return now.strftime(f"当前时间是 %Y年%m月%d日 %H:%M:%S（{timezone}）")

TOOLS: list[dict[str, Any]] = [
    {
        "schema": {
            "name": "get_time",
            "description": "获取当前本地时间。当用户问"现在几点"、"今天几号"等时间问题时调用。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "时区说明，默认 'local'",
                        "default": "local",
                    }
                },
                "required": [],   # 所有参数可选，LLM 可以空参调用
            },
        },
        "handler": get_time_handler,
    }
]

def get_tool_schemas() -> list[dict]:
    """返回所有工具的 schema 列表（传给 LLM 的那一份）。"""
    return [t["schema"] for t in TOOLS]

def execute_tool(name: str, inputs: dict) -> str:
    """按名称路由并执行工具，返回字符串结果。"""
    for tool in TOOLS:
        if tool["schema"]["name"] == name:
            try:
                return str(tool["handler"](**inputs))
            except Exception as e:
                return f"工具执行出错：{e}"
    return f"未知工具：{name}"
```

快速验证 handler 是否正确：

```python
>>> from tools import get_time_handler, execute_tool
>>> get_time_handler()
'当前时间是 2026年05月06日 00:24:16（local）'
>>> execute_tool("get_time", {})
'当前时间是 2026年05月06日 00:24:16（local）'
>>> execute_tool("no_such_tool", {})
'未知工具：no_such_tool'
```

工具本身是通的。现在把 StubProvider 替换成真实 LLM。

### 扩展 2：接通 Provider

这是本章最值得细看的环节，因为**Anthropic 和 OpenAI 的协议格式确实不一样**——不是微小差异，而是在消息结构的多个位置都有分歧。

先看一张对比：

| 对比项 | Anthropic | OpenAI |
|--------|-----------|--------|
| 工具调用的位置 | `response.content[]` 数组内的 block | `response.choices[0].message.tool_calls` 顶层字段 |
| 参数字段名 | `input`（Python dict） | `arguments`（JSON 字符串，需 json.loads） |
| 工具结果的角色 | `"user"`（携带特殊 content 格式） | `"tool"`（独立的第四种角色） |
| 关联 ID 字段名 | `tool_use_id` | `tool_call_id` |

这 4 个差异是独立的，每一个都可能导致 API 报错。Provider 层的价值就是把这些差异封装进去，让 AgentLoop 的核心代码不需要知道自己在用哪家 API。

你可能会想：直接用 OpenAI 的兼容接口，把所有 provider 都对齐到一套格式不就行了吗？这是可行的，很多项目也这么做。但代价是丧失各家的原生特性——例如 Anthropic 的工具调用返回里，文字和工具意图可以同时出现在 `content` 数组里（LLM 先说"我来查一下"，再给出 tool_use block），OpenAI 的格式则把它们分在不同字段。如果你想保留这个"思考过程文字"，就需要原生格式。所以本章选择在 Provider 层适配各家格式，而不是强制统一到某一家的接口。

下面逐段拆解 Anthropic 工具调用响应的实际结构：

```python
# Anthropic 工具调用响应的结构（示意）
response.content = [
    # block 1：LLM 的思考文字（可能有，也可能没有）
    {"type": "text", "text": "我来查一下当前时间…"},

    # block 2：工具调用意图
    {
        "type": "tool_use",
        "id": "toolu_01AbCd...",   # ← 每次唯一 ID，后续 tool_result 需要引用它
        "name": "get_time",
        "input": {}                # ← 参数是 dict（不是字符串）
    }
]
response.stop_reason = "tool_use"  # ← 这是分支判断的关键信号
```

然后是 tool_result 回填的格式——这里有一个容易踩的坑：

```python
# 正确的回填顺序（缺一不可，顺序不可颠倒）

# 第一步：先把 LLM 的"决定调工具"消息存入 messages
messages.append({
    "role": "assistant",
    "content": [
        {"type": "text", "text": "我来查一下…"},          # 如果 LLM 有文字
        {"type": "tool_use", "id": "toolu_01AbCd...",
         "name": "get_time", "input": {}}
    ]
})

# 第二步：执行工具，把结果以 user 角色回填
messages.append({
    "role": "user",
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_01AbCd...",   # ← 必须和上面的 id 一致
            "content": "当前时间是 2026年05月06日 00:24:16（local）"
        }
    ]
})
```

如果你跳过第一步直接追加 tool_result，Anthropic API 会返回 `400 Bad Request`，错误信息大意是"找不到对应的 tool_use 消息"。这是初学者最高频的错误之一。

为什么 API 要求这个顺序？因为 Anthropic 的协议设计里，tool_result 消息是通过 `tool_use_id` 与特定的 tool_use block 关联的。API 需要在历史里找到那个 ID，才能理解"这个结果是哪次工具调用的返回"。如果历史里找不到对应的 ID，API 就无法构建完整的因果链——所以拒绝请求。

这个设计并非多此一举。如果 LLM 在一次回复里同时调用了 3 个工具（这在 Ch 5 会遇到），`tool_use_id` 是唯一能让 API 知道"这个结果对应哪个调用"的方式。没有 ID 关联，工具结果就成了孤儿消息。

这是本章采用 `make_assistant_with_tool_use()` 方法封装的原因——让 AgentLoop 里每次工具调用都强制执行这两步，而不是依赖开发者记住顺序。

```python
# provider.py（AnthropicProvider 核心部分，其余见 code/lena-v0.3/provider.py）

class AnthropicProvider:
    def chat(self, messages, tools):
        resp = self.client.messages.create(
            model=self.model, max_tokens=1024,
            system="你是 Lena，一个有帮助的 AI 助手。请用中文回答。",
            messages=messages, tools=tools,
        )
        text_parts, tool_calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name, "inputs": block.input})
        return LLMResponse(
            content=" ".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason,
        )

    def make_assistant_with_tool_use(self, response):
        """把含 tool_use 的响应打包成 assistant 消息（第一步必须先存）。"""
        content = []
        if response.content:
            content.append({"type": "text", "text": response.content})
        for tc in response.tool_calls:
            content.append({"type": "tool_use", "id": tc["id"],
                             "name": tc["name"], "input": tc["inputs"]})
        return {"role": "assistant", "content": content}

    def make_tool_result_message(self, tool_id, result):
        """把工具结果打包成 user 消息（第二步）。"""
        return {"role": "user",
                "content": [{"type": "tool_result",
                              "tool_use_id": tool_id, "content": result}]}
```

### 扩展 3：组装完整 AgentLoop

有了 ToolRegistry 和 Provider，把它们接进骨架里的 AgentLoop：

```python
# lena.py — agent_loop()（完整实现）

def agent_loop(user_input: str, provider, max_turns: int) -> str:
    messages.append({"role": "user", "content": user_input})
    tools = get_tool_schemas()   # ← 每次都拿最新的工具列表

    for turn in range(max_turns):
        # ── 调用 LLM，拿到统一格式的响应 ─────────────────────────────────────
        response = provider.chat(messages, tools)

        if response.tool_calls:
            # ── 关键：先存 assistant（含 tool_use），再追加 tool_result ────────
            messages.append(provider.make_assistant_with_tool_use(response))

            for tc in response.tool_calls:
                result = execute_tool(tc["name"], tc["inputs"])
                print(f"  [工具] {tc['name']}({tc['inputs']}) → {result}")
                messages.append(provider.make_tool_result_message(tc["id"], result))

            continue   # 回到循环顶端，让 LLM 看到工具结果后再决策

        # ── LLM 直接给出文字答复，循环结束 ─────────────────────────────────────
        messages.append({"role": "assistant", "content": response.content})
        return response.content

    return "（已达最大工具调用轮次）"
```

注意 `max_turns` 的作用：这是防御性代码，防止工具调用进入无限循环。一个设计不当的工具或一个特殊的 prompt，可能让 LLM 反复调用同一个工具。10 轮上限保证 agent 不会无限消耗 token。

如果你的场景里单次任务确实需要超过 10 轮工具调用（比如写一份长报告需要反复查资料），可以调大这个数字——但先从小的开始，遇到业务需要再调整，而不是一开始就设置 100。

现在把这三个扩展叠在一起，就是完整的 `lena-v0.3`。可以感受一下整体的数据流：用户输入进来，经过 Config 解析、AgentLoop 驱动、Provider 翻译、ToolRegistry 执行、Memory 追加，最终回复出来。每个模块都在做且只在做自己职责范围内的事。这就是为什么 6 模块共识在三个独立实现里都收敛到了同一个结构——当问题被自然分解时，不同人会独立得出相同的边界划分。

**关于 Memory 的一个直觉**：本章的 Memory 实现是一个 Python 列表，每次 agent_loop 调用后它都在增长。问完"现在几点"后，messages[] 里有 4 条消息；再问一个问题，会追加更多。这意味着随着对话增长，每次 LLM 调用的 token 消耗也在增长——因为你传入的 messages 越来越长。这在短对话里不是问题，但在真实的长任务里会触及 context window 上限。这个问题的解法是 Context Engineering，Ch 8 会详细讲。现在只需要记住：messages[] 是 agent 的全部记忆，也是它的唯一瓶颈。

---

## Beat 6 — 运行验证

### 安装和运行

```bash
cd code/lena-v0.3
pip install -r requirements.txt
cp .env.example .env   # 编辑填入你的 API Key

# Anthropic（需要 ANTHROPIC_API_KEY）
python3 lena.py

# OpenAI（需要 OPENAI_API_KEY）
python3 lena.py --provider openai

# AWS Bedrock（需要配置好 aws credentials，us-west-2）
python3 lena.py --provider bedrock
```

### 真实终端输出（2026-05-06 Bedrock 实测）

```
$ python3 lena.py --provider bedrock

Lena v0.3 ✦ provider=bedrock
输入 'exit' 或按 Ctrl-C 退出

你：现在几点了？
  [工具] get_time({}) → 当前时间是 2026年05月06日 00:24:31（local）
Lena：现在是 **2026年5月6日 00:24**，已经是深夜了哦！🌙
注意休息，有什么需要帮助的尽管告诉我！😊

你：今天是星期几？
Lena：根据刚才获取的时间，**2026年5月6日** 是**星期三**！📅

你：exit
再见！
```

几个值得注意的细节：

**LLM 被调用了两次**。第一次问"几点"时，你能看到 `[工具]` 那行打印——这意味着 AgentLoop 执行了一轮完整的"调工具 → 回填 → 再问 LLM"流程，LLM 第二次调用后才给出最终答复。

**第二个问题 Lena 没有再调工具**。问"星期几"时，没有 `[工具]` 打印行，因为 messages[] 里已经有了时间信息，LLM 直接从上下文推断出星期几。这就是 Memory 模块的价值：减少不必要的重复调用。

**如果你遇到报错**，最常见的两种情况：

- `ANTHROPIC_API_KEY not found`：检查 `.env` 文件是否正确填写，或者 `source .env` 是否生效
- `400 Bad Request: messages: roles must alternate`：通常意味着 messages[] 里出现了连续的同角色消息——检查是否在工具调用时跳过了 `make_assistant_with_tool_use` 这步

### messages[] 在一次对话里的变化

这张快照帮你理解 Memory 模块的实际内容：

```python
# 问完"现在几点"之后，messages[] 的完整状态

messages = [
    # 用户输入
    {"role": "user", "content": "现在几点了？"},

    # LLM 第一次回复（决定调工具）
    {"role": "assistant", "content": [
        {"type": "text",     "text": "我来查一下当前时间…"},
        {"type": "tool_use", "id": "toolu_xxx",
         "name": "get_time", "input": {}}
    ]},

    # 工具结果（以 user 角色回填）
    {"role": "user", "content": [
        {"type": "tool_result",
         "tool_use_id": "toolu_xxx",
         "content": "当前时间是 2026年05月06日 00:24:31（local）"}
    ]},

    # LLM 第二次回复（最终答复）
    {"role": "assistant",
     "content": "现在是 **2026年5月6日 00:24**，已经是深夜了哦！…"}
]
```

4 条消息，2 次 LLM 调用，1 次工具调用。这就是"现在几点"这个任务的完整执行轨迹，全部保留在 messages[] 里。

有了这张快照，你可以反过来思考一个问题：如果你想让 Lena 在下次启动时还"记得"今天的对话，需要做什么？答案很直接——把 messages[] 序列化到磁盘，下次启动时恢复。这就是 Ch 7 的 Memory 模块要做的事情：把这个 Python 列表换成 SQLite 持久化存储。骨架不变，数据层升级。

还有一个细节值得关注：上面的 messages[] 快照里，`role: "user"` 出现了两次——第一次是真正的用户输入，第二次是工具结果的回填。这个"用工具结果冒充用户消息"的设计，是 Anthropic 协议的特意选择。它的含义是：**工具结果在 LLM 眼里，是"外部世界给出的输入"，和用户输入在语义层次上是平级的**。LLM 基于这些输入做决策，而不关心这个输入来自人类键盘还是 Python 函数的返回值。理解了这一点，你就理解了为什么 agent 可以把任意外部数据（传感器读数、数据库查询、网页内容）"注入"到 LLM 的决策上下文里——它们都走同一条路：`role: "user"` + `type: "tool_result"`。

### 本章小结

到这里，你已经从零开始，用大约 150 行 Python（lena.py + provider.py + tools.py 合计）实现了一个完整可运行的 agent。它满足三个核心标准：

1. **能自主决策**：Lena 自己判断什么时候需要调工具，不是你告诉它"现在调 get_time"
2. **能多轮执行**：如果一个任务需要多次工具调用，Lena 的 while 循环支持任意轮次
3. **能跨 provider 运行**：同一份 AgentLoop 代码，切换 `--provider` 参数就能在三家 LLM 上跑

这 3 点，是一个能"自主做任何事"的通用 agent 的最基础骨架。后续所有章节，都是在这个骨架上叠加新能力——更多工具、持久记忆、子任务拆分、长任务恢复——而不是推倒重来。

---

## Beat 6.5 — Hands-on Lab：从零跑通你的第一个 Agent

上面看到了别人的运行结果。现在轮到你自己动手。以下是一个完整的、可复制粘贴的操作序列——从空目录到 Lena 回答你"几点了"，**不超过 5 分钟**。

**前置条件**：Python 3.10+、一个 Anthropic API Key（或 OpenAI Key）。

```bash
# 步骤 1：创建项目目录
mkdir lena-lab && cd lena-lab

# 步骤 2：安装依赖（只有一个）
pip install anthropic

# 步骤 3：设置 API Key
export ANTHROPIC_API_KEY="sk-ant-xxx"   # 替换为你的 key
```

**步骤 4：创建单文件 agent（全部逻辑在一个文件里，便于理解数据流）**

把以下内容存为 `agent.py`：

```python
import anthropic
from datetime import datetime

client = anthropic.Anthropic()
messages = []

TOOLS = [{
    "name": "get_time",
    "description": "获取当前本地时间",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}]

def execute(name, inputs):
    if name == "get_time":
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"未知工具: {name}"

def run(user_input):
    messages.append({"role": "user", "content": user_input})

    for step in range(5):
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512, tools=TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "end_turn":
            return next(b.text for b in resp.content if b.type == "text")

        results = []
        for b in resp.content:
            if b.type == "tool_use":
                r = execute(b.name, b.input)
                print(f"  🔧 {b.name}() → {r}")
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": r})
        messages.append({"role": "user", "content": results})

    return "（超出步数限制）"

if __name__ == "__main__":
    print("Lena Lab ✦ 输入 exit 退出\n")
    while True:
        q = input("你: ").strip()
        if q in ("exit", "quit", ""): break
        print(f"Lena: {run(q)}\n")
```

**步骤 5：运行并观察**

```bash
python3 agent.py
```

你应该看到：

```
Lena Lab ✦ 输入 exit 退出

你: 现在几点
  🔧 get_time() → 2026-05-08 11:23:45
Lena: 现在是 2026年5月8日上午 11:23。

你: 帮我算 7 * 8
Lena: 7 × 8 = 56。

你: exit
```

**关键观察**：
- 第一个问题触发了工具调用（你看到了 🔧 输出）
- 第二个问题 **没有** 触发工具调用——LLM 自己就能算，所以它直接回答了
- 这就是 ReAct 循环的核心智慧：**LLM 自己决定什么时候需要工具**

**步骤 6：加一个你自己的工具**

在 TOOLS 列表里加一个新工具定义，在 execute() 里加一个新分支。比如加一个"随机数"工具：

```python
# 加到 TOOLS 列表
{"name": "random_number", "description": "生成 1-100 的随机整数",
 "input_schema": {"type": "object", "properties": {}, "required": []}},

# 加到 execute() 函数
if name == "random_number":
    import random
    return str(random.randint(1, 100))
```

重新运行，问 Lena "给我一个随机数"——她会调用你的新工具。**AgentLoop 一行没改**。这就是 Tool 统一性支柱的威力。

---

## Beat 6.6 — Troubleshooting：当 Lena 出问题时

跑 agent 代码时遇到报错很正常。以下是新手最高频的 5 个问题和解法：

| 错误信息 | 根因 | 解法 |
|----------|------|------|
| `AuthenticationError: 401` | API Key 无效或未设置 | 检查 `echo $ANTHROPIC_API_KEY`，确认不为空且格式正确 |
| `400: messages: roles must alternate` | messages[] 里出现了连续两个同 role 的消息 | 检查工具调用后是否漏掉了 `messages.append({"role": "user", ...})` |
| `400: tool_use_id not found` | tool_result 里的 ID 和 tool_use 不匹配 | 确认用的是 `b.id`（来自 response），不是自己编的 |
| `TypeError: 'ContentBlock' is not subscriptable` | 把 SDK 对象当 dict 用了 | 用 `b.type` 而不是 `b["type"]`，SDK 返回的是对象不是字典 |
| 循环一直跑不停，token 疯涨 | 没有 `if resp.stop_reason == "end_turn": return` | 加出口条件；同时确认 `max_steps` 有上限 |

**调试三板斧**（按顺序试）：

1. **打印 messages[]**：`import json; print(json.dumps(messages, indent=2, default=str))`——90% 的 bug 在 messages 结构里
2. **打印 stop_reason**：`print(f"stop_reason={resp.stop_reason}")`——确认 LLM 是想调工具还是想结束
3. **用 stub 替换真实 LLM**：让 provider 固定返回一个 tool_use 响应，隔离是 LLM 的问题还是你的代码的问题

如果三板斧都试了还解决不了，回到 Ch 2 的 Wire-Level Trace 部分，对照 messages JSON 格式逐字段检查。bug 永远在数据里，不在逻辑里——agent 代码的逻辑只有 while + if，复杂度全在数据结构的格式匹配上。

---

## Beat 7 — Design Note

> **Why Not LangChain's AgentExecutor?**

LangChain 的 `AgentExecutor`（`langchain>=0.1.0`）做的事情和本章的 `agent_loop()` 完全相同：while 循环 + 工具调用 + 结果回填。区别在于它包了更多层。

**使用 AgentExecutor 的 tradeoff**：

- **调试路径更长**。出了问题，你要在 `AgentExecutor` → `BaseSingleActionAgent` → `LLMChain` → `ChatAnthropic` 这几层里找到真正的 API 调用。本章的代码，整个调用链一个文件内可见。
- **版本稳定性低**。LangChain 在 2023-2024 年经历了从 `langchain` 到 `langchain-core` 的重大重构，AgentExecutor API 也随之变化。用 v0.1 学的代码，到 v0.3 可能已经是另一套写法。以框架 API 为中心组织的知识，有效期很短。
- **抽象遮蔽原理**。Armin Ronacher（Flask 作者）在 Simon Willison 的博客里观察到这个问题："existing SDKs aren't worth adopting yet"——不是说它们不好，而是说理解原理之前就使用框架，会让你对"出了什么问题"没有直觉。

**本章选择裸写的理由**：Anthropic 和 OpenAI 的格式差异只有 4 个字段（见 Beat 5 对比表），用 100 行 provider.py 完全可以封装，不需要引入一个有几万行代码的框架。

**什么时候该用 LangChain？** 当你需要这些现成组件时：LCEL 流式管道、LangSmith 可观测性平台、与大量现成工具集成（SerpAPI、Wikipedia、向量数据库）。这些是 LangChain 真正的价值所在，而不是它的 agent 循环抽象。

**这是一个权衡，不是是非题**。本书不是在说 LangChain 不好用，而是在说：在你理解 agent 的底层运作之前就依赖框架，会让你在出问题时失去定位能力。一旦你能在 100 行代码里构建并调试一个 agent，再用 LangChain 会有质的不同——你知道框架在做什么，出错时知道去哪一层找问题。

用 50 行写通一个 agent，再去看框架，你会更有掌控感。这是在多个 agent 教学课程中观察到的有效路径：先手写原语，再封装框架，顺序很重要——反过来就难以建立真正的理解，出了问题只会重试，不会诊断。

需要诚实说明的是：本章实现的 StubProvider → AnthropicProvider 这个模式，本质是一个**手工版本的提供者抽象**，它在处理单一工具调用时工作得很好，但在边界情况下是不健壮的。例如，如果 LLM 在一次响应里返回了文字和多个 tool_use blocks 的混合内容，当前实现能处理，但如果 tool_use block 本身带了 `cache_control` 字段（Anthropic prompt caching 特性），你的 `make_assistant_with_tool_use` 就需要透传这个字段，否则缓存就失效了。这类细节是 Ch 8 Context Engineering 章才会讲到的内容。当前的实现对本章的教学目标已经足够，不需要追求生产完整性——这就是"先简单后复杂"的原则。

---

---

## 叙事钩子

Lena 现在能回答"现在几点"了。但她只有一个工具，而一个真正有用的助手需要能读文件、执行命令、搜网页。把工具从 1 个扩展到 4 个时，你不希望修改 AgentLoop 的任何一行——这就是**工具注册机制**要解决的问题。下一章，我们设计一个"加工具不改核心"的 ToolRegistry，然后用 4 个工具完成第一次真正意义上的多步任务。

---

## 导航

➡️ **[Ch 4. LLM 底层速查](../ch04-llm-internals/README.md)** — 工程师需要知道的 LLM 最少原理

[← Ch 2. ReAct 循环的秘密](../ch02-react-loop/README.md) · [下一章 →](../ch04-llm-internals/README.md) · [📘 回全书目录](../../README.md)