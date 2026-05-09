# Chapter 5 · Technology Selection: How to Choose Between Prompt / Few-shot / RAG / Agent / Fine-tune

> Methodology chapter · No code output · Deliverable is a print-quality decision tree

```
Full book roadmap

Ch1 → Ch2 → Ch3 → Ch4 → [Ch5 ← you are here] → Ch6 → Ch7 → ...
                                  ↑
                           Selection chapter
                      Before you write a single line of code, decide which path to take
```

This chapter starts from "what the five paths are" → works through each one systematically (motivation, applicable boundaries, when not to use it, five-dimension scoring) → and arrives at a printable decision tree. Along the way we'll hit one trap: most engineers instinctively reach for "the most familiar path" when facing a new requirement, not "the most appropriate path." This chapter exists to interrupt that instinct and build a selection intuition with actual justification behind it.

Lena writes no new code in this chapter. By the end, you have a map in your head — and you know where each technical path starting in Ch 6 sits on that map.

---

## Beat 1 — Roadmap

```
You are here: Ch5

Ch3 (Lena born: 50-line bare loop)
    ↓
Ch4 (LLM internals: engineering intuition)
    ↓
Ch5 (Technology selection: five paths, one decision tree) ← current position
    ↓
Ch6+ (Tool system, RAG, Planning… dive deep based on selection results)
```

At the end of Ch 3, Lena can run through a single tool call. Now you want her to do more — answer questions about internal company documentation, write emails in a particular style, autonomously execute multi-step tasks.

Before diving in, stop and ask one question: **Which path are you taking?**

This isn't a philosophical question. It's an engineering decision. Costs differ by 10×, data requirements differ by 1000×, latency differs by 5×. Pick the wrong one and you're not "a little suboptimal" — you're building to rebuild. And "rebuilding" in an LLM system means re-evaluating from scratch, rebuilding indexes, or retraining.

This chapter corresponds to a special node on Lena's evolution diagram: **no new code, but post-selection clarity**. After reading it, you'll be able to explain in your own words "I chose this path because…" instead of "everyone seems to be using RAG."

> **🧠 Intelligence increment (v0.4 → v0.5)**: Lena gains its first "rational selection" capability — using a five-dimension scoring framework (cost / latency / data requirements / update frequency / controllability) to make justified choices among five paths: Prompt / Few-shot / RAG / Agent / Fine-tune, rather than instinctively reaching for "the most familiar option." This chapter teaches you how to embed selection judgment into your own agent architecture decisions.

---

## Beat 2 — Motivation: Why Wrong Selection Has Extreme Costs

Start with a number: how much time does a project that shouldn't have taken the Fine-tune path typically waste?

In real production systems, an initial-scale LoRA fine-tune experiment (data cleaning + labeling + training + evaluation) requires at least 2–4 weeks. If it eventually turns out that "RAG plus a good prompt was enough," those 2–4 weeks of sunk cost cannot be recovered. Worse, a fine-tuned model is static — its knowledge freezes at the training cutoff, and every knowledge update requires retraining.

Fine-tune is a classic "over-engineering" trap. But the reverse trap exists too:

A style-adaptation task that genuinely calls for Fine-tune (e.g., "reply in my company's customer service tone") when forced through few-shot needs 20 examples stuffed into every call. That's roughly 2,000 extra tokens per API request, which at Anthropic Claude Sonnet pricing translates to about **$0.60 per 1,000 calls** in pure waste. Doesn't sound like much? At 1 million calls, that's $600 of pure waste — and it still doesn't solve the style consistency problem.

Two traps, two directions. Wrong selection means either wasting time, or continuously wasting money.

The real challenge isn't "which path is best" — every path has scenarios it fits — it's "in the first 30 minutes facing a new requirement, how do you converge quickly to the right path." That's the problem this chapter's decision tree solves.

---

## Beat 3 — Theory Foundation: The Essential Nature of the Five Paths

> *Section 3.1 — pure theory*

### 3.1 What Fundamentally Differentiates the Five Paths

Convention: **path** = the core technical approach an LLM system uses to solve a given problem; **strategy** = a specific implementation approach within a path (e.g. Few-shot is a strategy within the Prompt Engineering path). This chapter uses "path" for all five top-level choices.

Five paths, one-sentence positioning:

| Path | Essence | What it changes |
|------|---------|-----------------|
| **Prompt Engineering** | Tell the model how | Input format and instructions |
| **Few-shot / ICL** | Show the model examples | Example content in the input |
| **RAG** | Fetch resources for the model | Dynamically inject external knowledge at inference time |
| **Agent** | Give the model tools and a loop | The model's action capability and execution environment |
| **Fine-tune** | Change the model itself | Model weights |

These five paths are conceptually independent but frequently combined in engineering: an Agent can embed RAG as a tool, RAG's document filtering can be optimized with Prompt Engineering, and a Fine-tuned result can serve as an Agent's backbone model.

