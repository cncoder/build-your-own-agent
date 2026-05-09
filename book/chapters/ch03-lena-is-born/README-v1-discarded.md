# 第 3 章：Lena 诞生——50 行 Python 写出可跑的 Agent

> **[支柱：Tool 统一性]**
> "任何能力 = 工具。加工具不改核心。"

---

## 本章你将

1. **亲手写出**第一个可运行的 agent loop——`while True` + 工具调用 + 结果回填
2. **理解 MVA 6 模块共识**：Config / Provider / Memory / ToolRegistry / AgentLoop / Skills
3. **看懂 tool_use / tool_result 协议**，并搞清楚 Anthropic 和 OpenAI 两家格式的本质差异
4. **跑通 `lena-v0.3/`**：在终端里问"现在几点"，Lena 会调用真实工具回答你
5. **建立直觉**："agent 的全部秘密"就是一个带工具的 while 循环

---

## 前情提要

上一章，我们把 agent 的工作方式拆解为 **ReAct 循环的状态机**：

```
思考（Thought）→ 行动（Action）→ 观察（Observation）→ 思考…
```

你理解了这是一个**循环**，而不是一次性的 API 调用。你手绘了状态机图，写下了"下次 LLM 调用时，把上一步的观察结果也带上"这个关键洞察。

现在，我们要把那张手绘图变成**真实可跑的 Python 代码**。

---

## 为什么要讲这个

大多数 agent 教程直接让你用 LangChain 或 AutoGen。你跟着做，发现"哦，有效了"——但你不知道为什么。当出了 bug，你在框架层层抽象里找不到北。

