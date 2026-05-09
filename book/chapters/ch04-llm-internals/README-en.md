# Ch 4 · LLM Internals: The Minimum You Need to Know as an Agent Engineer

> **Lena version note**: This is a methodology chapter with no code output. After reading it, Lena's codebase stays unchanged — but you, the engineer building agents, walk away with a cognitive map that lets you stop being intimidated by model parameters. The tool system in Ch 5 is where you'll actually build on top of this map.

---

## Beat 1 — Roadmap

```
Ch 1 → Ch 2 → Ch 3 → [Ch 4 ← you are here] → Ch 5 → ... → Ch 22
API call   ReAct loop  Lena born              LLM internals   Tool system
```

By now, Lena can take user input, call an LLM, and return results. But every time you pick a model, set `max_tokens`, or decide whether to use prompt caching, you're making an engineering decision — without knowing why.

This chapter starts from "Lena fires its first API request" and walks through 8 mental models, ending at "you can make a model selection decision in 30 seconds." Along the way we'll hit one counterintuitive trap: **the instinct says bigger model = better; the engineering reality is bigger model = more expensive, slower, and sometimes dumber** — the MoE architecture is the key to understanding that contradiction.

The only deliverable in this chapter is a decision tree. No code, no matrices — just intuition you can take with you.

**This chapter is not an ML textbook.** Books on training Transformers already exist — Raschka's *Build a Large Language Model From Scratch* implements GPT-2 from zero, and Karpathy's nanoGPT fits a 124M-parameter GPT into 300 lines. This book doesn't repeat their work. It focuses on the harness: how to plug a model into your agent and make it do what you want.

> **🧠 Intelligence increment (v0.3 → v0.4)**: Lena gains its first "understanding of LLM internals" — once you've internalized the cost model for tokens, context windows, and prompt caching, you can make model selection decisions in 30 seconds instead of guessing "bigger is better." This chapter teaches you how to embed LLM engineering intuition into your own agent design decisions.

---

## Beat 2 — Motivation

You open the Anthropic docs, see Claude Opus 4, Sonnet 4.5, and Haiku 3.5 listed side by side. You go with Opus because it's "smarter."

Three weeks later the bill lands: $847. The same task on Haiku would cost $23. Quality testing shows: for your tool-calling use case, Haiku scores 91% and Opus scores 93%. You paid 37× more for a 2% quality improvement.

This is not an edge case. In 2026-era agent development, **wrong model selection is the single most common cost mistake**. Not because engineers are careless — because nobody built the right intuitive framework.

Different scenario. Your agent needs to process a 200-page PDF (roughly 150,000 tokens). You picked GPT-4o because it's "good." Each request now takes 15 seconds and costs 18× what an 8K-context request costs — because attention scales quadratically with context length, and you weren't aware of that.

Or: you're self-hosting a 70B open-source model. FP16 precision needs 140 GB of VRAM; you don't have that. INT4 quantization brings it down to 40 GB, runnable on 4× RTX 4090s, with quality loss that's acceptable for your use case — but you didn't know this option existed.

**The 8 mental models are the minimal necessary knowledge to avoid all of the above.** Understanding them requires no knowledge of backpropagation, no PyTorch experience — only the ability to see "what engineering parameter does this determine."

---

## Beat 3 — Theory Foundation

Anthropic's engineering white paper gives a practitioner-grade selection axiom in its architecture section:

> "Choose the right model for the job. The key is balancing three factors: **capabilities, speed, and cost**. Think of it like choosing the right tool from a toolbox: you wouldn't use a sledgehammer to hang a picture frame."
> (Source: Anthropic, *Building Effective AI Agents*, 2025, p.10)

The premise of that statement is: you have to understand **what actually differs** between models. This chapter doesn't teach you to train them — it teaches you the 8 mental models so that every time you pick a model, set a parameter, or estimate a cost, you understand the physical reason behind it.

### 3.1 Why LLMs Are "Predict the Next Token" Machines

Convention: **token** = the smallest text unit an LLM processes (roughly 0.75 English words; one Chinese character is typically 1–2 tokens); **word** = a human-written word, not the same as a token.

Everything a modern LLM does can be described in one sentence: given the preceding tokens, predict a probability distribution over the next token. This is repeated, one token at a time, until a stop token is generated.

