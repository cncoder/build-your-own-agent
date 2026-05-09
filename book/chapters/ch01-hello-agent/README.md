# 第 1 章：你好，Agent——从一次 API 调用开始

---

## Beat 1 — 路线图

```
全书路线图（26 章）

Ch1 ← 你在这里
 │  心智模型 + Day-0 API 调通
 ▼
Ch2  ReAct 循环原理
 ▼
Ch3  Lena 诞生（50 行，第一个真实工具）
 ▼
Ch4  LLM 底层速查（方法论章）
 ▼
Ch5-12  六大支柱：工具 / 流式 / 记忆 / Context / 规划 / Skills
 ▼
Ch13-18  安全双章 + always-on（Telegram / Heartbeat / Cron）
 ▼
Ch19-25  MCP / Sandbox / Evals / 专用派生 / Browser Agent
```

**本章 arc**：从"LLM 是什么感觉"出发，经过三层心智模型的建立（LLM 是函数 / Agent 是程序 / 工具调用是两者之间的桥梁），最终在第 6 节用 ≤30 行 Python 跑通第一次 API 调用——途中会踩的坑是三家 provider 的格式差异，以及 Bedrock 的模型 ID 不是你想象中的那个名字。

**Lena 版本变化**：本章结束时，Lena 从 v0.0（什么都没有）变成 v0.1——一个能打印一次模型回复的最小骨架。她还不会记忆、不会工具调用、不会循环，但她**活着**。这是本书最重要的一步：从零到有。

本章不上来就塞代码。前 80% 篇幅用来建立心智模型，最后 20% 才跑 API。这个顺序是有意设计的：**直觉先于代码，代码才能被真正理解**（来源：rasbt/LLMs-from-scratch Ch01 的"无代码"策略，R7-G §4 #1）。

> **🧠 聪明度增量（v0.0 → v0.1）**：Lena 第一次向 LLM 发请求并拿到真实回答——从零行代码到能打印模型输出的最小骨架，彻底告别 if/else 硬编码逻辑。这一章教读者把"让语言模型做决策"这个能力长在自己 agent 上的方法。

---

## Beat 2 — 动机：为什么不直接用现成产品？

有一个简单的测试：打开任何一个现成的 LLM 产品，输入"今天深圳有没有下雨"，大概率得到的回答是"我无法查询实时天气"。

这不是模型不够聪明，而是**产品没给它工具**。

现在换一种方式：把同一个模型接上一个 `weather_api` 工具，再问同样的问题——它会调用工具、读到返回值、然后综合成一句话告诉你"今天深圳多云，最高气温 32°C，出门记得备伞"。同一个模型，从"我不知道"变成"我去查一下，帮你整合好"。

这个差距来自**你是否掌控了模型的工具、记忆、和循环**。

用封装好的产品，这三样都是内置、固定的。直接调 API，这三样都由你决定。

具体差距体现在以下几个维度：

| 维度 | 现成产品 | 直调 API |
|------|---------|----------|
| 工具 | 内置、固定，你无法改 | 你来定义，任意可扩展 |
| 记忆策略 | 固定窗口，无法干预 | 你控制压缩方式、持久化策略 |
| 成本 | 订阅制，按座位收费 | 按 token 计价，可分模型分层 |
| 可观测性 | 黑盒，出错难排查 | 每条请求可完整日志，每一步可追踪 |
| 模型选择 | 单一模型或固定套餐 | 随时切换 provider，随时换模型 |
| 集成方式 | 封闭产品，只能用它的接口 | 任意集成进你的系统 |

"成本分层"这一条值得多说一句。在真实的生产系统里，当一个 agent 需要执行数千次子任务时——研究任务、摘要任务、格式化任务——这些子任务不需要用最贵的模型。"主控用大模型做复杂规划、子任务用快模型做简单执行"的分层策略，在保持效果相当的前提下，可以让总账单降低 20-30 倍。这种精细控制，只有直调 API 才能做到。

正如 Andrej Karpathy 所说："We are at the start of the decade of agents — requiring patience and persistent human-in-the-loop oversight."（我们正处在 agent 十年之始。这需要耐心和持续的人在环路监督。）本书不鼓吹"Agent 元年"焦虑，而是用十年视角陪读者把 Lena 从零造出来。

So here we go. 本章的任务是让你走过那道门：不再是模型的用户，而是模型的构建者。