> *Section 3.2 — pure theory*

### 3.2 The Five-Dimension Evaluation Framework

Different paths have drastically different costs and benefits across five dimensions. You must evaluate all five simultaneously — not just "accuracy":

**Convention**:
- **Cost** = per-inference API costs + engineering maintenance costs;
- **Data requirements** = amount of labeled data needed;
- **Latency** = end-to-end response time per inference;
- **Quality** = accuracy/quality on the target task;
- **Maintenance** = ongoing maintenance complexity after system launch.

Five-dimension scoring uses 1–5 (1 = lowest cost/difficulty in that dimension, 5 = highest cost/difficulty).

> This framework comes from one of the core principles of agent design in Anthropic's engineering blog: "Success in the LLM space isn't about building the most sophisticated system. It's about building the *right* system for your needs." (Source: [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents))

> *Section 3.3 — pure theory*

### 3.3 Two Counterintuitive Facts

**Counterintuitive fact 1: Fine-tune is not "more advanced Prompt Engineering"**

At first glance Fine-tune looks like "burning your prompt into model weights" — higher accuracy, lower runtime cost. But in practice it's more like "performing surgery on the model": after surgery, the model's general capabilities may regress (catastrophic forgetting), and every knowledge update requires surgery again. Fine-tune solves **style / format / domain terminology** problems, not **knowledge update** problems. Treating Fine-tune as a knowledge injection tool is one of the most common misconceptions in this field.

> "Fine-tuning and RAG are often seen as alternatives. In practice, they solve different problems: RAG handles knowledge retrieval; fine-tuning handles behavioral alignment." — This is currently one of the most-cited engineering judgments in the field, and this book adopts it as the working definition.

**Counterintuitive fact 2: Agent is not "more complex RAG"**

At first glance Agent looks like RAG plus tool calling — it can retrieve and execute. But in practice it's more like an "operating system process" than a "query engine": it has a loop, state, and the ability to take actions. This means its errors also loop and amplify, while RAG errors only manifest at individual retrieval steps. Agent's applicable domain is **multi-step, uncertain tasks requiring dynamic decision-making** — not "I need more accurate answers to questions."

> Anthropic explicitly writes in Building Effective Agents: "many patterns can be implemented in a few lines of code," and warns that "adding unnecessary framework layers" is an anti-pattern. The implication behind that statement: exhaust simpler options before reaching for Agent.

---

## Beat 4 — Five-Path Panorama: Bird's Eye First, Then Dive

Now let's walk through each path systematically — not to celebrate it, but to find its ceiling and its floor.

Before diving into each path, start with a panoramic comparison. This is step one of selection: use the five dimensions to quickly locate which quadrant your scenario falls in.

**Five paths × five dimensions (1 = lowest cost, 5 = highest cost)**

| Path | Cost | Data requirements | Latency | Quality (target task) | Maintenance complexity |
|------|------|-------------------|---------|----------------------|----------------------|
| Prompt Engineering | ★ | ★ | ★★ | ★★★ | ★★ |
| Few-shot / ICL | ★★★ | ★★ | ★★★ | ★★★★ | ★★ |
| RAG | ★★★ | ★★★ | ★★★ | ★★★★ | ★★★ |
| Agent | ★★★★★ | ★★ | ★★★★★ | ★★★★★ (multi-step tasks) | ★★★★★ |
| Fine-tune | ★★★★ | ★★★★★ | ★★ | ★★★★★ (target domain) | ★★★★ |

How to read this table: don't look for a row where everything is lowest — that path doesn't exist. Look for "the path where your most critical dimension is acceptable and no other dimension exceeds your budget."

**Three most common misselection patterns**

Looking at this table instinctively produces three kinds of wrong choices:

1. **"Fine-tune has the highest quality, so pick Fine-tune"** → ignores data requirements and maintenance cost, plus the fact that it can't solve knowledge update problems.
2. **"Agent can do everything, so pick Agent"** → ignores cost multiplication and error amplification; it's over-engineering for fixed-process tasks.
3. **"Prompt is free, start with Prompt and see"** → a reasonable starting point, but if the task is fundamentally a knowledge retrieval problem, even the best prompt won't help; deciding early saves effort.

Now, with this panoramic view in hand, let's go into the detail of each path.

---

### 4.1 Path One: Prompt Engineering

**One-sentence positioning**: Prompt Engineering is the lowest-cost, closest-to-hand path of the five. It lets you improve LLM output quality by adjusting input text without changing any infrastructure. Its ceiling is higher than most people think — and its floor is too. There are problems it simply cannot reach.