This means LLMs are fundamentally **serial generators** — generating token 100 requires having generated the previous 99. That's a key engineering constraint: no matter how large the model or how powerful the GPU, output speed (tokens/sec) has a physical ceiling that is directly tied to how long you need the reply to be. **What this means for agent builders**: tasks that require long outputs (writing reports, generating code) are inherently slower than short-output tasks. Give your timeouts enough headroom.

### 3.2 The Transformer in One Diagram

Convention: **embedding** = a representation that maps a token into a high-dimensional vector space — an array of numbers; **encoding** usually refers to BERT-style bidirectional encoders. The GPT-family decoder-only architecture this book discusses uses embeddings throughout.

```
Input text
    ↓
[Tokenizer]       splits text into a token sequence
    ↓
[Embedding Layer] maps each token to a vector (e.g. 4096 dimensions)
    ↓
[Attention Layers × N]  each token attends to all others, building context
    ↓
[Output Layer]    maps vectors back to vocabulary, outputs probability distribution
    ↓
sampling (greedy / temperature / top-p)
    ↓
next token
```

N attention layers stacked — GPT-3 has 96; the Claude family is undisclosed but comparable in scale. Each attention layer does one thing: lets every token in the sequence "ask questions" of every other token and integrate the answers. More layers = deeper linguistic understanding; but every layer must compute at inference time. Layers × token count × parameter count = compute cost.

**What this means for agent builders**: a model's "intelligence" comes from its layer count and parameter count, but inference latency grows linearly too. Choosing "smart enough" rather than "smartest" is correct engineering hygiene.

---

## Beat 4 — The 8 Mental Models

*The scaffolding here isn't code — it's 8 cognitive cards. Let's build them one by one.*

---

### Mental Model 1: The Transformer in One Diagram — Why Not RNN?

**Key number**: GPT-3 has 96 attention layers, each processing the full sequence, with 175 billion parameters.

Before Transformers, sequence models were mostly RNNs (recurrent neural networks). The problem with RNNs: by the time you process token 1,000, information about token 1 has mostly been "forgotten" — because it flows sequentially, like a game of telephone. Transformer attention sidesteps this entirely: every token can directly "see" any other token in the sequence regardless of distance. No forgetting from distance.

This is why LLMs can handle 100K+ context without losing early information — in theory. In practice it's also bounded by KV Cache VRAM limits (see Mental Model 3).

Another RNN problem: training can only proceed sequentially, no parallelism. Transformers can process the entire sequence in parallel, making training across thousands of GPUs feasible. Training speed differences of 100× or more.

**What this means for agent builders**: you don't need to train a Transformer yourself. But "why can the model remember context from very early in the conversation" — attention directly connects any two tokens — is the foundational intuition for understanding context window limits.

---

### Mental Model 2: The Engineering Consequence of Attention — Intuition for O(n²)

**Key number**: context growing from 4K to 128K (32×) increases attention compute by roughly 1,024×.

The core operation in attention can be understood in one sentence: every token in the sequence must be compared pairwise with every other token. If the sequence has n tokens, that's n × n comparisons. That's O(n²) — quadratic complexity.

Concrete numbers to feel the difference:
- 1,000 tokens → 1,000,000 comparisons
- 8,000 tokens → 64,000,000 comparisons (64× more)
- 128,000 tokens → 16,384,000,000 comparisons (16,384× more)

This directly explains why "long context = expensive." Anthropic's Claude 3.5 Haiku costs roughly $0.0008 per 1K tokens; processing 200K tokens isn't 200× more expensive — it's worse, because the model's internal computation scales quadratically with context, and that cost flows through to pricing.

Convention: **attention score** = the unnormalized relevance score between two tokens; **attention weight** = the normalized score, where all weights sum to 1, representing "how much should this token borrow from other tokens."

Modern optimizations (Flash Attention, Sliding Window Attention) reduce actual compute through block-wise calculation or restricting each token to only attend to neighbors. But O(n²) is the correct mental model for understanding why long context has a cost.

**What this means for agent builders**: when making architectural decisions, treat "how much context does this task actually need" as an explicit design parameter — don't just leave 200K open and fill it. Precise context control saves money and reduces attention dilution (in very long contexts, early critical information can get "drowned out").

---

### Mental Model 3: KV Cache — Why Conversation Is ~85% Cheaper Than Recomputing

**Key number**: a 200-turn conversation, 50 new tokens per turn. Without KV Cache: recompute all ~10,000 tokens each turn. With KV Cache: only compute the 50 new tokens per turn. Saves ~99.5% of redundant computation, translating to roughly 85% savings on API token costs (after accounting for fixed output token costs).