---

## Beat 3 — 理论铺垫

> *纯理论。本节包含三个小节，每节建立一层心智模型。读完这三节，你会知道 LLM 能做什么、不能做什么，以及 agent 是怎么弥补那个"不能"的。*

### 3.1 LLM：一个有截止日期的函数

Convention：**LLM** = Large Language Model，大语言模型；**prompt** = 输入给模型的文字序列；**completion** = 模型生成的输出文字序列。后续统一用这三个词，不再和"输入""输出""回复"混用。

LLM 在工程上最准确的心智模型是**一个函数**——一个给定输入必然产生输出的映射：

```
completion = LLM(prompt)
```

这个函数视角非常有用，因为它帮你排除了很多误解。它有三个本质特征，一旦理解，后面很多"模型为什么做不到 X"都会豁然开朗：

**特征一：无状态。** 每次调用独立，彼此不相知。你在第一次对话里告诉它"我叫张三"，第二次对话开始时它已经完全忘记了。除非你**把上一次对话的内容也放进这一次的 prompt**，否则它什么都不记得。这就是为什么"多轮对话"其实是一个工程问题：程序员要负责把历史消息追加进去，LLM 本身没有记忆机制。记忆是程序员给的，不是模型自带的。

**特征二：单次生成。** 它只产生文字，不执行任何动作。它可以写出"调用天气 API"这句话，但它自己不会真的去调——除非你（作为程序员）读到这几个字，手动执行那个 API，再把结果粘贴回 prompt 告诉它。工具调用能力是程序对 LLM 输出的**解析和执行**，而不是 LLM 自己的能力。

**特征三：知识截止日期。** 训练数据有截止日期，之后发生的事它不知道。这不是 bug，这是它的本质——它是对训练数据的压缩和提取，是一个"学过什么就知道什么"的系统，而不是实时信息系统。今天的天气、今天的股价、刚发布的 API 文档，它都不知道——除非你通过工具帮它去查。

这三个特征合在一起，解释了为什么 LLM 本身不是 agent：**它没有持久性（无状态）、没有主动性（单次生成）、没有时效性（截止日期）**。这三个限制，正是本书接下来要一层层解除的工程问题。

### 3.2 Agent：一个程序，而不是一次调用

Convention：**Agent** = 一个围绕 LLM 构建的程序，通过循环、工具调用和记忆机制，将 LLM 的单次生成能力扩展成多步自主执行；**Tool** = agent 可以在执行过程中调用的外部能力（查时间、读文件、搜网页、执行代码……）；**Memory** = agent 在执行过程中保留和检索信息的机制，包括当前会话历史（短期）和跨会话持久化（长期）。

区分 LLM 和 Agent 的最简单方法：**LLM 是函数，Agent 是程序**。

一个程序有循环、有状态、有副作用，可以执行很多步。一个 agent 的最小形态，就是一个围绕 LLM 的 while 循环：

```
目标输入
    │
    ▼
[LLM 决策]──→ "需要执行工具 X(参数 Y)" ──→ [执行工具 X(Y)] ──→ 结果追加进上下文
    │                                                              │
    ◄──────────────────────────────────────────────────────────────
    │
    ▼
[LLM 决策]──→ "任务完成，输出最终回复"
    │
    ▼
  结束
```

这个循环有一个学术名字：**ReAct 循环**（Reasoning + Acting，推理 + 行动）。在论文 *ReAct: Synergizing Reasoning and Acting in Language Models*（Yao et al., ICLR 2023，arxiv: 2210.03629）中，研究者发现：把 LLM 的思考过程（Thought）和行动步骤（Action）交替呈现，并把工具返回的结果（Observation）喂回给模型，LLM 在复杂任务上的表现显著优于纯生成。你不需要读完这篇论文，只需要知道它验证了一件事：**循环 + 工具 + 观察，是从 LLM 到 agent 的关键结构**。

本章不动手实现这个循环——那是 Ch3 的内容。这里先建立直觉：循环不是"写代码的技巧"，是 agent 区别于 LLM 的**本质差异**。从某种意义上说，agent 工程师的全部工作，都是在设计这个循环的每一个细节：循环什么时候停、工具怎么定义、记忆怎么管理、错误怎么处理。

