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

**本章脉络**：从"LLM 是什么感觉"出发，经过三层心智模型的建立（LLM 是函数 / Agent 是程序 / 工具调用是两者之间的桥梁），最终在第 6 节用 ≤30 行 Python 跑通第一次 API 调用——途中会踩的坑是三家 provider 的格式差异，以及 Bedrock 的模型 ID 不是你想象中的那个名字。

**Lena 版本变化**：本章结束时，Lena 从 v0.0（什么都没有）变成 v0.1——一个能打印一次 completion 的最小骨架。她还不会记忆、不会工具调用、不会循环，但她能接受 prompt 并返回 completion，这是后续所有功能的基础。

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

"成本分层"这一条值得多说一句。在真实的生产系统里，当一个 agent 需要执行数千次子任务时——研究任务、摘要任务、格式化任务——这些子任务不需要用最贵的模型。"主控用大模型做复杂规划、子任务用快模型做简单执行"的分层策略，在保持效果相当的前提下，能大幅降低总账单（快模型的 per-token 价格通常是旗舰模型的 1/10 到 1/20）。这种精细控制，只有直调 API 才能做到。

---

## Beat 3 — 理论铺垫

### 3.1 LLM：一个有截止日期的函数

Convention：**LLM**（Large Language Model，大语言模型）= 通过海量文本预训练、能理解和生成自然语言序列的神经网络模型，工程上可以建模为一个确定性映射函数；**prompt**（提示词）= 输入给 LLM 的文本序列，包含用户消息、系统指令和历史对话，是程序员控制模型行为的唯一入口；**completion**（生成结果）= LLM 对给定 prompt 产生的输出文本序列，生成过程是逐 token 采样，而非检索或查找，每次调用产生一段 completion 后即结束。后续统一用这三个词，不再和"输入""输出""回复"混用。

举例：prompt 是 `"用一句话解释什么是大语言模型"`，对应的 completion 是 `"大语言模型是一种通过海量文本训练的 AI 系统，能理解和生成自然语言。"`。同一个 prompt 每次调用可能产生不同的 completion（因为采样有随机性），但通常语义一致。

LLM 在工程上最准确的心智模型是**一个函数**——一个给定输入必然产生输出的映射：

```
completion = LLM(prompt)
```

这个函数视角非常有用，因为它帮你排除了很多误解。它有三个本质特征，一旦理解，后面很多"模型为什么做不到 X"都会豁然开朗：

**特征一：无状态。** 每次调用独立，彼此不相知。你在第一次对话里告诉它"我叫张三"，第二次对话开始时它已经完全忘记了。除非你**把上一次对话的内容也放进这一次的 prompt**，否则它什么都不记得。这就是为什么"多轮对话"其实是一个工程问题：程序员要负责把历史消息追加进去，LLM 本身没有记忆机制。记忆是程序员给的，不是模型自带的。

**特征二：单次生成。** 它只产生 completion，不执行任何动作。它可以写出"调用天气 API"这句话，但它自己不会真的去调——除非你（作为程序员）读到这几个字，手动执行那个 API，再把结果粘贴回 prompt 告诉它。工具调用能力是程序对 LLM 输出的**解析和执行**，而不是 LLM 自己的能力。

**特征三：知识截止日期。** 训练数据有截止日期，之后发生的事它不知道。这不是 bug，这是它的本质——它是对训练数据的压缩和提取，是一个"学过什么就知道什么"的系统，而不是实时信息系统。今天的天气、今天的股价、刚发布的 API 文档，它都不知道——除非你通过工具帮它去查。

这三个特征合在一起，给出了构建 agent 必须解决的工程问题清单：无状态 → 需要外部记忆层维持会话；单次生成 → 需要循环让 LLM 驱动工具执行；知识截止 → 需要工具把实时信息注入 prompt。本书后续每一章，都在往这三个方向前进。

### 3.2 Agent：一个程序，而不是一次调用