During attention computation, each token needs to produce three things: Query (what am I asking for?), Key (what can I answer?), and Value (what is my content?). Abbreviated Q, K, V.

In a multi-turn conversation, the K and V from previous turns don't change — you never modify history. If you cache them, the next turn only needs to compute Q/K/V for new tokens, then use the new Q to attend over all cached K. That's KV Cache.

**Prompt Caching** is the API-layer manifestation of KV Cache. Anthropic, OpenAI, and DeepSeek all offer it in different forms:
- Anthropic: mark cacheable prompt prefixes in the request with `cache_control: {type: "ephemeral"}`; on cache hit, input token cost drops to 10%
- OpenAI: automatically caches prompts exceeding 1,024 tokens; cache hit cost drops to 50%
- DeepSeek: enabled automatically on all requests; cache hit cost drops to roughly 10%

**What this means for agent builders**: put your system prompt, tool schemas, and long documents at the beginning of your messages, and put the per-turn changing parts (user input) at the end. This maximizes cache hit rate and can reduce the effective cost of multi-turn conversations by several times. This is the foundation of Ch 7 (Context Engineering) — but the intuition belongs here.

---

### Mental Model 4: Why Context Windows Are Finite

**Key number**: at inference time, a 70B model's KV Cache consumes roughly 0.5 GB of VRAM per 1K tokens. A 128K context requires 64 GB — comparable to the model weights themselves.

Context window sizes aren't arbitrary numbers. They're an engineering tradeoff between VRAM, compute, and cost.

The KV Cache must live in GPU VRAM because every new token generation requires accessing it. GPU VRAM is scarce — the A100 80 GB is the current server-side mainstream; the H100 comes in 80 GB and 141 GB variants. One H100 141 GB running a 70B FP16 model uses nearly all 141 GB just for weights. Supporting a 128K context KV Cache on top of that requires multi-GPU parallelism.

This is why Claude 200K and Gemini 1M are engineering achievements: they found ways to scale context at manageable cost (including more aggressive KV Cache compression and Multi-Query Attention).

Convention: **context window** = the maximum number of tokens a model can process in one request, including both input and output; **sequence length** = the actual token count being processed, which must be ≤ context window.

An often-missed engineering detail: when input exceeds the context window, you won't get an error — the API silently truncates the oldest content (usually the earliest conversation turns). Missing this, an agent can suddenly "forget" critical early instructions mid-session without any warning.

**What this means for agent builders**: actively manage context — don't rely on "200K is definitely enough." In Ch 7 you'll learn autocompact and microcompact strategies. But before that, knowing "context gets truncated silently" is the first step to avoiding the trap.

---

### Mental Model 5: FP16 / BF16 / INT8 / INT4 — What Quantization Is

**Key number**: INT4 quantization shrinks a 70B model from 140 GB to roughly 40 GB, runnable on 4× RTX 4090 (24 GB each); quality loss on most tasks is roughly 5–10%.

Model weights are a large collection of floating-point numbers. How many bits you use to store each float determines both precision and memory footprint.

| Precision | Bits | 70B model VRAM | Quality | Typical use |
|-----------|------|----------------|---------|-------------|
| FP32 | 32 bit | 280 GB | Baseline | Training (not used for inference) |
| FP16 | 16 bit | 140 GB | ≈ FP32 | Default server-side inference precision |
| BF16 | 16 bit | 140 GB | ≈ FP16 | H100/A100 training; wider numerical range |
| INT8 | 8 bit | 70 GB | <3% loss | Resource-constrained server deployment |
| INT4 | 4 bit | 35–40 GB | 5–10% loss | Consumer GPU local deployment, first choice |

Convention: **FP16** = 16-bit float using sign + 5-bit exponent + 10-bit mantissa; **BF16** = Brain Float 16, using sign + 8-bit exponent + 7-bit mantissa, same exponent range as FP32 so it's much less prone to overflow. In this book's context the two are equivalent in quality; the main difference is hardware support — A100/H100 natively accelerate BF16.