顺着这个理解，"agent"这个词在领域内被用得相当混乱——有人把加了一个工具的 LLM 叫 agent，有人把整套多模型协作系统叫 agent。Simon Willison（simonwillison.net）对这个词的漂移有过直接批评："most of the people who use it seem to assume that everyone else shares and understands the definition"（2024-12-20）。本书采用 Anthropic 在 *Building Effective Agents*（2024-12-19）中给出的定义作为操作性标准：agent 是"LLMs using tools based on environmental feedback in a loop"——**在循环中根据环境反馈使用工具的 LLM 系统**。这是本书后续所有讨论的共同起点。

### 3.3 三家 API：同一件事，三种说法

本书的贯穿项目 Lena 需要能切换不同的模型 provider，因为在真实工程里你可能因为成本、合规、延迟或功能需要换 provider。在落地代码之前，先理解三家在**格式上**的核心差异——不是哪家更好，而是它们的接口设计反映了不同的工程决策，理解了这些决策，你才不会把格式当成"需要硬记的魔法咒语"。

Convention：**Anthropic** 的 API 叫 Messages API；**OpenAI** 的叫 Chat Completions API；**AWS Bedrock** 的叫 Converse API（通过 boto3 SDK 调用，而不是 HTTP JSON）。三者的**目的相同**（发消息拿回复），**格式不同**。

三家最关键的格式差异集中在两点：

**差异一：system prompt 放在哪。**

System prompt 是给模型设定角色、行为基调的一段指令，相当于"上岗前的岗位培训"。三家对这个字段的处理方式不同：
- Anthropic：`system` 是**顶层独立字段**，传字符串
- OpenAI：`system` 是 `messages` 列表里的**一条消息**，`{"role": "system", "content": "..."}`
- Bedrock：`system` 是**顶层独立字段**，但格式是**列表**，`[{"text": "..."}]`

这个差异不是偶然的——Anthropic 认为 system 和 user 消息在语义上属于不同层次，应该分开；OpenAI 的设计更统一，把所有对话内容都放进同一个列表；Bedrock 因为要兼容多家模型（不只是 Anthropic），用了更通用的结构。

**差异二：模型 ID 怎么写。**

这是最容易踩坑的一处，尤其是 Bedrock：
- Anthropic：直接写模型版本名，如 `claude-sonnet-4-6`（2024 版 `claude-3-5-sonnet-20241022` 已 deprecated，本书采用 2026 Claude 4.X 系列）
- OpenAI：直接写模型名，如 `gpt-4o`
- Bedrock：必须写 **inference profile ID**，如 `us.anthropic.claude-sonnet-4-6`，**不是基础模型 ID**

为什么 Bedrock 不一样？Bedrock 把"inference profile"和"base model"设计成两个不同的实体。Inference profile 是运行时实际调用的那个，有地理区域前缀（`us.` / `eu.` / `ap.`），背后会做负载均衡和跨区域路由。如果你直接传基础模型 ID，Bedrock 会返回"model identifier is invalid"——注意，这不是权限不够，是 ID 格式不对。支持的 inference profile ID 完整列表在 AWS 官方文档的 Bedrock Supported Regions 页面可以找到（来源：[AWS Bedrock cross-region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)）。

理解了这两个差异，下面的代码就不再是"硬记格式"，而是"套用你已经理解的设计逻辑"。这正是本书始终坚持先讲理由再给代码的原因：**理解使代码可记忆；死记使代码随时失效**。

---

## Beat 4 — 脚手架：最小 API 调用骨架

Now it is time to build Lena v0.1. 我们的目标是最小化：一个函数，给它 prompt，它返回模型回复。没有循环，没有工具，没有记忆。只是让 API 跑通。

Let's verify the basic structure by building the smallest possible wrapper around the Anthropic provider:

```python
# lena_v01.py — Lena v0.1 最小骨架（Anthropic 版）
# 依赖：pip install anthropic
# 整个文件 18 行，无任何框架依赖

import anthropic

def chat(prompt: str) -> str:
    """最小 LLM 调用：给 prompt，返回回复文字。"""
    client = anthropic.Anthropic()           # 自动读 ANTHROPIC_API_KEY 环境变量
    response = client.messages.create(
        model="claude-sonnet-4-6",  # 2026 Claude 4.X 系列（2024 版已 deprecated）
        max_tokens=1024,                     # 回复最大 token 数，防无限生成
        messages=[
            {"role": "user", "content": prompt}
        ],
    )
    return response.content[0].text          # 从响应对象里取出文字

if __name__ == "__main__":
    reply = chat("用一句话解释什么是大语言模型")
    print(reply)
```