有了 LLM 的函数模型，下一个问题自然浮现：怎么把一次 completion 变成能持续做事的系统？答案是在 LLM 外面套一个程序。

Convention：**Agent** = 一个围绕 LLM 构建的程序，通过循环、工具调用和记忆机制，将 LLM 的单次 completion 能力扩展成多步自主执行；**Tool**（工具）= agent 在循环中可以调用的外部能力，每个工具有固定接口：名称（`get_time`）、参数 JSON Schema（`{}`）、返回值（`"2026-05-12 09:30:00"`）——LLM 通过名称+参数发起调用请求，程序执行并把返回值作为下一轮循环的输入；**Memory**（记忆）= agent 在执行过程中保留和检索信息的机制，分为当前会话历史（短期，存在 messages 列表里）和跨会话持久化（长期，存在数据库或文件里）两层。

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

这个循环有一个学术名字：**ReAct 循环**（Reasoning + Acting，推理 + 行动）。Yao et al.（ICLR 2023，arxiv: 2210.03629）发现：把 LLM 的推理（Thought）、行动（Action）与真实工具返回结果（Observation）交替进行，能解决纯 chain-of-thought 容易产生幻觉的问题，让每一步推理锚定在真实执行结果上。核心结论是：**循环 + 工具 + 观察，是从 LLM 到 agent 的关键结构**。

循环不是"写代码的技巧"，是 agent 区别于 LLM 的**本质差异**。agent 工程师的全部工作，都是在设计这个循环的每一个细节：循环什么时候停、工具怎么定义、记忆怎么管理、错误怎么处理。（Ch3 会动手实现这个循环并加入第一个真实工具。）

顺着这个理解，"agent"这个词在领域内被用得相当混乱——有人把加了一个工具的 LLM 叫 agent，有人把整套多模型协作系统叫 agent，语义漂移严重。本书采用 Anthropic 在 *Building Effective Agents*（2024-12-19）中给出的定义作为操作性标准：**agent 是在循环中根据环境反馈使用工具的 LLM 系统**（"LLMs dynamically directing their own processes and tool usage"）。这是本书后续所有讨论的共同起点。

### 3.3 三家 API：同一件事，三种说法

有了 agent = LLM + loop + tool 的心智模型，下一步是让这个 LLM 真正跑起来。在此之前需要解决一个工程前置问题：主流的三家 LLM provider 格式不统一，同一个 "发 prompt 拿 completion" 操作，在三家 SDK 里写法各有差异。Lena 需要能切换不同 provider，因为在真实工程里你可能因为成本、合规、延迟或功能需要换 provider。理解格式差异背后的设计逻辑，才不会把它当成"需要硬记的魔法咒语"。

Convention：**Anthropic** 的 API 叫 Messages API；**OpenAI** 的叫 Chat Completions API；**AWS Bedrock** 的叫 Converse API（通过 boto3 SDK 调用，而不是 HTTP JSON）。三者的**目的相同**（发 prompt 拿 completion），**格式不同**。

三家最关键的格式差异集中在两点：

**差异一：system prompt 放在哪。**

System prompt 是给模型设定角色、行为基调的一段指令，相当于"上岗前的岗位培训"，是 prompt 的一个特殊分层。三家对这个字段的处理方式不同：
- Anthropic：`system` 是**顶层独立字段**，传字符串
- OpenAI：`system` 是 `messages` 列表里的**一条消息**，`{"role": "system", "content": "..."}`
- Bedrock：`system` 是**顶层独立字段**，但格式是**列表**，`[{"text": "..."}]`

这个差异不是偶然的——Anthropic 认为 system 和 user 消息在语义上属于不同层次，应该分开；OpenAI 的设计更统一，把所有对话内容都放进同一个列表；Bedrock 因为要兼容多家模型（不只是 Anthropic），用了更通用的结构。

**差异二：模型 ID 怎么写。**