Anthropic 在 [Building Effective Agents](https://www.anthropic.com/news/building-effective-agents)（2024-12-19）明确说：

> **"Many agents will be overkill. Start with prompting. If prompting doesn't work, start with the simplest agent architecture. Don't add complexity until you demonstrably need it."**

HuggingFace Agents Course 的批评也恰好切中要害（R4 第 3.2 节）：那门课从概念层直接跳到框架层，**没有用裸 Python 写过 ReAct 就直接包了框架**，结果读者"知其然不知其所以然"。

本章反其道而行之：**先裸写，后升级**。等你亲手写完这 50 行，再去看 LangChain 的源码，你会发现它也只是这 50 行的装饰版本。

---

## 核心概念：agent = LLM + loop + tools

### 最小心智模型

把 agent 想成一台**有三根线插头的机器**：

```
        ┌─────────────────────────────────┐
  用户  │                                 │
  输入 ─┼──▶  Memory (messages[])         │
        │         │                       │
        │         ▼                       │
        │    LLM (Provider)               │
        │         │                       │
        │    ┌────┴────┐                  │
        │    │tool_use?│                  │
        │    └────┬────┘                  │
        │    是   │   否                  │
        │         │    └──▶ 返回文字答复  │
        │         ▼                       │
        │    ToolRegistry                 │
        │    (execute_tool)               │
        │         │                       │
        │    tool_result ──▶ messages[]   │
        │    (循环回去再问 LLM)           │
        └─────────────────────────────────┘
```

**三个关键元素**：
- **LLM**：大脑，决定下一步做什么
- **Loop（while 循环）**：让决策可以不止一步
- **Tools（工具）**：大脑的双手，能做 LLM 自己做不了的事（查时间、搜网页、读文件…）

### ASCII 时序图

一次"现在几点"的完整交互：

```
用户              Lena (while loop)         LLM API         工具
 │                      │                      │              │
 │── "现在几点？" ──────▶│                      │              │
 │                      │──── chat(messages,   │              │
 │                      │       tools=[...]) ──▶│              │
 │                      │                      │              │
 │                      │◀── stop_reason=       │              │
 │                      │    "tool_use"         │              │
 │                      │    content=[{         │              │
 │                      │      type:"tool_use", │              │
 │                      │      name:"get_time", │              │
 │                      │      id:"toolu_xxx"   │              │
 │                      │    }]                 │              │
 │                      │                      │              │
 │                      │──── execute_tool() ──────────────────▶│
 │                      │◀── "当前时间是 00:24" ──────────────────│
 │                      │                      │              │
 │                      │── messages.append(   │              │
 │                      │   tool_result)        │              │
 │                      │                      │              │
 │                      │──── chat(messages) ──▶│              │
 │                      │◀── stop_reason=       │              │
 │                      │    "end_turn"         │              │
 │                      │    content=[text]     │              │
 │                      │                      │              │
 │◀── "现在是 00:24..." ─│                      │              │
```

**关键点**：整个过程 LLM 被调用了**两次**。第一次决定要调工具，第二次拿着工具结果给出最终答复。这个模式，无论工具调用多少次，都是一样的逻辑。

### MVA 6 模块共识

通过对比三个 nano 级实现（nano-claw TS / nanoClaw Py / Tian-NanoClaw），R2 报告提炼出了**最小可行 Agent 的 6 模块共识**：

| 模块 | 职责 | lena-v0.3 位置 |
|---|---|---|
| **Config** | 读取 .env、命令行参数 | `lena.py` argparse + dotenv |
| **Provider** | 统一多家 LLM API 差异 | `provider.py` |
| **Memory** | 管理 messages[] 对话历史 | `lena.py` messages 列表 |
| **ToolRegistry** | 注册工具 + 执行工具 | `tools.py` TOOLS 列表 |
| **AgentLoop** | while 循环 + 决策 | `lena.py` agent_loop() |
| **Skills** | 可复用能力包（SOP） | 本章暂不使用，Ch 9 展开 |

> **引用**：nano-claw `src/agent/loop.ts`（247 行）/ nanoClaw `core/agent.py`（Agent.run()，约 155 行）/ Tian-NanoClaw `src/agent_app.py` AgentSystem。三者的 6 模块对应关系见 R2 第 2 节。

这 6 个模块就是**所有 agent 框架（LangChain、CrewAI、AutoGen）的公分母**。框架只是在这 6 个模块外面加了一层更漂亮的 API，底层逻辑完全相同。

---

## 动手写

我们按顺序实现这 6 个模块。每个模块尽量短，让你一眼能看完。

### 第一步：工具（ToolRegistry）

工具是 agent 最核心的扩展点。**Tool 统一性**（六大支柱第一条）的核心思想是：任何外部能力都可以包装成工具，而 agent loop 的核心代码不需要改变。

一个工具 = 两件东西：
1. **schema**：告诉 LLM"这个工具叫什么、做什么、需要哪些参数"
2. **handler**：真正执行的 Python 函数

```python
# tools.py（核心片段）

TOOLS = [
    {
        "schema": {
            "name": "get_time",
            "description": "获取当前本地时间。当用户问'现在几点'、'今天几号'等时间相关问题时调用。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "timezone": {"type": "string", "description": "时区说明，默认 'local'"}
                },
                "required": [],
            },
        },
        "handler": get_time_handler,
    }
]
```

**为什么 schema 这么重要？**

LLM 无法直接调用函数。它能做的，是在回复里输出一个特殊的 JSON 块，告诉你"我想调用这个函数，参数是这些"。你的代码读到这个 JSON 块，调用真正的函数，把结果返回给 LLM。

LLM 能做出明智的决策（知道什么时候该调用 get_time），是因为你在请求里附上了 schema——这相当于你把"工具使用说明书"传给了 LLM。

**`input_schema` 就是 JSON Schema**。这个格式是标准化的，你可以用 Pydantic 自动生成（Ch 4 会讲）。

### 第二步：Provider 适配层

这是本章最值得花时间看的地方，因为**Anthropic 和 OpenAI 的 tool_use 协议是两套不同的格式**，搞混了会直接报错。

#### Anthropic 格式

```python
# LLM 返回（包含工具调用）：
response.content = [
    {"type": "text", "text": "我来查一下当前时间…"},
    {
        "type": "tool_use",         # ← Anthropic 独有的 block 类型
        "id": "toolu_01AbCd...",    # ← 用于后续 tool_result 的关联 ID
        "name": "get_time",
        "input": {}                 # ← 参数，Anthropic 叫 input（不是 arguments）
    }
]

# 工具结果回填（回到 messages 里）：
{
    "role": "user",               # ← 注意：工具结果以 user 身份回填
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_01AbCd...",   # ← 与上面的 id 对应
            "content": "当前时间是 2026年05月06日 00:24:16"
        }
    ]
}
```

#### OpenAI 格式

```python
# LLM 返回（包含工具调用）：
message.tool_calls = [
    ToolCall(
        id="call_abc123",              # ← OpenAI 的 id
        type="function",
        function=Function(
            name="get_time",
            arguments='{}'             # ← 参数是 JSON 字符串，Anthropic 是 dict
        )
    )
]

# 工具结果回填（回到 messages 里）：
{
    "role": "tool",              # ← 注意：OpenAI 有专门的 "tool" 角色
    "tool_call_id": "call_abc123",   # ← 字段名也不同
    "content": "当前时间是 2026年05月06日 00:24:16"
}
```

**两家格式差异汇总**：

| 对比项 | Anthropic | OpenAI |
|--------|-----------|--------|
| 工具调用位置 | `content[]` 数组里的 block | 顶层 `tool_calls` 字段 |
| 参数字段名 | `input`（dict） | `arguments`（JSON 字符串） |
| 工具结果角色 | `user`（携带特殊 content） | `tool`（独立角色） |
| 关联 ID 字段 | `tool_use_id` | `tool_call_id` |

这就是为什么 provider.py 需要封装两套 `make_tool_result_message()` 方法——让 agent_loop 的核心代码不需要知道自己在用哪家 API。

> **参考**：nanoClaw `core/llm.py:571-578` `_adapt_for_anthropic()` 完整转换逻辑；`llm.py:18-38` `_parse_openai_usage()` 三家 cache token 字段统一处理。

#### 三家 Provider 实现

`provider.py` 实现了三个类：

```python
class AnthropicProvider:   # 原生 Anthropic API
class OpenAIProvider:      # OpenAI / 兼容接口（如 DeepSeek）
class BedrockProvider:     # AWS Bedrock（通过 anthropic SDK 的 Bedrock 后端）

def create_provider(name: str):  # 工厂函数
```

每个 Provider 必须实现三个方法：
- `chat(messages, tools)` → `LLMResponse`：调用 LLM
- `make_assistant_with_tool_use(response)` → dict：把含工具调用的响应转成 messages 格式
- `make_tool_result_message(tool_id, result)` → dict：把工具结果转成 messages 格式

### 第三步：Memory（对话历史）

本章的 Memory 实现极简——一个 Python 列表：

```python
# lena.py
messages: list[dict] = []
```

这已经足够了，因为 LLM 的所有上下文都在 messages 里。`agent_loop()` 每次运行都往这个列表里追加消息：用户消息、assistant 消息、tool_result 消息。下次用户输入时，LLM 能看到完整历史。

> **扩展方向**：Ch 6 会把这个列表换成 SQLite 持久化的 MemoryStore（参考 nanoClaw `memory/store.py`）。届时 agent 能"记住"跨会话的信息。

### 第四步：AgentLoop 核心

这是全章的重点。把上面三个模块组合起来：

```python
# lena.py — agent_loop()（完整版）

def agent_loop(user_input: str, provider, max_turns: int) -> str:
    messages.append({"role": "user", "content": user_input})
    tools = get_tool_schemas()

    for turn in range(max_turns):
        # ── 调用 LLM ──────────────────────────────────────────────────────────
        response = provider.chat(messages, tools)

        if response.tool_calls:
            # ── 有工具调用：先把 assistant 消息（含 tool_use block）存入 messages
            messages.append(provider.make_assistant_with_tool_use(response))

            # ── 执行每个工具，把结果回填 messages ──────────────────────────────
            for tc in response.tool_calls:
                result = execute_tool(tc["name"], tc["inputs"])
                print(f"  [工具] {tc['name']}({tc['inputs']}) → {result}")
                messages.append(provider.make_tool_result_message(tc["id"], result))

            # 继续循环，让 LLM 看到工具结果后给出最终回复
            continue

        # ── 无工具调用：LLM 直接给出文字答复，循环结束 ─────────────────────────
        messages.append({"role": "assistant", "content": response.content})
        return response.content

    return "（已达最大工具调用轮次）"
```

**逐行解读**：

| 行 | 作用 |
|---|---|
| `messages.append(user)` | 把用户输入存入 Memory |
| `provider.chat(messages, tools)` | 带着完整历史和工具列表问 LLM |
| `if response.tool_calls:` | LLM 想调工具 |
| `make_assistant_with_tool_use(response)` | 把 LLM 的工具调用决策存入 Memory |
| `execute_tool(name, inputs)` | 真正运行工具 |
| `make_tool_result_message(id, result)` | 把工具结果存入 Memory |
| `continue` | 回到循环顶端，再次问 LLM |
| `return response.content` | LLM 不再调工具，返回最终答复 |

**最关键的一步**，往往被初学者忽略：

```python
messages.append(provider.make_assistant_with_tool_use(response))
```

你**必须先把"LLM 说要调工具"这个消息存入 messages**，然后再添加工具结果。如果少了这一步，API 会报错——因为它看到一个 tool_result 但不知道对应的是哪次工具调用。

> **参考**：nano-claw `src/agent/loop.ts:136-175`（工具调用处理逻辑）；nanoClaw `core/agent.py:222-250`（并行工具执行 + tool_result 回填）。

### 第五步：Config 和 REPL

```python
# lena.py — main()

def main():
    args = parse_args()            # Config：--provider, --max-turns
    provider = create_provider(args.provider)  # Provider 工厂

    print(f"Lena v0.3 ✦ provider={args.provider}")
    print("输入 'exit' 或按 Ctrl-C 退出\n")

    while True:                    # REPL 主循环
        user = input("你：").strip()
        if user.lower() in ("exit", "quit"):
            break
        reply = agent_loop(user, provider, args.max_turns)
        print(f"Lena：{reply}\n")
```

注意：这里有**两层循环**：
- 外层 `while True`：REPL 持续接受用户输入
- 内层 `for turn in range(max_turns)`：单次 agent 决策循环（工具调用可能多轮）

每次用户输入触发一次 `agent_loop()`，工具调用和结果回填都在 `agent_loop()` 内部完成。

---

## 跑通的样子

### 安装和运行

```bash
cd code/lena-v0.3
pip install -r requirements.txt
cp .env.example .env   # 编辑填入你的 API Key

# Anthropic
python lena.py

# OpenAI
python lena.py --provider openai

# AWS Bedrock（需要配置好 aws credentials）
python lena.py --provider bedrock
```

### 真实终端输出（2026-05-06 Bedrock 实测）

```
$ python lena.py --provider bedrock

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

**注意第二个问题**：问"星期几"时，Lena **没有再次调用 `get_time`**。因为 messages[] 里已经有了时间信息，LLM 直接从上下文推断出星期几。这就是 Memory 模块的价值——减少不必要的工具调用。

### 理解 messages[] 的变化

一次"现在几点"的完整会话，messages[] 的变化如下：

```python
# 初始状态
messages = []

# 1. 用户输入后
messages = [
    {"role": "user", "content": "现在几点了？"}
]

# 2. LLM 第一次调用后（决定调工具）
messages = [
    {"role": "user", "content": "现在几点了？"},
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "我来查一下当前时间…"},
            {"type": "tool_use", "id": "toolu_xxx", "name": "get_time", "input": {}}
        ]
    }
]