运行：

```bash
pip install anthropic          # 约 5 秒
export ANTHROPIC_API_KEY="sk-ant-..."
python3 lena_v01.py
```

预期输出（约 2-3 秒后出现，内容因模型而异，1-2 句话）：

```
大语言模型是一种通过海量文本数据训练、能够理解和生成自然语言的人工智能系统。
```

That's it. 这就是 Lena 的起点：一个函数，18 行，一次调用，打印回复。

`max_tokens=1024` 这个参数值得解释一下。LLM 的生成是开放式的——如果你不设上限，它可能生成很长的内容（不是 bug，是 feature）。`max_tokens` 的作用是告诉 API "超过这个长度就停"。对于简单的问答，1024 已经足够；对于需要生成长文档的场景，可以调高到 4096 或更大。这个参数影响的是**单次调用的最大输出长度**，不影响输入的长度。

---

## Beat 5 — 渐进组装：三家 Provider 的完整骨架

从 Beat 4 的 Anthropic 版本出发，依次加上 OpenAI 和 Bedrock，让 Lena v0.1 支持三家 provider 切换。每扩展一步，都有可验证的预期输出。

| 扩展点 | 为何需要 | 如何加 |
|--------|---------|--------|
| OpenAI 支持 | system 字段格式不同，开始感受 provider 抽象的必要性 | 另写 `chat_openai()` 函数，`system` 放进 messages 列表 |
| Bedrock 支持 | inference profile ID + content 是列表格式 | 用 `boto3.client("bedrock-runtime")` 调用 `converse()` |
| provider 路由 | 用一个字典统一入口，命令行指定 provider | `PROVIDERS = {"anthropic": ..., "openai": ..., "bedrock": ...}` |

完整的 Lena v0.1（约 62 行）：

```python
# lena_v01_full.py — Lena v0.1 完整版（三家 provider）
# 依赖：pip install anthropic openai boto3
import os
import sys


def chat_anthropic(prompt: str) -> str:
    """Anthropic Messages API。
    关键格式：system 是顶层字段（字符串）；content 是字符串。
    """
    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def chat_openai(prompt: str) -> str:
    """OpenAI Chat Completions API。
    关键格式：system 在 messages 列表里，role="system"。
    """
    from openai import OpenAI
    client = OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "你是一个有用的 AI 助手，名字叫 Lena。"},
            {"role": "user",   "content": prompt},
        ],
    )
    return response.choices[0].message.content


def chat_bedrock(prompt: str) -> str:
    """AWS Bedrock Converse API（boto3 SDK）。
    关键格式：modelId 必须是 inference profile ID（含 us./eu. 前缀）；
    content 是列表而非字符串。
    """
    import boto3
    client = boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )
    response = client.converse(
        modelId="us.anthropic.claude-sonnet-4-6",  # inference profile ID（2026 Claude 4.X 系列）
        messages=[{
            "role": "user",
            "content": [{"text": prompt}]    # content 是列表，不是字符串
        }],
        inferenceConfig={"maxTokens": 1024},
    )
    return response["output"]["message"]["content"][0]["text"]


PROVIDERS = {
    "anthropic": chat_anthropic,
    "openai":    chat_openai,
    "bedrock":   chat_bedrock,
}


def main():
    provider = sys.argv[1] if len(sys.argv) > 1 else "anthropic"
    if provider not in PROVIDERS:
        print(f"未知 provider：{provider}。可选：{list(PROVIDERS.keys())}")
        sys.exit(1)

    prompt = "用一句话解释什么是大语言模型"
    print(f"[Lena v0.1 | provider={provider}]")
    reply = PROVIDERS[provider](prompt)
    print(f"回复：{reply}")


if __name__ == "__main__":
    main()
```

三家的预期输出（同一 prompt，同一问题，格式相同，内容各有侧重）：