The quantization mechanism can be understood simply: map precise FP16 values into the INT4 range (0–15) using a scale factor to restore approximate values. This inevitably loses some precision, but the loss is controlled — good quantization implementations (GPTQ, AWQ, llama.cpp's Q4_K_M) have minimal quality impact.

**What this means for agent builders**: if you need to self-host a model, INT4 is your entry ticket on consumer hardware. If you're using APIs, quantization is handled transparently on the server side — but Groq, Together, and DeepSeek use quantized models, which is why they're cheaper; they're a sensible choice for tasks where precision trade-offs are acceptable.

---

### Mental Model 6: Dense vs MoE — Why DeepSeek-V3 Is "671B total, 37B active"

**Key number**: DeepSeek-V3 has 671B total parameters; each inference pass activates 37B. Active parameters determine inference cost — not total parameters.

Traditional Transformers (Dense models) activate every parameter on every token generation. GPT-4 is estimated to have roughly 1.8T parameters, all of which fire every time — extremely costly.

Mixture of Experts (MoE) architecture: split the FFN (feed-forward network) layers into multiple experts and only route to a subset of them per token. With 64 experts and 2 active per token, actual compute is 1/32. But the model's total knowledge still comes from all 64 experts trained together — large total parameters, small active parameters.

DeepSeek-V3 data:
- Total parameters: 671B (requires large VRAM to store weights)
- Active parameters per token: 37B (inference compute equivalent to a 37B dense model)
- At its 2025 release: quality close to GPT-4o, inference cost roughly 1/10th

Convention: **Dense model** = activates all parameters every inference pass; **MoE model** = has a routing mechanism, activates only a subset of "experts" per pass; **active parameters** = the parameters actually participating in computation each inference pass, determining inference speed and cost; **total parameters** = sum of all expert parameters, determining storage and loading cost.

The cost of MoE: every expert's parameters must be loaded into VRAM, even if not activated for this particular inference. 671B total parameters means you need roughly 1.3 TB of VRAM to store the model — requiring 10+ H100s. DeepSeek's API amortizes this cost across a shared server fleet; you don't need to worry about it.

Other mainstream MoE models: Qwen3-235B (roughly 22B active), Mixtral 8×7B (roughly 13B active, 46B total).

**What this means for agent builders**: when you see a large-parameter model with a surprisingly low price, check whether it's MoE — active parameters are what truly determine inference cost. Don't be scared off by total parameter count, and don't be deceived by it either when evaluating actual inference capacity.

---

### Mental Model 7: Representative Model Comparison Table

**Key number**: as of early 2026, in agent tool-calling scenarios, the Claude Sonnet family has consistently ranked in the top tier on the quality-to-cost ratio (Berkeley Function Calling Leaderboard, public ranking).

The table below scores models across four dimensions that matter to agent engineers (1–5, 5 is best):

| Model | Reasoning | Tool Calling | Long Context | Chinese Quality | Cost | Best for |
|-------|-----------|-------------|--------------|-----------------|------|---------|
| Claude Opus 4 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★ | ★★ | Complex reasoning requiring maximum quality |
| Claude Sonnet 4.5 | ★★★★ | ★★★★★ | ★★★★★ | ★★★★ | ★★★★ | **Default choice for most agent tasks** |
| Claude Haiku 3.5 | ★★★ | ★★★★ | ★★★★ | ★★★ | ★★★★★ | High-frequency simple calls, cost-sensitive |
| GPT-4o | ★★★★ | ★★★★★ | ★★★★ | ★★★★ | ★★★ | OpenAI ecosystem, existing integrations |
| GPT-4o mini | ★★★ | ★★★★ | ★★★ | ★★★ | ★★★★★ | Cost-sensitive OpenAI ecosystem tasks |
| Gemini 2.5 Pro | ★★★★★ | ★★★★ | ★★★★★ | ★★★★ | ★★★ | Very long documents, Google ecosystem |
| DeepSeek-V3 | ★★★★ | ★★★★ | ★★★★ | ★★★★★ | ★★★★★ | Chinese-language tasks, extreme cost sensitivity |
| DeepSeek-R1 | ★★★★★ | ★★★ | ★★★ | ★★★★★ | ★★★ | Complex reasoning; use cautiously for tool calling |
| Qwen3-72B | ★★★★ | ★★★★ | ★★★★ | ★★★★★ | ★★★★ | Chinese-first, local deployment friendly |

A few opinionated selection rules — not "it depends":

**Recommend Claude Sonnet as the default for agent tool calling**, because: function calling format is most stable, return format compliance rate is high, and consecutive tool-call success rates lead the field. This isn't a sponsored claim — Berkeley Function Calling Leaderboard data throughout 2025 supports it.

**Chinese-language tasks: consider DeepSeek-V3 or Qwen3 first**. Not because they're smarter than Claude, but because Chinese token efficiency is much better (the same content costs Claude roughly 1.5–2× more tokens), and the price is under 1/10th of Claude.

**Reasoning models (R1/Claude Thinking/o3) don't belong directly inside an agent loop**. See Mental Model 8.

**What this means for agent builders**: this table is not eternal truth. As of this writing (early 2026), the above judgments are based on public benchmarks and engineering practice. The model landscape may shift significantly in six months. But the selection methodology is stable: first identify task type, then filter by tool-calling stability, context length requirements, and cost ceiling.

---

### Mental Model 8: Reasoning Models vs Standard Models

**Key number**: DeepSeek-R1 processing a multi-step math problem internally "thinks" for roughly 2,000–8,000 tokens before outputting the answer. If the answer itself is 50 tokens, the thinking token cost may be 40–160× the answer cost.

Convention: **Reasoning model** = a model that generates a large volume of "thinking process" tokens before producing its final answer (e.g. OpenAI o3, DeepSeek-R1, Claude with extended thinking); **Standard model** = directly generates the answer without additional thinking output.

A reasoning model's internal mechanism is "think before answering" — implemented internally by generating a longer thinking text, then producing an answer based on that thinking. This makes it significantly outperform standard models on math reasoning, code debugging, and logic puzzles.

But it has one important limitation for agent tool calling: **format compliance rate for tool calls is unstable**. Standard models learn "when I need a tool, output this JSON format" as fixed behavior. Reasoning models may "change their mind" during the thinking process, or forget to call a tool in the correct format after finishing thinking, or stop mid-thinking within a single turn. In practice this causes parsing failures.

When to use reasoning models:
- The task itself is complex reasoning (math proofs, multi-step logic, code debug analysis)
- High latency is acceptable (thinking takes time; one inference may take 30–60 seconds)
- The task is "think clearly and do one thing" rather than "make small decisions across 20 tool call turns"

When not to use them:
- Agent loops requiring frequent tool calls (every call incurs thinking cost)
- Latency-sensitive scenarios (with streaming, users wait for thinking to finish before seeing any output)
- Tasks where format compliance matters (tool call JSON parsing)

A common trap in practice: plug DeepSeek-R1 into a ReAct loop, and it "figures out the answer" inside the thinking, stops calling tools, and outputs directly — your tools are never executed, the loop terminates early, and the user gets an answer based on the model's internal knowledge rather than what the tools actually returned.

**What this means for agent builders**: reasoning models are specialized instruments, not general upgrades. Use them for "single tasks that need deep thinking," and use standard models for multi-step agent loops.

---

## Beat 5 — Model Selection Decision Tree

*Assembling the 8 mental models into an actionable process.*

In agent development, you'll face model selection in three scenarios:

**Scenario A: API selection (using hosted models)**

First ask: **Does the task require complex reasoning (math, multi-step logic, deep analysis)?**

- Yes → consider a Reasoning model, but evaluate tool-calling needs:
  - Has tool calls → use Claude Sonnet/Opus (extended thinking mode, more controllable tool calling)
  - Pure reasoning, no tools → DeepSeek-R1 or o3-mini offer better value
- No → proceed to standard selection

Standard selection: **What's your primary concern?**

- Cost first → DeepSeek-V3 (Chinese) or Claude Haiku (English/tools)
- Chinese quality first → DeepSeek-V3 or Qwen3 (API version)
- Tool-calling stability first → Claude Sonnet family
- Very long context (>100K tokens) → Gemini 2.5 Pro or Claude (weigh cost)
- Already have OpenAI integration → GPT-4o or GPT-4o mini

**Scenario B: Local deployment selection**

First ask: **How much GPU VRAM do you have?**

- ≤ 24 GB (single consumer GPU) → 7B–13B INT4 (Qwen3-7B, Llama 3.2-8B)
- ≤ 80 GB (single A100) → 70B INT4 (Llama 3.3-70B, Qwen3-72B)
- ≤ 160 GB (dual A100/H100) → 70B FP16 or 671B MoE INT4 (DeepSeek-V3)
- Multi-node → 671B MoE FP16, API-equivalent quality

Then ask: **What are your quality requirements?**

- Quality-sensitive → choose higher precision (INT8 > INT4), or larger model INT4
- Throughput-sensitive → INT4 quantization + vLLM/llama.cpp inference framework

**Scenario C: Cost estimation**

Before designing an agent, do a back-of-envelope calculation:

```
Estimated daily cost = tokens per call × calls per day × token unit price

Example:
Per call: system prompt(2K) + conversation history(5K) + output(1K) = 8K tokens
Daily calls: 1,000
Claude Sonnet 4.5: input $3/M tokens, output $15/M tokens
Daily cost: 7K × 1000 × $3/1M + 1K × 1000 × $15/1M = $21 + $15 = $36/day = $1,080/month
```

Switch to Haiku: input $0.8/M, output $4/M → $5.6 + $4 = $9.6/day = $288/month

If quality holds, Haiku saves 73%. Do this calculation before you write the first line of agent code.

---

## Beat 6 — "Selection Decision Tree" Deliverable

This chapter has no code deliverable. But you have a portable decision framework and the following checklist, ready to reference any time:

**Model selection 10-second checklist**

1. Does the task require tool calling? → Prefer Claude Sonnet family
2. Is the primary language Chinese? → DeepSeek-V3 / Qwen3 are better value
3. Is it pure reasoning (no tools)? → Consider Reasoning models
4. Does context exceed 50K tokens? → Check that model's context window limit and real-world behavior
5. Cost-sensitive? → Estimate first, then downgrade to the model that's good enough
6. Local deployment? → VRAM ÷ 2 ≈ rough parameter ceiling in billions (FP16, GB-to-B rough conversion)

**Caveat on this chapter's limitations:**

The selection table above is based on public information from early 2026. LLM development moves extremely fast — six months from now the landscape may look significantly different. New model releases, pricing changes, and feature launches will all shift the optimal choices. What this chapter gives you is not conclusions; it's a selection methodology. The conclusions need to be validated against your own task benchmarks when you're actually building.

---

## Beat 7 — Design Note

> **Why Not Train Your Own Model?**

Readers sometimes ask: this book discusses LLMs, so why not train one from scratch?

The alternative: implement GPT-2 yourself using Raschka's *Build a Large Language Model From Scratch* or Karpathy's nanoGPT. Both resources have already done "implement Transformer from scratch through pretraining to text generation" extremely well.

If you want to understand how LLMs work internally, go read those. This book's recommendation: "You don't need to finish them — just know that in Raschka's book, Ch 4 implements GPTModel and Ch 5 completes pretraining. That's all the training intuition you need."

Why does this book focus on the harness rather than repeating that work?

- **Division of labor**: Karpathy's and Raschka's projects solve "what is an LLM." This book solves "how to use an LLM to build agents." Duplicating their work adds no value for readers.
- **Resource barrier**: training a GPT-2 scale model (124M parameters) requires hours of GPU compute; training any practically useful modern LLM requires millions of dollars. An engineer who wants to build agents doesn't need that.
- **Separate goals**: understanding LLM internals (weights, gradients, loss functions) and effectively using LLM APIs (context engineering, tool calling, model selection) are two distinct skill sets. The former is not a prerequisite for the latter.

If you're interested in training, Karpathy's zero-to-hero series and Raschka's book are currently the best entry points. Appendix D of this book lists "where to go if you want to go deeper."

If you need fine-tuning in production (not training from scratch), that belongs to a different domain — PEFT, LoRA, instruction tuning. This book doesn't cover it, because for most agent engineers, prompt engineering and model selection solve 95% of problems, and fine-tuning is a tool you reach for only after a bottleneck is clearly identified.

---

## End-of-Chapter Challenges

1. **Back-of-envelope estimation**: Your agent handles 500 user requests per day, with an average context of 10K tokens and output of 500 tokens per call. Estimate the monthly cost using Claude Sonnet 4.5 versus DeepSeek-V3. What's the difference?

2. **Selection exercise**: An agent needs to analyze a contract on behalf of a user (100-page PDF, roughly 80K tokens), identify risky clauses, and return a structured report. Give your model selection rationale, covering context length, reasoning capability, and cost as three distinct dimensions.

3. **MoE intuition**: Mixtral 8×7B has 46B total parameters but activates roughly 13B at inference time. If you have a machine with 2× RTX 4090 (48 GB total VRAM), how much VRAM does INT4 quantization require? Can this machine run it?

---

## Narrative Hook

You now have 8 cognitive cards and can make a model selection call in 30 seconds. But Lena still has only three tools: `get_time`, file read/write, and simple queries. In the next chapter, we'll build a "add tools without touching the core" registry mechanism — one that lets Lena scale elegantly to 20 tools without hardcoding any of them into the agent loop.

---

---

## Revision Log

| Version | Date | Changes |
|---------|------|---------|
| v1.0 | 2026-05-05 | Initial draft, created from scratch, covers all 8 mental models from SPEC |