# 3. 工具执行后，回填结果
messages = [
    {"role": "user", "content": "现在几点了？"},
    {"role": "assistant", "content": [...]},   # 上面
    {
        "role": "user",                         # Anthropic 用 user 回填工具结果
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_xxx", "content": "当前时间是 2026年05月06日 00:24:16（local）"}
        ]
    }
]

# 4. LLM 第二次调用后（给出最终答复）
messages = [
    ... (同上),
    {"role": "assistant", "content": "现在是 **2026年5月6日 00:24**，已经是深夜了哦！…"}
]
```

---

## Design Note：为什么不直接用 LangChain？

> **这是一个权衡，不是一个是非题。**

LangChain 2022 年诞生时，Anthropic 的 tool_use 协议还没标准化，OpenAI 的 function calling 也刚出来。LangChain 做了一层抽象，帮你屏蔽各家差异，是当时的合理选择。

**现在的问题**：

1. **抽象遮蔽调试路径**：用 LangChain 调工具时，如果出了问题，你需要扒开 `LLMChain → BaseLLM → ChatAnthropic → …` 好几层才能找到真正的 API 调用。而我们的代码，整个调用链一眼可见。

2. **Anthropic 官方建议**：在 Building Effective Agents 里，Anthropic 明确建议开发者"**直接调 API，不要过早引入框架**"。框架带来的抽象成本在简单场景下远超收益。

3. **两家格式差异其实不大**：看完本章，你会发现 Anthropic 和 OpenAI 的格式差异只有 4 点，用 100 行代码完全可以封装。不需要引入一个有几万行代码的框架。

**什么时候该用 LangChain？**

当你需要这些现成组件时：LCEL 流式管道、LangSmith 可观测性、大量已集成的工具（如 SerpAPI、Wikipedia）、与 RAG 模块的配合。这些是 LangChain 的真正价值所在，而不是它的 agent 循环抽象。

**Sourcebot 的案例**（R3 第二节"Agentic Loop 设计"）：这个团队刻意避开向量嵌入和 multi-agent graph，选择最简路径，发现"单 agent 架构减少幻觉"。这和 Anthropic 铁律一致：**start simple, add complexity only when it demonstrably improves outcomes**。

---

## 本章小结

1. **agent = LLM + loop + tools**。掌握了这个三元组，你就掌握了所有 agent 框架的本质。

2. **MVA 6 模块**（Config / Provider / Memory / ToolRegistry / AgentLoop / Skills）是行业共识。这 6 个模块在 nano-claw、nanoClaw、OpenClaw 三个不同实现里都能找到对应体。

3. **tool_use 协议是 agent 的神经接口**。Anthropic 和 OpenAI 格式不同，但都遵循同一个模式：LLM 输出工具调用意图 → 代码执行工具 → 结果回填给 LLM。

4. **messages[] 是唯一的真相源**。agent 的所有状态——用户输入、LLM 决策、工具结果——都在这个列表里。Memory 管理的核心就是管理这个列表。

5. **先裸写，后框架**。用 50 行代码写通一个 agent，再去看框架，你会更有掌控感。这是 DeepLearning.AI 课程的"先手写再框架"策略（R4 第 3.3 节），被认为是目前最好的 agent 教学方式。

---

## 延伸阅读

| 资料 | 位置 | 内容 |
|------|------|------|
| MVA 6 模块共识 | R2 第 2 节（`docs/research/R2-openclaw-nanoclaw-comparison.md:19-31`） | 三个 nano 实现的模块对比表 |
| nano-claw AgentLoop | `~/code/ccdev/agent-study/nano-claw/src/agent/loop.ts:91-211` | TS 版最小 agent loop（247 行完整实现） |
| nanoClaw Agent.run() | `~/code/ccdev/agent-study/nanoClaw/nanoclaw/core/agent.py:102-285` | Python 版完整实现（含并行工具调用、escalation）|
| Anthropic tool_use 官方文档 | https://docs.anthropic.com/en/docs/build-with-claude/tool-use | 工具调用完整协议规范 |
| Building Effective Agents | https://www.anthropic.com/news/building-effective-agents | 五大工作流模式 + 框架慎用论 |
| 三家 cache token 字段差异 | nanoClaw `core/llm.py:18-38` | OpenAI/DeepSeek/Anthropic 缓存 token 字段映射 |

---

## 下一步

Lena 现在能回答"现在几点"了。但她只有一个工具，没有持久记忆，也不能并发执行多个工具。

**Ch 4**：给 Lena 加上 `read_file` / `write_file` / `shell` / `web_search` 四个工具，并设计一个"加工具不改核心"的注册机制——这就是**Tool 统一性支柱**的完整实践。

**Ch 6**：把 `messages[]` 列表换成 SQLite 持久化，让 Lena 有"昨天"——这就是 **Memory 支柱**的起点。