```bash
python3 lena_v01_full.py anthropic
[Lena v0.1 | provider=anthropic]
回复：大语言模型是一种基于 Transformer 架构、通过海量文本预训练的 AI 系统，能够理解和生成自然语言。

python3 lena_v01_full.py openai
[Lena v0.1 | provider=openai]
回复：大语言模型是通过大量文本数据训练的 AI 模型，能够理解和生成自然语言。

python3 lena_v01_full.py bedrock
[Lena v0.1 | provider=bedrock]
回复：大语言模型是一种利用海量文本数据训练的人工智能模型，具备理解和生成自然语言的能力。
```

Along the way，你刚才亲手看到了三家格式差异中最重要的一条：**Bedrock 的 `content` 是列表，不是字符串**。这不是 Bedrock 的 quirk，而是它为了统一支持多模态（文字 + 图片 + 文档）而做的设计——列表里的每个元素可以是 `{"text": "..."}` 也可以是 `{"image": {...}}`。当你后续需要给 Lena 加图片理解能力时，这个设计就变成了优点。

**Bedrock 前置条件**：Bedrock 在运行前需要在 AWS 控制台手动申请模型访问权限：进入 Bedrock 控制台 → Model access → Anthropic Claude 系列 → 申请访问。申请通常即时生效，但需要你的 AWS 账号已经激活对应 region 的 Bedrock 服务。

---

## Beat 6 — 运行验证：Day-0 的三分钟锚点

到这里，Lena v0.1 已经可以完整运行。用最简版本做一次最终验证：

```bash
# 环境准备（约 30 秒）
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# 运行（约 2-3 秒，含网络延迟）
python3 lena_v01.py
```

读者应该看到的具体输出（1 行，约 30-60 个汉字）：

```
大语言模型是一种通过海量文本数据训练的人工智能系统，能够理解和生成自然语言文本。
```

**3 分钟内见到第一条 LLM 回复。** 这是本书的 Day-0 锚点——你已经不再是消费者，而是构建者。

**常见报错诊断**：

| 报错信息 | 根因 | 解决方法 |
|---------|------|---------|
| `AuthenticationError: 401` | API Key 未设置或已过期 | 检查 `ANTHROPIC_API_KEY` 环境变量是否正确设置 |
| `model identifier is invalid` | Bedrock 用了基础模型 ID | 改用 inference profile ID，加 `us.` 前缀 |
| `ModuleNotFoundError: No module named 'anthropic'` | SDK 未安装 | 运行 `pip install anthropic` |
| `botocore.exceptions.NoCredentialsError` | AWS 凭证未配置 | 设置 `AWS_ACCESS_KEY_ID` 和 `AWS_SECRET_ACCESS_KEY` |
| `ConnectionError` | 网络问题（部分地区需要代理） | 检查网络连通性，或配置代理 |

以下是 Lena v0.1 目前已知的局限性——不是 bug，是它现在还不具备的能力：

- **无记忆**：问两次问题，第二次它不记得第一次说了什么
- **无工具**：问"今天是几号"，它只能说"我没有实时信息"
- **无循环**：每次调用独立，它不会主动采取多步行动
- **无错误重试**：API 返回 429（请求过多），程序直接报错退出

这四条局限性对应本书后续四个方向：记忆（Ch8）、工具（Ch3、Ch6）、循环（Ch3）、鲁棒性（Ch7）。Ch3 会解决最关键的那一条——给 Lena 加上第一个工具 `get_time()`，让她真的能告诉你现在几点。

---

## Beat 7 — Design Note

---

