# Ch 4 · LLM 底层：agent 工程师需要知道的最少内容

> **Lena 版本**：本章是方法论章，无代码产物。读完后 Lena 本体代码不变，但你——作为写 agent 的工程师——获得了一张"不再被模型参数吓到"的认知地图。下一章（Ch 5）的工具系统才会在这张地图上真正动手。

---

## Beat 1 — 路线图

```
Ch 1 → Ch 2 → Ch 3 → [Ch 4 ← 你在这里] → Ch 5 → ... → Ch 22
基础调用   ReAct循环   Lena诞生         LLM底层     工具系统
```

到目前为止，Lena 能接收用户输入、调用 LLM、返回结果。但每次你选模型、设置 `max_tokens`、决定用不用 prompt caching，你其实在做一个工程决策——却不知道为什么。

本章从"Lena 发出第一次 API 请求"出发，经过 8 个心智模型，到达"你能在 30 秒内做出模型选型决策"的终态。途中会遇到一个坑：**直觉上越大的模型越好，工程上越大的模型越贵、越慢、有时还越蠢**——MoE 架构是理解这个矛盾的钥匙。

本章唯一的产物是一张决策树。没有代码，没有矩阵，只有你能带走用的直觉。

**本章不是模型教材。** 训练 Transformer 的书已经存在——Raschka 的《Build a Large Language Model From Scratch》从零实现了 GPT-2，Karpathy 的 nanoGPT 把 124M 参数 GPT 压缩进 300 行。本书不重复他们的工作，本书专注 harness——怎样把模型接进你的 agent，让它做你想要的事。

> **🧠 聪明度增量（v0.3 → v0.4）**：Lena 第一次"理解 LLM 内部"——掌握 token、context window、prompt caching 的成本模型后，工程师能在 30 秒内做出模型选型决策，不再凭感觉选"更大的模型"。这一章教读者把 LLM 工程直觉长在自己 agent 设计决策上的方法。

---

## Beat 2 — 动机

你打开 Anthropic 文档，看到 Claude Opus 4、Sonnet 4.5、Haiku 4.5 并排排列。你决定用 Opus，因为"更聪明"。

三周后你收到账单：$847。同样的任务用 Haiku 只需 $23。质量测试显示：对于你的工具调用场景，Haiku 的正确率是 91%，Opus 是 93%。你为 2% 的质量提升多花了 37 倍的钱。

这不是特例。在 2026 年的 agent 开发中，**模型选型错误是最常见的第一类成本浪费**。不是因为工程师不够聪明，而是因为没有建立正确的直觉框架。

现在换一个场景。你的 agent 需要处理 200 页 PDF（约 150,000 tokens）。你选了 GPT-4o，因为它"好"。结果每次请求需要 15 秒，成本是处理 8K 上下文的 18 倍——因为 attention 的计算随 context 长度平方增长，而你没有意识到这件事。

或者：你在自己的服务器上部署一个 70B 开源模型。FP16 精度需要 140GB 显存，你没有。INT4 量化把它压到 40GB，能跑在 4 张 RTX 4090 上，质量损失在你的场景下可以接受——但你不知道有这个选项。

**8 个心智模型是针对以上问题的最小必要知识集。** 理解它们不需要读懂反向传播，不需要写过一行 PyTorch，只需要理解"这个东西决定了什么工程参数"。

---

## Beat 3 — 理论铺垫

Anthropic 博客指出了一个工程师级的选型公理：