**Five-dimension scoring**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Cost | ★★★★★ | Near-zero additional cost; only consumes instruction tokens |
| Data requirements | ★★★★★ | No labeled data needed; iterating prompts manually is sufficient |
| Latency | ★★★★☆ | Slightly higher than bare API calls (extra processing time for instruction tokens) |
| Quality | ★★★☆☆ | Lower ceiling for complex tasks |
| Maintenance | ★★★★☆ | Prompt version management is simple; iteration depends on subjective judgment |

**3 scenarios where it works**

1. **Structured output formatting**: ask the model to output JSON, XML, or a specific template. "You are a parser. Convert the following text into `{"name": ..., "date": ...}` format." This kind of task is fully handled by a prompt — no RAG or Fine-tune needed.

2. **Tone/persona setting**: a customer service bot that needs a "friendly, concise, no-apologies" tone. Writing it in the system prompt is 100× faster than fine-tuning, and you can change it any time.

3. **Chain-of-Thought (CoT) activation**: adding "Let's think step by step" to a reasoning problem improved accuracy by an average of 15–30% on models before o1 (Source: Wei et al., 2022, [Chain-of-Thought Prompting Elicits Reasoning in Large Language Models](https://arxiv.org/abs/2201.11903) — you don't need to read the full paper, just know: providing a thinking-steps instruction significantly improves reasoning tasks).

**3 scenarios where it doesn't work**

1. **Knowledge-intensive QA**: if a user asks "what was our company's Q3 2024 revenue," no amount of prompt quality helps — the model simply doesn't have this data. That's RAG's territory, not prompt's.

2. **Style tasks requiring extreme consistency**: you want all outputs to strictly follow a specific writing style (e.g., standard wording in legal contracts). Even with detailed prompts, style will drift across different token sampling runs. This is a scenario Fine-tune handles but prompt handles poorly.

3. **Long-term memory tasks**: users want the agent to remember a preference from three months ago. The context window is finite; prompt engineering cannot solve cross-session persistent memory.

---

### 4.2 Path Two: Few-shot / In-Context Learning

**One-sentence positioning**: Few-shot is about "showing the model examples" rather than "telling the model how." When behavior is easier to demonstrate than to describe, few-shot outperforms lengthy instructions. But its cost grows linearly with the number of examples — every additional shot costs those tokens on every call.

**Five-dimension scoring**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Cost | ★★★☆☆ | Every call carries example tokens; cost scales with N |
| Data requirements | ★★★★☆ | Requires 5–30 high-quality examples; far fewer than Fine-tune |
| Latency | ★★★☆☆ | Each shot adds roughly 200–500 tokens of processing time |
| Quality | ★★★★☆ | With high-quality examples, matches Fine-tune for format/style tasks |
| Maintenance | ★★★★☆ | Low cost to maintain example libraries; can swap examples immediately |

**Where is the N-shot boundary?**

Few-shot has an engineering rule of thumb: when the number of examples exceeds 20–30, the marginal benefit of adding more approaches zero while cost continues to grow linearly. This isn't a fixed number — it depends on task complexity — but it signals a decision point: **if you're already using 20+ shots and results are still unsatisfactory, the problem isn't in the number of examples; the task itself calls for a different path.**

Another boundary is the context window. When examples total + user input + system prompt exceeds roughly 60% of the context window, the model's attention starts to get "lost in the middle" (Lost in the Middle, Shi et al., 2023) and accuracy drops.

**3 scenarios where it works**

1. **Rapid format adaptation**: you have 10 "good" example outputs and want the model to mimic the same format and tone, but don't have enough data for fine-tuning yet. Few-shot is the optimal solution for this period.

2. **Low-frequency specialized tasks**: a task that runs only 50 times per day makes fine-tune ROI extremely low, but zero-shot is inconsistent. Few-shot with 20 examples costs about 1,000 extra tokens per call, totaling roughly $0.05 per day for 50 calls — completely reasonable.

3. **Feasibility validation before fine-tuning**: before committing to fine-tune, use few-shot to verify the task is learnable. If 30-shot still performs poorly, fine-tuning almost certainly won't help either — the task definition itself has a problem.

**3 scenarios where it doesn't work**

1. **High-frequency calls + cost sensitivity**: with 1 million daily calls, each carrying 20 shots (roughly 2,000 extra tokens), at Claude Sonnet input pricing the daily extra cost is roughly $600, or $18,000/month. At this scale, the one-time cost of fine-tuning almost certainly wins.

2. **Tasks requiring precise recall of large amounts of knowledge**: your examples are essentially attempting to make the model "remember" large amounts of information (e.g., specs for 50 products). This isn't few-shot's strength — the model will "compress" this information rather than recall it precisely. This is a RAG scenario.

3. **Dynamically updating knowledge**: if example content needs daily updates (e.g., prices, inventory), maintaining the few-shot example library becomes a burden in itself. RAG can retrieve from real-time data sources — far better.

---

### 4.3 Path Three: RAG (Retrieval-Augmented Generation)

**One-sentence positioning**: RAG is "fetching resources for the model at inference time" — the model doesn't need to memorize all knowledge, but can retrieve the right documents when needed. It's the most frequently appearing technology in AI Agent systems (LinkedIn job data: 75% of AI agent positions list RAG experience as a requirement), but it's not a cure-all: if the retrieval fails, RAG is just an expensive prompt.

**Five-dimension scoring**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Cost | ★★★☆☆ | Vector retrieval infrastructure + embedding API costs + per-retrieval token costs |
| Data requirements | ★★★☆☆ | Requires a document corpus, no labeling needed; but document quality directly determines RAG quality |
| Latency | ★★★☆☆ | Extra retrieval latency (typically 50–200ms) plus injected context tokens |
| Quality | ★★★★☆ | Dramatically better than pure prompt on knowledge-intensive tasks; depends on retrieval quality |
| Maintenance | ★★★☆☆ | Index needs to be rebuilt or incrementally updated as documents change |

**Four core decision points in RAG** (implementation details in Ch 9; decision perspective only here)

RAG is not just "plug in a vector database." It's the combination of four independent engineering decisions:

1. **Chunking strategy**: how do you split documents? Fixed-length (simple, medium quality) vs. semantic chunking (better results, more complex implementation). Wrong chunking strategy causes critical information to straddle chunk boundaries, making both halves insufficiently relevant at retrieval time.

2. **Embedding model**: which vector model? OpenAI text-embedding-3-large has good results but is expensive; local BGE-M3 is strong for Chinese but requires running your own inference service. Higher vector dimensions mean higher storage and retrieval costs.

3. **Retrieval method**: pure vector search vs. Hybrid Search (BM25 + vector). Pure vector search misses precise terms (product model numbers, code snippets); Hybrid Search provides a safety net.

4. **Reranking**: rerank with a Reranker after top-K retrieval. Skipping rerank and directly using the top-5 often includes insufficiently relevant documents at position 5.

Each of these four decision points has a "default option" (for quick launch) and an "optimized option" (quality-first). Ch 9 will expand on each. 

**3 scenarios where it works**

1. **Enterprise knowledge base QA**: 100-page internal wiki, 1,000 historical emails, 500 product spec documents — too much to put in a prompt, too proprietary to train a general model on, RAG is the only sensible choice. A real data point: Anthropic reported in its Contextual Retrieval blog that prepending a context summary to each chunk on top of standard RAG reduced retrieval failure rates by roughly 49% (Source: [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)).

2. **Real-time or frequently updated knowledge**: news, stock prices, user behavior data — these can't be fine-tuned (too slow, too expensive), can't be pure prompt (the model doesn't know), need RAG to retrieve in real time.

3. **Scenarios requiring source citations**: legal, medical, and financial contexts require the agent to provide "which document, which page does this sentence come from." RAG supports this natively, because you know which chunk was retrieved; pure prompt and Fine-tune have no such capability.

**3 scenarios where it doesn't work**

1. **Badly structured document corpus**: if your knowledge base is full of poorly formatted, outdated, heavily duplicated documents, RAG will feed garbage to the model — results may be worse than zero-shot. "Garbage in, garbage out" is amplified in RAG.

2. **Reasoning-intensive tasks**: a user asks "based on our company's data, if we increase budget by 20%, which channel has the best ROI?" RAG can retrieve the data, but multi-step reasoning and decision-making is Agent's job, not RAG's.

3. **Extremely latency-sensitive scenarios**: real-time voice conversation (< 200ms target latency). Vector retrieval + rerank + token injection is hard to complete within this time window. These scenarios either use Fine-tune to bake knowledge into the model, or use pure prompt with a minimal specialized context.

---

### 4.4 Path Four: Agent (main thread of this book)

**One-sentence positioning**: Agent is "giving an LLM tools and a loop," enabling it to perceive its environment, take actions, and adjust next steps based on results. It has the widest capability boundary of the five paths, but also the highest complexity and hardest debugging.

**Convention**:
- **Workflow** = a predefined sequence of fixed steps, with LLM filling in content at each step;
- **Agent** = the LLM autonomously decides steps, dynamically choosing tools and adjusting its path.

This book treats both as the Agent path, but will distinguish between them in the decision tree.

**Five-dimension scoring**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Cost | ★★☆☆☆ | Multiple LLM calls + tool call costs; a single task may trigger 10–50 LLM calls |
| Data requirements | ★★★★☆ | No training data needed; but requires designing tools and prompts |
| Latency | ★★☆☆☆ | Multi-step execution; latency accumulates with step count; not suitable for real-time response |
| Quality | ★★★★★ | On multi-step, uncertain, tool-requiring tasks it's the only viable path |
| Maintenance | ★★☆☆☆ | Every tool change requires re-evaluating agent behavior; errors amplify in loops |

**"When Not to Use Agents"**

Anthropic dedicates a section of Building Effective Agents to when not to use agents — the most overlooked section in that document:

> "Agents are better suited for open-ended problems where it's difficult or impossible to predict the required number of steps, and where you can't hardcode a fixed path. This increased autonomy also comes with higher costs."

Translated into decision tree language: **if a task's execution path is predictable, the step count is fixed, and no dynamic decision-making is needed — don't use an Agent; use a workflow instead.**

This is what the Design Note in this chapter will expand on. For now, just internalize this principle: Agent complexity is a cost, not a reward.

**3 scenarios where it works**

1. **Open-ended tasks requiring multiple tools**: "Research my competitors' pricing strategy and compile a report." This task requires searching, reading, synthesizing, and writing — step count is variable and tool combinations are unpredictable. This is Agent's home turf. In real production systems, this kind of research task automation can compress what previously required 2–3 hours of manual searching into 5 minutes.

2. **Cross-system operations**: "Read the last 10 customer feedback emails, update the corresponding fields in CRM, then email customers who need follow-up." This task spans email, CRM, and outgoing mail across three systems, with step count dependent on data and dynamic judgment required throughout. A workflow can't do this; an agent can.

3. **Long-running autonomous tasks**: crawling industry news every morning, analyzing key information, generating summaries, and sending to a specified channel — these always-on, unattended, event-triggered tasks can only be done by an agent. No other path has this capability at all.

**3 scenarios where it doesn't work**

1. **Fixed-process tasks**: "every time a user submits a form, format the data and write it to the database." This is a deterministic two-step operation that should be hardcoded as a function. Using an agent is over-engineering, and every call triggers an LLM call costing roughly $0.001 — pure waste at scale.

2. **Real-time low-latency requirements**: voice conversations, game NPC real-time reactions (< 300ms). An agent's multi-step execution is inherently serial waiting — it cannot meet these latency requirements.

3. **High-certainty compliance scenarios**: a bank's loan approval process, a medical laboratory result interpretation — these scenarios require **fully traceable** decision paths and **zero hallucination tolerance**. Current LLM reliability isn't at the point where it can handle these cases with zero human review (this is one of the most unsolved problems in the field right now; as of writing, the most pragmatic approach is "human-in-the-loop + agent as assistant," not fully autonomous agent).

---

### 4.5 Path Five: Fine-tune

**One-sentence positioning**: Fine-tune is "changing the model itself" — not adjusting inputs, but changing weights. It solves the problem of "how the model behaves and sounds," not the problem of "what the model knows." This distinction is massively overlooked in practice and is the most important point in this section.

**Five-dimension scoring**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Cost | ★★☆☆☆ | Training cost (even LoRA requires GPU time) + hosted inference cost |
| Data requirements | ★☆☆☆☆ | SFT needs 500–5,000 high-quality example pairs; DPO needs preference comparison data |
| Latency | ★★★★★ | Inference latency same as base model, or even lower (small model fine-tuned) |
| Quality | ★★★★★ | Significantly better than other paths in target domain/style (given good data quality) |
| Maintenance | ★★☆☆☆ | Knowledge updates require retraining; catastrophic forgetting requires continuous monitoring |

**SFT / DPO / LoRA — how to choose?**

These three aren't parallel options — they operate at different levels:

- **SFT (Supervised Fine-Tuning)**: given input, demonstrate correct output. Good for "learning to do a class of tasks" (e.g., write reports in a specific format).
- **DPO (Direct Preference Optimization)**: given two outputs, label which is better. Good for "adjusting style preferences" (e.g., more concise vs. more detailed).
- **LoRA (Low-Rank Adaptation)**: an efficient implementation of SFT or DPO; only updates a small number of parameters during training, significantly reducing GPU cost and catastrophic forgetting risk.

> This book doesn't expand on Fine-tune implementation details — Raschka's *Build an LLM from Scratch* and Karpathy's zero-to-hero have already done this thoroughly. This book focuses on the harness; Fine-tune is a tool outside its boundary. If your scenario genuinely needs Fine-tune, those two resources are the right destination.

**3 scenarios where it works**

1. **High consistency for domain-specific terminology and writing style**: a law firm's contract drafting style has strict standards (wording, format, clause ordering); few-shot stability isn't enough, and post-fine-tune output consistency is significantly better.

2. **High-frequency calls on fixed tasks + cost sensitivity**: a sentiment analysis task with 1 million daily calls; the base model with detailed prompts is inconsistent. Fine-tuning a small model (e.g., Llama 3.1-8B LoRA) reduces inference cost by 10× and enables local deployment, eliminating API dependency.

3. **Security/compliance requirements preventing external API calls**: financial institutions and government departments whose data cannot be sent to external LLM APIs. Fine-tuning an open-source model on internal servers is the only viable path.

**3 scenarios where it doesn't work**

1. **Knowledge injection**: attempting to fine-tune the model to "remember" internal company documents. Fine-tune makes the model "tend toward certain types of answers" but cannot reliably remember specific facts (dates, numbers, names). Knowledge injection is RAG's job, not Fine-tune's. This is the most common misconception in the community, bar none.

2. **Rapid iteration phase**: the product is still finding product-market fit, requirements change weekly. Fine-tune's data preparation and training cycle is measured in weeks — it can't keep up with this pace. Until requirements stabilize, stick with Prompt Engineering + RAG.

3. **Enhancing tool-calling capability**: want the model to call tools better? Improving tool documentation and schema design (ACI principles) is far more effective than fine-tuning, at three orders of magnitude lower cost. Fine-tuning tool-use capability is an extremely poor use of effort, especially since the existing mainstream models (Claude, GPT-4o, Qwen3) already have strong tool-use out of the box.

---

## Beat 5 — Quick Reference: All Terms in This Chapter

This section is a terminology anchor for reference. When you encounter an unfamiliar term in later chapters, come back here.

**Convention (unified definitions for this book)**:

- **Embedding** = the process of converting text into a high-dimensional vector; the **vector** is the result, the **embedding model** is the tool.
- **Reranking** = re-sorting retrieval results to put the most relevant document first. (Not embedding — it's cross-encoder scoring.)
- **Hybrid Search** = combining keyword search (BM25) + semantic vector search, unioning results then reranking.
- **Guardrails** = constraint and filtering mechanisms on agent input/output, ensuring the agent doesn't execute dangerous operations or generate harmful content.
- **Evals** = systematic evaluation of LLM system performance, including automated test sets, LLM-as-judge, and human review.
- **MCP (Model Context Protocol)** = a tool and context protocol standard proposed by Anthropic, enabling LLMs to connect to external tools and data sources in a unified way.
- **ACP (Agent Communication Protocol)** = a protocol standard for communication between agents (standardization in progress).
- **A2A (Agent-to-Agent)** = a mechanism for direct interaction and task delegation between agents, without going through a unified coordination layer.
- **Observability** = the observability of an agent system, including logs, traces, and metrics, letting you see "what the agent is thinking and doing."
- **ICL (In-Context Learning)** = a model learning from examples in the context without gradient weight updates. Few-shot is its typical form.
- **LoRA** = Low-Rank Adaptation, an efficient fine-tune implementation.
- **SFT** = Supervised Fine-Tuning.
- **DPO** = Direct Preference Optimization, optimizing model output style via preference comparison data.
- **Catastrophic Forgetting** = the phenomenon where a model, while learning a new task during fine-tuning, forgets its previously acquired capabilities.
- **Context Rot** = the degradation of a model's ability to accurately recall early information as context grows longer (Source: Anthropic Context Engineering).

---

## Beat 6 — Selection Decision Tree (Print Quality)

Now let's build the decision tree. Starting from one question, walk to the final path recommendation.

```
┌─────────────────────────────────────────────────────────────────┐
│               Technology Selection Decision Tree v1.0            │
│                                                                   │
│         Starting point: you have a new LLM requirement           │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────┐
        │ Q1: Is the task execution path  │
        │ fully predictable?              │
        │ (fixed steps, no dynamic        │
        │  decision-making needed)        │
        └─────────────────────────────────┘
             │                    │
            YES                   NO
             │                    │
             ▼                    ▼
    ┌─────────────┐    ┌──────────────────────────┐
    │ → Workflow  │    │ Q2: Does the task need to  │
    │ (hardcode   │    │     access knowledge from  │
    │  step seq.) │    │     after training cutoff, │
    └─────────────┘    │     or org-internal data?  │
                       └──────────────────────────┘
                                │              │
                               YES             NO
                                │              │
                                ▼              ▼
                     ┌──────────────┐  ┌───────────────────────┐
                     │ Q3: How often│  │ Q5: Does the task have │
                     │ does this    │  │ very high requirements │
                     │ knowledge    │  │ for style/format       │
                     │ update?      │  │ consistency that       │
                     └──────────────┘  │ current prompting      │
                       │         │     │ approaches can't meet? │
                      High       Low   └───────────────────────┘
                       │          │              │              │
                       ▼          ▼             YES             NO
               ┌──────────┐  ┌──────────┐       │              │
               │ → RAG    │  │ Q4: Does │       ▼              ▼
               │ (live    │  │ knowledge│  ┌─────────┐  ┌──────────────┐
               │  index)  │  │ exceed   │  │→ Fine-  │  │ Q6: How many │
               └──────────┘  │ 30% of   │  │  tune   │  │ high-quality │
                             │ context? │  └─────────┘  │ examples?    │
                             └──────────┘               └──────────────┘
                               │      │                    │          │
                              YES     NO                 5–30        0–5
                               │      │                    │          │
                               ▼      ▼                    ▼          ▼
                         ┌──────────┐ ┌──────────┐  ┌─────────┐  ┌────────────┐
                         │ → RAG    │ │→ Few-shot │  │→ Few-   │  │→ Prompt    │
                         │ (corpus  │ │ or Fine-  │  │  shot   │  │ Engineering│
                         │  index)  │ │ tune both │  └─────────┘  └────────────┘
                         └──────────┘ │ work here │
                                      └──────────┘
                                           │
                                           ▼
                              ┌──────────────────────┐
                              │ Decision aid:         │
                              │ Fine-tune when call   │
                              │ volume > 500K/month.  │
                              │ Otherwise start with  │
                              │ Few-shot.             │
                              └──────────────────────┘
```

**Stacking rules**: the five paths above are not mutually exclusive. The most common production architecture is:

```
Agent (decision loop)
  ├── RAG tool (knowledge retrieval)
  ├── Prompt Engineering (system prompt for each tool)
  └── Optional: Fine-tuned backbone model (for extremely high-frequency scenarios)
```

This stacked architecture covers the technical structure of the majority of real-world AI agent products. Chapters 6–9 of this book implement it layer by layer.

**Quick mapping from common scenario to path**

| Scenario description | Recommended path | Reason |
|---------------------|------------------|--------|
| Formatting / structured output | Prompt | No external data needed, adjust instructions |
| Sentiment analysis (1M/day) | Fine-tune | High-frequency + fixed task, amortize cost |
| Enterprise internal doc QA | RAG | Proprietary knowledge, frequent updates, source citation needs |
| Code debugging / analysis | Agent + tools | Need to execute code, read files, iterate |
| Tone / brand voice consistency | Fine-tune or Few-shot | Style problem (behavior), not knowledge problem |
| Real-time news summary | RAG (live index) | Knowledge recency critical, daily updates |
| Cross-system automation | Agent | Multi-tool, multi-step, uncertain path |
| Low-frequency but high style consistency | Few-shot | Low frequency, Fine-tune ROI insufficient |
| Open-ended research task | Agent + RAG | Retrieval + multi-step reasoning needed |
| Security/compliance (data sovereignty) | Fine-tune (local deployment) | Data sovereignty requirements |

---

## Beat 7 — Design Notes × 2

---

> ### Design Note 0: The Selection Triangle — Capabilities, Speed, Cost
>
> Anthropic's architecture white paper summarizes the core framework for model selection: **capabilities, speed, and cost** form an irreconcilable triangle — within a fixed model family, you can only trade off between the three, never optimize all simultaneously.
>
> The white paper uses a direct analogy:
>
> > "Think of it like choosing the right tool from a toolbox: you wouldn't use a sledgehammer to hang a picture frame."
>
> The engineering implication: **use a light model (Haiku) for simple tasks, a heavy model (Opus) for complex reasoning — using an expensive model for simple tasks "isn't just wasteful; at scale, costs compound quickly."**
>
> Translate this principle into the language of this chapter's five-path selection: once you've picked a path (e.g., Agent), the next question isn't "which model is best" — it's "what's the task complexity at this step, and how capable a model does it require?" Orchestrators handle planning (requiring strong reasoning, use Sonnet or Opus); Workers handle individual deterministic steps (Haiku works fine). The cost difference between them is typically 5–20×. In a system with 10 concurrent Workers, choosing the wrong model means paying 10–20× more per task.
>
> Practical rule: label each agent step as "planning layer" or "execution layer." Use heavy models for the former, light models for the latter.
>
> (Source: Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*, 2025, p.8)

---

> ### Design Note 1: Architecture Selection Three-Question Framework + The Hidden Costs of Multi-agent
>
> Anthropic's white paper, discussing when to upgrade from single agent to multi-agent, presents a three-question decision framework (p.23):
>
> 1. **How high is the control requirement?** High-control scenarios (compliance audits, financial transactions, medical decisions) → prefer Single agent + sequential workflow, where every step is traceable, auditable, and rollback-capable. Multi-agent autonomy is a burden in these scenarios, not an advantage.
> 2. **How complex is the problem domain?** Single-domain tasks (enterprise knowledge base QA, targeted data analysis) → Single agent is enough. Cross-domain coordination needed (simultaneously analyzing code, financials, and user behavior) → Multi-agent's specialization division is where it earns its value.
> 3. **What are budget and token constraints?** Multi-agent architectures consume **10–15× the tokens** of a single agent — each sub-agent has its own context window, system prompt, and tool call overhead. If your monthly token budget is $500, plan for 5–7× cost growth before going multi-agent.
>
> (Source: Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*, 2025, p.23)
>
> These three questions also give a clear evolution path:
>
> > "You can deploy a single agent in weeks. Multi-agent systems take months to get right. Build something that works, then enhance."
>
> Translated into engineering decision language: use single agent to get the task working, validate feasibility, and establish an eval baseline; only make the minimal multi-agent changes once the single agent's bottleneck (insufficient parallelism, a subtask needing a specialized model) clearly emerges. Don't add architectural complexity before you've hit the bottleneck.
>
> This chapter's five-path selection and the three-question framework above are complementary: the five paths answer "what technical approach," the three-question framework answers "how many agents to run it with" — getting both selection dimensions right is what constitutes a complete architecture decision.

---

> ### Design Note A: RAG vs Fine-tune — Why the Community Misunderstands This as Binary
>
> **You may have heard this argument**: "When you have enough data, you should Fine-tune instead of RAG — the model remembering knowledge is more efficient than retrieving it each time."
>
> The problem with this argument is that it conflates two entirely different things:
>
> - Fine-tune solves a **behavior problem**: the model's output style, format, and reasoning tendencies.
> - RAG solves a **knowledge problem**: what information the model can access during inference.
>
> Existing evidence (including research from Anthropic, OpenAI, and Google DeepMind) shows that fine-tuning cannot reliably "memorize" factual knowledge — especially specific numbers, dates, and proper nouns. What it changes is "a tendency to answer this way," not "precisely knowing what this number is."
>
> **Practical engineering strategy (best practices as of writing)**:
>
> - 🟢 **RAG first, almost always**: for any scenario requiring access to external knowledge, start with RAG. If RAG can solve the problem, don't take the detour to Fine-tune.
> - 🟡 **Fine-tune stacked on RAG**: when RAG accuracy is already good but output style is inconsistent, consider fine-tuning a better "formatting/styling" layer on top of RAG.
> - 🔴 **Fine-tune replacing RAG**: this combination has almost no valid use case, except when your knowledge base is static and never updates, and call frequency is so high that RAG cost is unbearable.
>
> **Tradeoff summary**:
> - Fine-tune can't hot-update; RAG can (swap documents)
> - Fine-tune requires large labeled datasets; RAG only needs documents
> - Fine-tune infers faster; RAG has retrieval latency
> - Fine-tune changes behavior; RAG adds knowledge
>
> This isn't binary. In production systems, they frequently coexist.

---

> ### Design Note B: Agent Is Not a Silver Bullet — Anthropic Says So
>
> **Common misconception**: Agent is "the most powerful path" and can solve all LLM application problems.
>
> **Anthropic's official position** (Source: [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)):
>
> > "Many patterns can be implemented in a few lines of code...We recommend not using agentic frameworks, or using them very lightly, until you understand the underlying principles."
>
> Anthropic explicitly lists characteristics indicating you should not use an Agent:
> - Task path is predictable → use workflow, not agent
> - Task step count is fixed → use workflow, not agent
> - Error cost is extremely high (irreversible operations) → exhaust deterministic approaches first; if using an agent, mandate human-in-the-loop
>
> **Agent's real value** lies in "openness": when task step count is unpredictable, tool combinations vary by situation, and dynamic judgment is required — then Agent is necessary, not just "cooler."
>
> **Tradeoff summary**:
> - 🟢 Agent can do things other paths can't: multi-step autonomous execution, tool composition, cross-system operations
> - 🔴 Agent cost multiplier: 10 LLM calls per task = 10× cost
> - 🔴 Agent error amplifier: small errors in each step accumulate in the loop, eventually derailing completely
> - 🔴 Agent debugging difficulty: non-determinism means hard reproducibility — this is one of the engineering problems with the fewest good answers
>
> If your first reaction to a new requirement is "use an Agent," stop and ask first: "If I hardcoded the steps of this task and wrote it as a function, would that be enough?" If yes — don't use an Agent.

---

---

## End-of-Chapter Hook

The decision tree is built, but every branch on the tree is a door not yet opened.

The nearest door is **Ch 6: Tool System** — the infrastructure of the Agent path. You chose Agent in the decision tree; the next step is understanding the boundary of the "tool" concept: what is a tool, how do tools get registered, how do tools execute concurrently, how are tools safely exposed to the LLM.

In Ch 3, Lena had only one tool (`get_time`). By the end of Ch 6, she'll have four tools — plus a "add tools without touching the core" registration mechanism. That's the first step from personal toy to production system.

---

*Sources for this chapter:*
*- Anthropic Engineering Blog: [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)*
*- Anthropic Engineering Blog: [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)*
*- Anthropic Engineering Blog: [Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)*
*- Wei et al. (2022). Chain-of-Thought Prompting Elicits Reasoning in Large Language Models. [arXiv:2201.11903](https://arxiv.org/abs/2201.11903)*
*- R10 LinkedIn JD commonality analysis (internal research report, 26 complete JD samples)*
*- Prompt Engineering Guide / DAIR.AI: guides/fewshot.en.mdx, guides/rag.en.mdx (local clone)*