> **Design Note：为什么不从框架开始？**
>
> 最显而易见的起点是用 LangChain、LlamaIndex 或 smolagents 这类框架——它们号称"几行代码搭出一个 agent"，GitHub 上都有几万颗星。很多 agent 教程确实从框架开始，因为这让第一个 demo 更快出现。
>
> 框架有三个真实的 tradeoff，在决定是否从框架起步之前你应该了解：
>
> - **版本不稳定**。LangChain 在一年内重构了四次核心 API（来源：HN 讨论，2024-2025 年多次被提及）；v0.1 的写法在 v0.2 完全不适用。当你只会框架 API 而不理解底层时，每次升级都需要重新学，而且你不知道为什么要这样改。
> - **调试困难**。框架把 messages 构建、tool call 解析、retry 逻辑都藏在内部。当 agent 行为异常时，你不知道错在哪一层——是你的 system prompt，还是框架的消息格式转换，还是模型的响应格式，还是工具的返回值解析？Armin Ronacher（Sentry 创始人）在 2025 年明确写道："existing SDKs aren't worth adopting yet. Model differences are significant enough that teams need custom abstractions."（转引自 Simon Willison，simonwillison.net，2025-11-23）框架的抽象层越厚，这个问题越严重。
> - **框架可以后加**。先手写，理解每一层，再决定要不要引入框架——这条路是通的。反过来，先用框架，再拆开理解底层——几乎没有人真的做到，因为框架把你和底层隔离开了。
>
> 本书选择手写 loop 不是认为"框架有罪"，而是**框架是理解之后的选择，不是理解的替代品**。等你读完 Ch3-5，自己写出了 agent loop 的核心，你届时会对任何框架的源码都看得懂——LangChain、smolagents、LlamaIndex 都不例外——也知道在哪里需要框架、在哪里不需要。
>
> 如果你所在的团队已经深度依赖 LangGraph 或 AutoGen，本书的原理层依然完全适用。每章的核心概念可以一一映射到框架的对应模块：本书的 `AgentLoop` = LangGraph 的 `StateGraph`；本书的 `ToolRegistry` = LangChain 的 `tool` 装饰器；本书的 `Memory` = LangGraph 的 `MemorySaver`。原理通了，框架就是薄薄一层 API。

---

## 全书路线图：Lena 的版本演进

这 30 行代码是本书的起点。下面是全书 26 章每个里程碑 Lena 会获得的新能力——从第一章起，你就能看到终态，知道自己在往哪里走：

```
Lena 版本演进（全书 26 章）

v0.0  Ch0   全书导览：agent 的智能演进地图（无代码，建立大局观）
v0.1  Ch1   打印一次模型回复，支持三家 provider（本章）
v0.2  Ch2   理解 ReAct 循环，手绘 Thought/Action/Observation 状态机
v0.3  Ch3   第一个真实工具（get_time），while 循环，能回答"现在几点"
─────────── Part 0 结束：心智模型已建立 ───────────────────────────
v0.4  Ch4   LLM 底层心智模型（方法论章，产物是直觉，不是代码）
v0.5  Ch5   技术选型：provider / 框架 / 记忆方案决策地图
v0.6  Ch6   工具注册表：read_file / write_file / shell / web_search
v0.7  Ch7   SSE 流式输出，并发工具执行（终端里看 Lena"边想边说"）
v0.8  Ch8   SQLite 会话历史 + 文件系统长期记忆，跨会话记住你的偏好
v0.9  Ch9   RAG：向量检索 + 外部知识库，Lena 第一次能"去读"文档
v1.0  Ch10  Context 压缩，Prompt Caching，50 轮对话不炸 token 窗口
v1.1  Ch11  子任务拆分，并发派发子 agent，自主调研任务
v1.2  Ch12  Skills 加载（Markdown 文件 → 可触发的指令集）
─────────── Part 1 结束：六大支柱已建立 ───────────────────────────
v1.3  Ch13  输入层安全：Prompt Injection 防护，权限边界
v1.4  Ch14  执行层安全：沙箱、最小凭证、执行审计
v1.5  Ch15  Gateway 常驻进程，Telegram 收发消息
v1.6  Ch16  MessageBus，channel 热插拔
v1.7  Ch17  Heartbeat，每天 8 点主动推送晨报
v1.8  Ch18  Cron 定时任务，崩溃恢复，跨天任务断点续传
─────────── Part 2 结束：always-on 个人 assistant 完成 ─────────────
v1.9  Ch19  MCP 扩展协议，连接 filesystem / github / brave-search
v2.0  Ch20  Docker 沙箱，容器里安全执行任意代码
v2.1  Ch21  Evals 流水线，CI 每次 PR 自动评分
v2.2  Ch22  可观测性，launchd/systemd 生产部署
v2.3  Ch23  Specialization：一键从 Lena 派生专用 agent
v2.4  Ch24  Browser Agent：自主浏览网页完成任务
v2.5  Ch25  从通用到专用——派生框架全景与工程实践
─────────── 全书结束：generalist agent runtime 完成 ────────────────
```

**六大支柱**是贯穿这张演进图的架构骨架——每一章在往其中一个方向推进，每一个支柱都是"通用 agent"缺一不可的组件：