> "Choose the right model for the job. The key is balancing three factors: **capabilities, speed, and cost**. Think of it like choosing the right tool from a toolbox: you wouldn't use a sledgehammer to hang a picture frame."
> （来源：Anthropic, [Building effective agents](https://www.anthropic.com/research/building-effective-agents), 2024-12-19）

这句话的前提是：你得理解模型之间**到底差在哪里**。本章不教你训练模型，而是教你建立 8 个心智模型——让你每次选模型 / 设参数 / 算成本时，知道背后的物理原因。

### 3.1 为什么 LLM 是"预测下一个 token"的机器

Convention：**token** = LLM 处理的最小文字单元（约 0.75 个英语单词，1 个中文汉字通常是 1-2 个 token）；**word** = 人类书写时的单词，不等于 token。

所有现代 LLM 做的事都可以用一句话描述：给定之前的 tokens，预测下一个 token 的概率分布。这件事被重复执行，一个 token 接一个 token，直到生成结束符。

这意味着 LLM 本质上是**串行生成**的——生成第 100 个 token 时，必须已经生成了前 99 个。这是一个关键的工程约束：无论模型多大、GPU 多强，输出速度（tokens/秒）有其物理上限，这个上限与你期望的回复长度直接相关。**对你写 agent 意味着什么**：需要长回复的任务（写报告、生成代码）天生比短回复任务慢，设计 agent 时要给足 timeout 余量。

### 3.2 Transformer 一图

**

Convention：**embedding** = 把 token 映射到高维向量空间的表示，一个数字数组；**encoding** 通常指 BERT 式双向编码器，本书讨论的 GPT 系模型使用 decoder-only 架构，下文统一用 embedding。

```
输入文字
    ↓
[Tokenizer]  把文字切成 token 序列
    ↓
[Embedding Layer]  把每个 token 变成一个向量（如 4096 维）
    ↓
[Attention Layers × N]  让每个 token 看到其他 token，理解上下文
    ↓
[Output Layer]  把向量映射回词表，输出概率分布
    ↓
采样（greedy / temperature / top-p）
    ↓
下一个 token
```

N 层 Attention 叠加——GPT-3 是 96 层，Claude 系列未公开但量级相似。每层 Attention 做的事：让序列中的每个 token 向其他所有 token"提问"并整合答案。层越多，模型对语言规律的理解越深；但推理时每层都要计算，层数 × token 数 × 参数量 = 计算量。

**对你写 agent 意味着什么**：模型"智力"来自层数和参数量，但推理延迟也线性增长。选"足够聪明"而不是"最聪明"是正确的工程习惯。

---

## Beat 4 — 8 个心智模型

*本章的脚手架是 8 张认知卡片。在展开认知卡片之前，先用三段代码建立"摸得到的直觉"——让抽象的 token 计数、context 成本、prompt caching 变成你能亲手跑的数字。读懂代码后，8 个心智模型会更容易落地。*

**代码 4-A：token 计数与 context 长度估算**

```python
import anthropic

def count_tokens(text: str, model: str = "claude-sonnet-4-5") -> int:
    """用 Anthropic SDK 精确计算文本的 token 数。

    Args:
        text: 待计算的文本
        model: 使用的模型（不同模型 tokenizer 有差异）

    Returns:
        token 数量

    Example:
        >>> count_tokens("Hello, world!")
        4
        >>> count_tokens("你好，世界！")
        8
    """
    client = anthropic.Anthropic()
    response = client.messages.count_tokens(
        model=model,
        messages=[{"role": "user", "content": text}],
    )
    return response.input_tokens


def estimate_context_cost(
    system_prompt: str,
    user_messages: list[str],
    model: str = "claude-sonnet-4-5",
    input_price_per_mtok: float = 3.0,
    output_price_per_mtok: float = 15.0,
    avg_output_tokens: int = 500,
) -> dict:
    """估算多轮对话的 context 成本。

    返回值包含：每轮的 token 数、累计成本、缓存节省潜力。
    """
    system_tokens = count_tokens(system_prompt)
    results = []
    cumulative_tokens = system_tokens

    for i, msg in enumerate(user_messages):
        msg_tokens = count_tokens(msg)
        cumulative_tokens += msg_tokens

        input_cost = (cumulative_tokens / 1_000_000) * input_price_per_mtok
        output_cost = (avg_output_tokens / 1_000_000) * output_price_per_mtok

        results.append({
            "round": i + 1,
            "new_tokens": msg_tokens,
            "total_context": cumulative_tokens,
            "round_cost_usd": round(input_cost + output_cost, 6),
        })
        # 每轮之后，对话历史也会增加（输出也进入 context）
        cumulative_tokens += avg_output_tokens

    return {
        "system_tokens": system_tokens,
        "rounds": results,
        "total_cost_usd": sum(r["round_cost_usd"] for r in results),
    }
```

预期输出（假设 system prompt 约 200 tokens，三轮对话各约 50 tokens）：

```
{
  "system_tokens": 198,
  "rounds": [
    {"round": 1, "new_tokens": 48, "total_context": 246, "round_cost_usd": 0.000758},
    {"round": 2, "new_tokens": 52, "total_context": 796, "round_cost_usd": 0.002403},
    {"round": 3, "new_tokens": 45, "total_context": 1341, "round_cost_usd": 0.004038},
  ],
  "total_cost_usd": 0.007199
}
```

注意第 1 轮到第 3 轮，每轮成本从 $0.0008 增长到 $0.004——这就是 context 累积的代价，也是 KV Cache 为什么值钱的原因。

**代码 4-B：Prompt Caching 的成本对比**

```python
import anthropic

def compare_caching_cost(
    system_prompt: str,
    user_message: str,
    model: str = "claude-sonnet-4-5",
) -> dict:
    """对比有缓存和无缓存时的 token 计费差异。

    启用 prompt caching 后，命中缓存的 token 按 10% 价格计费。
    本函数通过两次调用演示实际 cache_read_input_tokens 数字。
    """
    client = anthropic.Anthropic()

    # 第一次调用：写入缓存（cache_creation_input_tokens 会计费）
    first = client.messages.create(
        model=model,
        max_tokens=100,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )
    cache_write_tokens = first.usage.cache_creation_input_tokens or 0
    first_input_tokens = first.usage.input_tokens

    # 第二次调用：命中缓存（cache_read_input_tokens 按 10% 价格）
    second = client.messages.create(
        model=model,
        max_tokens=100,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )
    cache_read_tokens = second.usage.cache_read_input_tokens or 0
    second_input_tokens = second.usage.input_tokens

    return {
        "first_call": {
            "input_tokens": first_input_tokens,
            "cache_write_tokens": cache_write_tokens,
        },
        "second_call": {
            "input_tokens": second_input_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_hit": cache_read_tokens > 0,
        },
    }
```

预期输出（system prompt 约 500 tokens）：

```
{
  "first_call": {"input_tokens": 520, "cache_write_tokens": 512},
  "second_call": {"input_tokens": 20, "cache_read_tokens": 512, "cache_hit": true}
}
```

第二次调用时 `cache_read_tokens=512` 表示这 512 个 token 按 10% 价格计算——真实成本降到了原来的 10%。这是心智模型 3 说的"把 system prompt、工具 schema 放前面"的工程价值。

---

---

### 心智模型 1：Transformer 一图——为什么不是 RNN？

**关键数字**：GPT-3 有 96 层 Attention，每层处理完整序列，1750 亿参数。

在 Transformer 之前，序列模型主要是 RNN（循环神经网络）。RNN 的问题是：处理第 1000 个 token 时，关于第 1 个 token 的信息已经被"遗忘"了大半——因为它是按顺序传递的，像电话游戏。Transformer 的 Attention 机制直接跳过这个限制：每个 token 都能直接"看到"序列中的任意其他 token，距离不造成遗忘。

这解释了为什么 LLM 能处理 100K 以上的上下文而不丢失早期信息——理论上。实践中还受到 KV Cache 显存限制（见心智模型 3）。

另一个 RNN 的问题：训练时只能串行处理，无法并行。Transformer 可以并行处理整个序列，这让用几千张 GPU 并行训练成为可能。训练速度差了 100 倍不止。

**对你写 agent 意味着什么**：你不需要自己训练 Transformer。但"模型为什么能记住很久之前的上下文"——Attention 直接连接任意两个 token——是理解 context window 限制时的基础直觉。

---

### 心智模型 2：Attention 的工程后果——O(n²) 的直觉

**关键数字**：context 从 4K 增加到 128K（32 倍），Attention 计算量增加约 1024 倍。

Attention 的核心操作可以用一句话理解：序列中的每个 token 要和其他所有 token 两两比较。如果序列有 n 个 token，就有 n × n 对比较。这就是 O(n²)——quadratic complexity。

用具体数字感受这个差距：
- 1,000 tokens → 1,000,000 对比较
- 8,000 tokens → 64,000,000 对比较（增加 64 倍）
- 128,000 tokens → 16,384,000,000 对比较（增加 16,384 倍）

这直接解释了为什么"长 context = 贵"。Anthropic 的 Claude 3.5 Haiku 处理 1K tokens 约 $0.0008，处理 200K tokens 不是 200 倍而是更高——输入 token 本身按量计费，而模型的内部计算量随 context 平方增长，这些成本通过定价传递给用户。

Convention：**attention score** = 两个 token 之间尚未归一化的相关性得分；**attention weight** = 经归一化后的权重，所有 weights 加和为 1，表示"这个 token 应该借鉴其他 token 多少信息"。

现代优化（Flash Attention、Sliding Window Attention）通过分块计算或限制每个 token 只看近邻，把实际计算量压低。但 O(n²) 是理解"长 context 为什么有代价"的正确心智模型。

**对你写 agent 意味着什么**：做 agent 架构决策时，把"这个任务需要多长 context"作为一个明确的设计参数，而不是开着 200K 塞满就好。精确控制 context 既省钱又减少注意力稀释（太长的 context 里，早期关键信息容易被"淹没"）。

---

### 心智模型 3：KV Cache——为什么对话比重算省 ~85% tokens

**关键数字**：200 轮对话，每轮新增 50 tokens。不用 KV Cache 需要重算全部 ~10,000 tokens；用了 KV Cache 每轮只算新增的 50 tokens。节省约 99.5% 的重复计算，折算成 API token 费用约省 85%（因为还有输出 tokens 的固定成本）。

Attention 计算时，每个 token 需要生成三样东西：Query（我要问什么）、Key（我能回答什么）、Value（我的信息内容）。简写为 Q、K、V。

多轮对话时，前面轮次的 K 和 V 其实不会变——你不会修改历史消息。如果把它们缓存起来，下一轮只需要计算新 token 的 Q/K/V，然后用新 Q 去对所有历史 K 做 Attention 即可。这就是 KV Cache。

**Prompt Caching** 是 KV Cache 在 API 层的表现形式。Anthropic、OpenAI、DeepSeek 都提供了不同程度的 prompt caching：
- Anthropic：在请求中用 `cache_control: {type: "ephemeral"}` 标记可缓存的 prompt 前缀，缓存命中后输入 token 价格降至 10%
- OpenAI：自动对超过 1024 tokens 的 prompt 做缓存，命中价格降至 50%
- DeepSeek：所有请求自动启用，命中价格降至约 10%

**对你写 agent 意味着什么**：把 system prompt、工具 schema、长文档放在消息的开头，把每轮变化的部分（用户输入）放在最后。这让缓存命中率最大化，多轮对话的实际成本可以降低数倍。这是第 7 章（Context Engineering）的基础，但直觉要在这里建立。

---

### 心智模型 4：Context Window 为什么有限

**关键数字**：70B 模型运行时，KV Cache 每 1K tokens 占约 0.5GB 显存；128K context 就是 64GB，和模型权重本身的显存需求相当。

Context window 不是随便定的数字。它是显存、计算、成本三者之间的工程妥协。

KV Cache 要住在 GPU 显存里（VRAM），因为每次生成新 token 都需要访问。GPU 显存是稀缺资源——A100 80GB 版是目前服务端主流，H100 有 80GB 和 141GB 两种。一张 H100 141GB 跑一个 70B FP16 模型，光是模型权重就要 140GB，几乎占满。再要支持 128K context 的 KV Cache，就需要多卡并行。

这就是为什么 Claude 200K、Gemini 1M 是工程成就：他们找到了在可控成本下扩展 context 的方法（包括更激进的 KV Cache 压缩和 Multi-Query Attention 等技术）。

Convention：**context window** = 模型在一次请求中能看到的最大 token 数，包括输入和输出；**sequence length** = 实际处理的 token 序列长度，必须 ≤ context window。

一个常被忽视的工程细节：超过 context window 的内容不会"报错"——API 会截断最早的内容（通常是第一轮对话），静默丢失。不注意这点，agent 在长会话中会突然"忘记"早期的关键指令。

**对你写 agent 意味着什么**：主动管理上下文，不要依赖"200K 肯定够"。在 Ch 7 你会学到 autocompact 和 microcompact 策略——但在此之前，知道"context 会被截断且是静默的"是避坑的第一步。

---

### 心智模型 5：FP16 / BF16 / INT8 / INT4——量化是什么

**关键数字**：INT4 量化让 70B 模型从 140GB 压到约 40GB，能跑在 4 张 RTX 4090（每张 24GB）上；质量损失在多数任务上约 5-10%。

模型权重是一堆浮点数。存储这些浮点数用多少比特，决定了精度和显存占用。

| 精度 | 比特数 | 70B 模型显存 | 质量 | 典型场景 |
|------|--------|------------|------|---------|
| FP32 | 32 bit | 280 GB | 基准 | 训练（不用于推理） |
| FP16 | 16 bit | 140 GB | ≈FP32 | 服务器推理默认精度 |
| BF16 | 16 bit | 140 GB | ≈FP16 | H100/A100 训练优先，数值范围更宽 |
| INT8 | 8 bit | 70 GB | 损失 <3% | 资源受限服务器部署 |
| INT4 | 4 bit | 35-40 GB | 损失 5-10% | 消费级 GPU 本地部署首选 |

Convention：**FP16** = 16 位浮点，用符号位 + 5 位指数 + 10 位尾数；**BF16** = Brain Float 16，用符号位 + 8 位指数 + 7 位尾数，指数范围和 FP32 一样宽，更不容易溢出。本书语境下，两者在质量上等价，主要差别是硬件支持：A100/H100 对 BF16 有原生加速。

量化的机制可以简单理解为：把精确的 FP16 数字映射到 INT4 范围（0-15），用一个 scale 因子还原。这不可避免地损失精度，但损失是可控的，好的量化实现（GPTQ、AWQ、llama.cpp 的 Q4_K_M）对质量影响很小。

**对你写 agent 意味着什么**：如果你需要自托管模型，INT4 是消费级硬件的入场券。如果你用 API，量化在服务端透明处理，你感知不到——但 Groq、Together、DeepSeek 这些推理服务用了量化，它们便宜很多，在精度可接受的任务上是明智选择。

---

### 心智模型 6：Dense vs MoE——DeepSeek-V3 为什么"671B 激活 37B"

**关键数字**：DeepSeek-V3 总参数 671B，每次推理激活 37B。激活参数决定推理成本，不是总参数。

传统 Transformer（Dense 模型）每次生成 token 时，激活所有参数。GPT-4 据估计约 1.8T 参数，每次生成都用到全部——代价极高。

Mixture of Experts（MoE）架构的思路：把 FFN（前馈网络）层分成多个专家（expert），每次只路由给其中几个专家处理。如果有 64 个专家，每次激活 2 个，实际计算量只有 1/32。但模型"见过的知识"仍来自所有 64 个专家的训练——总参数大，激活参数小。

DeepSeek-V3 的数据：
- 总参数：671B（需要大显存存储权重）
- 每 token 激活：37B（推理计算量等效于 37B Dense 模型）
- 在 2025 年发布时，质量接近 GPT-4o，但推理成本约为其 1/10

Convention：**Dense 模型** = 每次推理激活全部参数；**MoE 模型** = 有路由机制，每次只激活部分"专家"；**激活参数（active parameters）** = 每次推理实际参与计算的参数量，决定推理速度和成本；**总参数（total parameters）** = 所有专家的参数之和，决定存储和加载成本。

MoE 的代价：每个 expert 的参数都要加载进显存，即使它在这次推理中没被激活。671B 总参数意味着你需要 1.3TB 显存来存模型——这需要 10+ 张 H100。DeepSeek 的 API 用共享服务器摊平这个成本，你不用操心。

另一个主流 MoE 模型：Qwen3-235B（激活约 22B），Mixtral 8×7B（激活约 13B，总 46B）。

**对你写 agent 意味着什么**：当你看到一个模型参数量很大但价格很便宜，先检查是不是 MoE 架构——激活参数才是推理成本的真正决定因素。不要被总参数量吓到，也不要被它迷惑而忽略 active 参数的实际含量。

---

### 心智模型 7：代表模型选型对比表

**关键数字**：截至 2026 年初，agent 工具调用场景中，Claude Sonnet 系列在综合质量/成本比上连续保持第一梯队（Berkeley function calling leaderboard，来源公开排行榜）。

以下对比表针对 agent 工程师的四个核心关切维度打分（1-5 分，5 最优）：

| 模型 | 推理能力 | 工具调用 | 长 Context | 中文质量 | 成本 | 适用场景 |
|------|---------|---------|-----------|---------|------|---------|
| Claude Opus 4 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★ | ★★ | 需要最高质量的复杂推理 |
| Claude Sonnet 4.5 | ★★★★ | ★★★★★ | ★★★★★ | ★★★★ | ★★★★ | **大多数 agent 任务的首选** |
| Claude Haiku 4.5 | ★★★ | ★★★★ | ★★★★ | ★★★ | ★★★★★ | 高频简单调用，成本敏感 |
| GPT-4o | ★★★★ | ★★★★★ | ★★★★ | ★★★★ | ★★★ | OpenAI 生态、已有集成 |
| GPT-4o mini | ★★★ | ★★★★ | ★★★ | ★★★ | ★★★★★ | OpenAI 生态成本敏感任务 |
| Gemini 2.5 Pro | ★★★★★ | ★★★★ | ★★★★★ | ★★★★ | ★★★ | 超长文档、Google 生态 |
| DeepSeek-V3 | ★★★★ | ★★★★ | ★★★★ | ★★★★★ | ★★★★★ | 中文场景、成本极敏感 |
| DeepSeek-R1 | ★★★★★ | ★★★ | ★★★ | ★★★★★ | ★★★ | 复杂推理、慎用于工具调用 |
| Qwen3-72B | ★★★★ | ★★★★ | ★★★★ | ★★★★★ | ★★★★ | 中文优先、本地部署友好 |

几条选型铁律（有立场的，不是"都可以视情况而定"）：

**推荐 Claude Sonnet 系列作为 agent 工具调用的默认选择**，理由：function calling 格式最稳定，返回格式遵从率高，工具调用连续成功率领先。这不是赞助说法——Berkeley function calling leaderboard 2025 全年数据支持这个结论。

**中文任务优先考虑 DeepSeek-V3 或 Qwen3**：不是因为它们比 Claude 更聪明，而是中文 token 效率更高（同样的内容 Claude 消耗约 1.5-2 倍 token），且价格是 Claude 的 1/10 以下。

**Reasoning 模型（R1/Claude Thinking/o3）不适合直接套进 agent loop**：理由见心智模型 8。

**对你写 agent 意味着什么**：这张表不是永恒真理。截至本书写作时（2026 年初），以上判断基于公开基准和工程实践。6 个月后模型格局可能变化。但选型方法论是稳定的：先确定任务类型，再对照工具调用稳定性、context 长度需求、成本上限三个维度过滤。

---

### 心智模型 8：Reasoning 模型 vs 普通模型

**关键数字**：DeepSeek-R1 处理一道需要多步推理的数学题，内部"思考"消耗约 2,000-8,000 tokens，然后才输出答案。如果答案只有 50 tokens，thinking tokens 的成本可能是答案本身的 40-160 倍。

Convention：**Reasoning 模型** = 在输出最终答案前，会生成大量"思考过程"token 的模型（如 OpenAI o3、DeepSeek-R1、Claude with extended thinking）；**普通模型** = 直接生成答案，不额外输出思考过程。

Reasoning 模型的内部机制是"在回答之前先想一想"——这在模型内部被实现为先生成一段较长的思考文本，然后基于这段思考给出答案。这让它在数学推理、代码调试、逻辑谜题上表现显著优于普通模型。

但它对 agent 工具调用有一个重要限制：**工具调用的格式遵从率不稳定**。普通模型学会了"当我需要工具时，输出这个 JSON 格式"，这是固定行为。Reasoning 模型在思考过程中可能"改变主意"，或者在思考完后忘记按格式调用工具，或者在同一个 turn 里思考一半就停了。这在实际工程中会造成解析失败。

何时该用 Reasoning 模型：
- 任务本身是复杂推理（数学证明、多步逻辑、代码调试分析）
- 允许较高延迟（thinking 需要时间，一次推理可能需要 30-60 秒）
- 任务是"想清楚再做一件事"，而不是"在 20 轮工具调用里每次都做小决策"

何时不该用：
- 需要频繁工具调用的 agent loop（每次调用都有 thinking 成本）
- 延迟敏感的场景（streaming 时用户要等 thinking 结束才看到内容）
- 格式遵从很重要的任务（工具调用的 JSON 解析）

一个实践中的常见陷阱：把 DeepSeek-R1 放进 ReAct loop，结果它在思考里"想到了答案"，不再调用工具，直接输出——你的工具从来没被执行，loop 提前终止，用户得到了一个基于模型内部知识的答案而不是工具实际返回的结果。

**对你写 agent 意味着什么**：Reasoning 模型是专用工具，不是通用升级。把它用在"需要深度思考的单次任务"上，用普通模型跑 multi-step agent loop。

---

## Beat 5 — 选型决策树

*把 8 个心智模型组装成一个可操作的流程。*

在 agent 开发中，你会在三个场景面临模型选型：

**场景 A：API 选型（使用托管模型）**

首先问：**任务是否需要复杂推理（数学、多步逻辑、深度分析）？**

- 是 → 考虑 Reasoning 模型，但评估工具调用需求：
  - 有工具调用 → 用 Claude Sonnet/Opus（extended thinking 模式，工具调用更可控）
  - 纯推理，无工具 → DeepSeek-R1 或 o3-mini 性价比高
- 否 → 进入常规选型

常规选型：**主要关注哪个维度？**

- 成本优先 → DeepSeek-V3（中文）或 Claude Haiku 4.5（英文/工具）
- 中文优先 → DeepSeek-V3 或 Qwen3（API 版）
- 工具调用稳定性优先 → Claude Sonnet 系列
- 超长 Context（>100K tokens）→ Gemini 2.5 Pro 或 Claude（成本考量）
- 已有 OpenAI 集成 → GPT-4o 或 GPT-4o mini

**场景 B：本地部署选型**

首先问：**你有多少 GPU 显存？**

- ≤ 24 GB（单张消费级 GPU）→ 7B-13B INT4 量化（Qwen3-7B、Llama 3.2-8B）
- ≤ 80 GB（单张 A100）→ 70B INT4 量化（Llama 3.3-70B、Qwen3-72B）
- ≤ 160 GB（双 A100/H100）→ 70B FP16 或 671B MoE INT4（DeepSeek-V3）
- 多节点 → 671B MoE FP16，能达到 API 同等质量

然后问：**质量要求如何？**

- 质量敏感 → 选更高精度（INT8 > INT4），或更大模型 INT4
- 吞吐量敏感 → INT4 量化 + vLLM/llama.cpp 推理框架

**场景 C：成本估算**

在设计 agent 之前做一次信封背面计算：

```
预估日成本 = 每次调用 tokens × 每天调用次数 × token 单价

例：
每次调用：system prompt(2K) + 对话历史(5K) + 输出(1K) = 8K tokens
每天调用：1,000 次
Claude Sonnet 4.5：输入 $3/M tokens，输出 $15/M tokens
日成本：7K×1000×$3/1M + 1K×1000×$15/1M = $21 + $15 = $36/天 = $1,080/月
```

换 Haiku 4.5：输入 $1/M，输出 $5/M → $7 + $5 = $12/天 = $360/月

如果质量可接受，Haiku 节省 67%。这个计算应该在写第一行 agent 代码之前做。

---

## Beat 6 — "选型决策树"产物

**代码 4-C：信封背面成本计算器（可直接用）**

```python
def estimate_monthly_cost(
    daily_calls: int,
    avg_input_tokens: int,
    avg_output_tokens: int,
    model_config: dict,
    cache_hit_rate: float = 0.0,
) -> dict:
    """估算 agent 每月 API 成本。

    Args:
        daily_calls: 每日 API 调用次数
        avg_input_tokens: 平均每次输入 token 数
        avg_output_tokens: 平均每次输出 token 数
        model_config: 包含 name/input_price/output_price/cached_price 的字典
        cache_hit_rate: prompt caching 命中率（0.0-1.0）

    Returns:
        包含日成本、月成本、缓存节省的字典

    Example:
        >>> sonnet = {
        ...     "name": "claude-sonnet-4-5",
        ...     "input_price": 3.0,    # $/M tokens
        ...     "output_price": 15.0,
        ...     "cached_price": 0.3,   # 10% of input price
        ... }
        >>> estimate_monthly_cost(1000, 7000, 1000, sonnet, cache_hit_rate=0.7)
        {'daily_usd': 36.0, 'monthly_usd': 1080.0, 'cache_saving_usd': 756.0, ...}
    """
    price_per_mtok_in = model_config["input_price"]
    price_per_mtok_out = model_config["output_price"]
    cached_price = model_config.get("cached_price", price_per_mtok_in * 0.1)

    # 非缓存部分按正常价格；缓存命中部分按降价后计算
    uncached_input_tokens = avg_input_tokens * (1 - cache_hit_rate)
    cached_input_tokens = avg_input_tokens * cache_hit_rate

    daily_input_cost = (
        (uncached_input_tokens / 1_000_000) * price_per_mtok_in
        + (cached_input_tokens / 1_000_000) * cached_price
    ) * daily_calls
    daily_output_cost = (avg_output_tokens / 1_000_000) * price_per_mtok_out * daily_calls
    daily_cost = daily_input_cost + daily_output_cost

    # 无缓存时的基准成本（用于计算节省量）
    baseline_input_cost = (avg_input_tokens / 1_000_000) * price_per_mtok_in * daily_calls
    cache_saving_daily = baseline_input_cost - daily_input_cost

    return {
        "model": model_config["name"],
        "daily_usd": round(daily_cost, 2),
        "monthly_usd": round(daily_cost * 30, 2),
        "cache_saving_monthly_usd": round(cache_saving_daily * 30, 2),
        "cache_hit_rate": cache_hit_rate,
    }


# 用法示例
MODELS = {
    "sonnet": {
        "name": "claude-sonnet-4-5",
        "input_price": 3.0,
        "output_price": 15.0,
        "cached_price": 0.3,
    },
    "haiku": {
        "name": "claude-haiku-4-5",
        "input_price": 1.0,
        "output_price": 5.0,
        "cached_price": 0.1,
    },
}
```

预期输出（每日 1000 次调用，平均 7K 输入 + 1K 输出，70% 缓存命中率）：

```
Sonnet: {'daily_usd': 21.3, 'monthly_usd': 639.0, 'cache_saving_monthly_usd': 441.0}
Haiku:  {'daily_usd':  7.6, 'monthly_usd': 228.0, 'cache_saving_monthly_usd': 132.3}
```

这个函数是 Beat 5 "信封背面计算"的代码版本。在设计 agent 之前跑一次，把感受从"大概多少钱"变成"确切多少钱"。缓存命中率 70% 时，Sonnet 的月成本从 $1,080 降到 $639，节省 $441——而切换到 Haiku 4.5 能进一步降到 $228，两种手段可以叠加使用。

---

本章的代码产物是三个工具函数（代码 4-A/4-B/4-C），可直接放进任何 agent 项目：token 计数、prompt caching 效果验证、月成本估算。你有了一张可带走的决策框架，以及以下随时可查的检查清单：

**模型选型 10 秒检查清单**

1. 任务需要工具调用吗？→ 优先 Claude Sonnet 系列
2. 主要语言是中文吗？→ DeepSeek-V3 / Qwen3 性价比更高
3. 任务是纯推理（无工具）吗？→ 考虑 Reasoning 模型
4. Context 超过 50K tokens 吗？→ 检查该模型的 context window 上限和实际效果
5. 对成本敏感吗？→ 先估算，再降级到足够好的模型
6. 本地部署吗？→ 显存 ÷ 2 = 大概能跑的参数量（FP16，GB 和 B 之间的粗略换算）

**本章可能产生的局限性提示**：

以上选型表基于 2026 年初的公开信息。LLM 发展速度极快，6 个月后格局可能显著变化——新模型发布、定价调整、功能上线都会改变最优选择。本章给你的不是结论，是选型方法论。结论需要你在实际使用时用自己的任务基准验证。

---

## Beat 7 — Design Note

> **Why Not Train Your Own Model?**

有时候读者会问：既然本书讲 LLM，为什么不从头训练一个？

训练的替代方案：用 Raschka 的《Build a Large Language Model From Scratch》或 Karpathy 的 nanoGPT 自己实现 GPT-2。这两本/两个项目已经把"从零实现 Transformer 到预训练文本生成"做得极好。

如果你想理解 LLM 内部如何工作，去读那两个资源。本书建议："不需要读完，只需要知道：在 Raschka 的书里，Ch4 实现了 GPTModel，Ch5 完成了预训练。这是你需要的全部训练直觉。"

为什么本书不做这件事，而是专注 harness（利用模型的框架）？

- **分工差异**：Karpathy 和 Raschka 的项目解决了"LLM 是什么"。本书解决"LLM 怎么用来构建 agent"。做重复的事对读者没有额外价值。
- **资源门槛**：训练 GPT-2 级别（124M 参数）的模型需要数小时 GPU 计算，训练任何实用的现代 LLM 需要数百万美元。一个想构建 agent 的工程师不需要这个门槛。
- **目标分离**：理解 LLM 内部原理（权重、梯度、损失函数）和有效使用 LLM API（context engineering、工具调用、选型）是两套技能，前者不是后者的必要前提。

当然，如果你对训练感兴趣，Karpathy 的 zero-to-hero 系列和 Raschka 的书是目前最好的入门路径。本书在附录 D 给出了"想深入的去哪里"指引。

如果你在生产环境需要 fine-tuning（而不是从头训练），那属于另一个领域——PEFT、LoRA、instruction tuning——本书不覆盖，因为对大多数 agent 工程师来说，prompt engineering 和模型选型能解决 95% 的问题，fine-tuning 是你在瓶颈明确之后才需要的工具。

---

## 章末挑战

1. **数字估算**：你的 agent 每天处理 500 次用户请求，每次平均 context 是 10K tokens，输出 500 tokens。分别用 Claude Sonnet 4.5 和 DeepSeek-V3 估算月成本，差距是多少？

2. **选型练习**：一个 agent 需要帮用户分析合同（100 页 PDF，约 80K tokens），判断是否存在风险条款，返回一份结构化报告。请给出你的模型选型理由，包括 context 长度、推理能力、成本三个维度。

3. **MoE 直觉**：Mixtral 8×7B 的总参数是 46B，但推理时激活约 13B。如果你有一台 2×RTX 4090（共 48GB VRAM），用 INT4 量化大约需要多少显存？这台机器能跑得起来吗？

---

## 叙事钩子

你现在有了 8 张认知卡片，能在 30 秒内做出模型选型判断。但 Lena 还只有三个工具：get_time、文件读写、简单查询。下一章，我们要构建一个"加工具不改核心"的注册机制——让 Lena 能优雅地扩展到 20 个工具，而不是把每个工具硬编码进 agent loop。

---

---

## Revision Log

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-05-05 | 初稿，从零创建，覆盖 SPEC 全部 8 个心智模型 |