这是最容易踩坑的一处，尤其是 Bedrock：
- Anthropic：直接写模型版本名，如 `claude-sonnet-4-6`（2024 版 `claude-3-5-sonnet-20241022` 已 deprecated，本书采用 2026 Claude 4.X 系列）
- OpenAI：直接写模型名，如 `gpt-4o`
- Bedrock：必须写 **inference profile ID**，如 `us.anthropic.claude-sonnet-4-6`，**不是基础模型 ID**

Convention：**inference profile ID** = AWS Bedrock 运行时实际调用的模型标识符，带有地理区域前缀（`us.` / `eu.` / `ap.`），背后执行负载均衡和跨区域路由；与之对应的**基础模型 ID**（如 `anthropic.claude-sonnet-4-6`）是模型注册条目，不能直接用于调用——传入基础模型 ID 会报"model identifier is invalid"。支持的 inference profile ID 完整列表见 AWS 官方文档 [Bedrock cross-region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)。

理解了这两个差异，下面的代码就不再是"硬记格式"，而是"套用你已经理解的设计逻辑"。

---

## Beat 4 — 脚手架：最小 API 调用骨架

下面开始构建 Lena v0.1。目标是最小化：一个函数，给它 prompt，它返回 completion。没有循环，没有工具，没有记忆。只是让 API 跑通。