```
① Tool Universality   任何能力都可以定义为工具（Ch6-7）
   → 把"会 Python"变成工具，把"能搜索网页"变成工具，
     工具是 agent 与外部世界交互的唯一通道。

② Memory              短期记忆 + 长期记忆 + 检索（Ch8-9）
   → 没有记忆的 agent 是失忆者；
     记忆让 agent 能在会话间积累知识，跨天执行复杂任务。

③ Planning            把大目标自主拆解为子步骤（Ch11）
   → 人告诉 agent "调研 X 并写报告"，
     agent 自己决定先查什么、再查什么、怎么综合。

④ Long-horizon        跨小时跨天不丢失状态（Ch17-18）
   → 常驻进程 + 心跳 + cron，让 agent 成为 7×24 的工作者，
     而不是每次都要人工启动的工具。

⑤ Safety              不被 prompt 注入劫持，行为可审计（Ch13-14）
   → 通用 = 强大 = 危险；
     没有安全约束的通用 agent 是不可部署的。

⑥ Specialization      从通用 runtime 派生专用 agent（Ch23-25）
   → 同一套 Lena 核心，换一套 system prompt + 工具集，
     就能变成量化交易 agent / 新闻播报 agent / 代码审查 agent。
```

这六个支柱不是独立的功能点，而是**互相依赖的系统**。Tool Universality 是基础，没有工具的 agent 什么都做不了；Memory 是扩展，没有记忆的 agent 什么都记不住；Planning 是放大器，让 1 个目标变成 N 个有序子步骤；Long-horizon 是持续性保证，让 agent 不只是一次性工具；Safety 是信任基础，没有 Safety 的 agent 不能在生产里跑；Specialization 是最终回报，让你写的通用 runtime 能快速复用到任何场景。

本章是这六个支柱的起点，也是唯一的起点：**先让一条回复打印出来，才有地方叠加一切**。

---

## 三家 API 格式速查

这张表在后续章节会反复用到，先在这里给出完整版：

| 维度 | Anthropic | OpenAI | AWS Bedrock |
|------|-----------|--------|-------------|
| API 名称 | Messages API | Chat Completions | Converse API |
| Python SDK | `anthropic` | `openai` | `boto3` |
| 认证方式 | `ANTHROPIC_API_KEY` 环境变量 | `OPENAI_API_KEY` 环境变量 | AWS SigV4（`AWS_ACCESS_KEY_ID` 等） |
| system 位置 | 顶层字段，字符串 | messages 里 `role="system"` | 顶层字段，列表 `[{"text":"..."}]` |
| user content 格式 | 字符串 | 字符串 | 列表 `[{"text":"..."}]` |
| 模型 ID 格式 | `claude-sonnet-4-6` | `gpt-4o` | `us.anthropic.claude-sonnet-4-6`（inference profile） |
| 回复路径 | `response.content[0].text` | `response.choices[0].message.content` | `response["output"]["message"]["content"][0]["text"]` |
| stop 信号字段 | `stop_reason` | `finish_reason` | `stopReason` |
| token 统计字段 | `usage.input_tokens` | `usage.prompt_tokens` | `usage.inputTokens` |
| 流式支持 | SSE，`event: content_block_delta` | SSE，`data: {...}` | SDK 流式迭代器 |

Ch6 我们会把这张表变成一个 `BaseProvider` 抽象——到时候你会理解，为什么这个抽象必须存在，以及它应该在哪一层做格式转换。

---

## 本章挑战（可选）

1. **格式探索**：把 `lena_v01_full.py` 中的 Anthropic 调用改成带 `system` 参数的版本（`system="你是一个专门回答编程问题的助手"`），对比有 system 和无 system 时模型回复的语气差异。
2. **错误诊断**：故意把 Bedrock 的 `modelId` 改成基础模型 ID（去掉 `us.` 前缀），观察报错信息，然后改回来。这个报错信息会在你实际工作中帮你快速定位问题。
3. **预告题**：思考：如果要让 Lena 支持"第 2 次提问能记住第 1 次的回复"，需要在哪里加什么代码？提示：`messages` 是个列表，每轮追加一条。（Ch3 会给出完整答案）

---

*下一章：ReAct 循环的秘密——把单次问答升级为循环决策，Lena v0.2 等着你。*

---

## 导航

➡️ **[Ch 2. ReAct 循环的秘密](../ch02-react-loop/README.md)** — 从零开始，推理和行动如何交织成 ReAct 循环

[📘 回全书目录](../../README.md)