```python
# lena_v01.py — Lena v0.1 最小骨架（Anthropic 版）
# 依赖：pip install anthropic
# 整个文件 18 行，无任何框架依赖

import anthropic

def chat(prompt: str) -> str:
    """最小 LLM 调用：给 prompt，返回 completion 文字。"""
    client = anthropic.Anthropic()           # 自动读 ANTHROPIC_API_KEY 环境变量
    response = client.messages.create(
        model="claude-sonnet-4-6",  # 2026 Claude 4.X 系列（2024 版已 deprecated）
        max_tokens=1024,                     # completion 最大 token 数，防无限生成
        messages=[
            {"role": "user", "content": prompt}
        ],
    )
    return response.content[0].text          # 从响应对象里取出 completion 文字

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

这就是 Lena 的起点：一个函数，18 行，一个 prompt 进去，一个 completion 出来。

Convention：**max_tokens** = 单次 API 调用中 completion 的最大 token 数量上限，超过此限制时模型立即停止生成，返回的 `stop_reason` 字段值为 `"max_tokens"`（而非正常结束的 `"end_turn"`）；它只影响输出长度，不影响输入 prompt 的长度。

| max_tokens 值 | 适用场景 | stop_reason 正常值 |
|--------------|---------|------------------|
| 256 | 极短回答（是/否/一个词） | `"end_turn"` |
| 1024 | 问答、摘要、代码片段 | `"end_turn"` |
| 4096+ | 长文档、完整代码文件 | `"end_turn"` |
| 不设或过小 | ⚠️ 可能截断 completion | `"max_tokens"`（表示被截断） |

生产环境中始终设置合理上限：模型生成是按 token 计费的，不设上限在某些模型上会生成数万 token，产生意外账单。

---

## Beat 5 — 渐进组装：三家 Provider 的完整骨架

从 Beat 4 的 Anthropic 版本出发，依次加上 OpenAI 和 Bedrock，让 Lena v0.1 支持三家 provider 切换。每扩展一步，都有可验证的预期输出。Beat 3 讲的格式差异，现在直接变成代码。

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
    content 是列表而非字符串——这是 Bedrock 为支持多模态（multimodal，
    即同一消息里混合文字、图片、文档等不同类型内容）而做的统一设计。
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
            "content": [{"text": prompt}]    # content 是列表：{"text":...} / {"image":{...}} / {"document":{...}}
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

你刚才亲手验证了 Beat 3 讲的格式差异中最值得关注的一条：**Bedrock 的 `content` 是列表，不是字符串**。这个设计是为了支持 Convention：**multimodal**（多模态）= 在同一条消息里混合多种内容类型——文字（`{"text": "..."}`）、图片（`{"image": {...}}`）、文档（`{"document": {...}}`）可以共存于同一个 `content` 列表中，每种类型是一个独立 block。当前的 Lena v0.1 只用文字，但后续需要给 Lena 加"读截图"能力时，只需在同一个列表里追加一个 `{"image": ...}` block，不需要换 SDK。

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

**常见报错诊断**：

| 报错信息 | 根因 | 解决方法 |
|---------|------|---------|
| `AuthenticationError: 401` | API Key 未设置或已过期 | 检查 `ANTHROPIC_API_KEY` 环境变量是否正确设置 |
| `model identifier is invalid` | Bedrock 用了基础模型 ID | 改用 inference profile ID，加 `us.` 前缀 |
| `ModuleNotFoundError: No module named 'anthropic'` | SDK 未安装 | 运行 `pip install anthropic` |
| `botocore.exceptions.NoCredentialsError` | AWS 凭证未配置 | 设置 `AWS_ACCESS_KEY_ID` 和 `AWS_SECRET_ACCESS_KEY` |
| `ConnectionError` | 网络问题（部分地区需要代理） | 检查网络连通性，或配置代理 |

Lena v0.1 目前已知的局限性——不是 bug，是她现在还不具备的能力：

- **无记忆**：发两次 prompt，第二次她不记得第一次的 completion
- **无工具**：prompt 里问"今天是几号"，她只能说"我没有实时信息"
- **无循环**：每次调用独立，她不会主动采取多步行动
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
> - **版本不稳定**。LangChain 核心 API 在 2023-2024 年间经历了多次重大重构（`langchain` → `langchain-core` + `langchain-community` 拆包，`Chain` → `LCEL` 链式语法切换），v0.1 的写法在 v0.2 完全不适用。当你只会框架 API 而不理解底层时，每次升级都需要重新学，而且你不知道为什么要这样改。
> - **调试困难**。框架把 messages 构建、tool call 解析、retry 逻辑都藏在内部。当 agent 行为异常时，你不知道错在哪一层——是你的 system prompt，还是框架的消息格式转换，还是模型的响应格式，还是工具的返回值解析？框架的抽象层越厚，这个问题越严重。Anthropic 官方文档 *Building Effective Agents*（2024-12-19）明确建议："Start with the simplest solution possible"——先理解每一层再决定要不要引入框架，而不是反过来。
> - **框架可以后加**。先手写，理解每一层，再决定要不要引入框架——这条路是通的。反过来，先用框架，再拆开理解底层——几乎没有人真的做到，因为框架把你和底层隔离开了。
>
> 本书选择手写 loop 不是认为"框架有罪"，而是**框架是理解之后的选择，不是理解的替代品**。等你读完 Ch3-5，自己写出了 agent loop 的核心，你届时会对任何框架的源码都看得懂——LangChain、smolagents、LlamaIndex 都不例外——也知道在哪里需要框架、在哪里不需要。
>
> 如果你所在的团队已经深度依赖 LangGraph 或 AutoGen，本书的原理层依然完全适用。每章的核心概念可以一一映射到框架的对应模块：本书的 `AgentLoop` = LangGraph 的 `StateGraph`；本书的 `ToolRegistry` = LangChain 的 `tool` 装饰器；本书的 `Memory` = LangGraph 的 `MemorySaver`。原理通了，框架就是薄薄一层 API。

---

## 本章挑战（可选）

1. **格式探索**：把 `lena_v01_full.py` 中的 Anthropic 调用改成带 `system` 参数的版本（`system="你是一个专门回答编程问题的助手"`），对比有 system prompt 和无 system prompt 时模型 completion 的语气差异。
2. **错误诊断**：故意把 Bedrock 的 `modelId` 改成基础模型 ID（去掉 `us.` 前缀），观察报错信息，然后改回来。这个报错信息会在你实际工作中帮你快速定位问题。
3. **预告题**：思考：如果要让 Lena 支持"第 2 次 prompt 能记住第 1 次的 completion"，需要在哪里加什么代码？提示：`messages` 是个列表，每轮追加一条。（Ch3 会给出完整答案）
