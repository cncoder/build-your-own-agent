# Chapter 1: Hello, Agent — Starting with One API Call

---

## Beat 1 — Roadmap

```
Full book roadmap (26 chapters)

Ch1 ← you are here
 │  Mental models + Day-0 API call
 ▼
Ch2  The ReAct loop explained
 ▼
Ch3  Lena is born (50 lines, first real tool)
 ▼
Ch4  LLM internals quick reference (methodology chapter)
 ▼
Ch5-12  Six Pillars: Tools / Streaming / Memory / Context / Planning / Skills
 ▼
Ch13-18  Safety pair + always-on (Telegram / Heartbeat / Cron)
 ▼
Ch19-25  MCP / Sandbox / Evals / Specialization / Browser Agent
```

**Chapter arc**: Starting from "what does an LLM feel like," through three layers of mental models (LLM as function / Agent as program / Tool Use as the bridge between them), and arriving in section 6 where we run the first API call in ≤30 lines of Python — the pitfall along the way being the format differences between three providers, and Bedrock's model ID not being the name you'd expect.

**Lena's version change**: By the end of this chapter, Lena goes from v0.0 (nothing) to v0.1 — a minimal skeleton that can print a single model reply. She can't yet remember, call tools, or loop. But she's **alive**. This is the most important step in the book: from zero to something.

This chapter doesn't front-load code. The first 80% builds mental models; the last 20% runs the API. This ordering is intentional: **intuition precedes code; only then can code be truly understood** (inspired by the "no-code" strategy of rasbt/LLMs-from-scratch Ch01, R7-G §4 #1).

> **Intelligence increment (v0.0 → v0.1)**: Lena makes her first request to an LLM and receives a real response — from zero lines of code to a minimal skeleton that can print model output, leaving behind hard-coded if/else logic entirely. This chapter teaches you how to wire "let a language model make decisions" into your own agent.

---

## Beat 2 — Motivation: Why Not Just Use an Existing Product?

Here's a simple test. Open any packaged LLM product, type "Is it raining in my city right now?" — the answer is almost certainly "I'm unable to query real-time weather."

That's not the model being unintelligent. That's **the product not giving it a tool**.

Now try the same thing differently: attach a `weather_api` tool to the same model and ask the same question. It will call the tool, read the response, then synthesize an answer: "It's cloudy today, high of 32°C, you might want to bring an umbrella." Same model, from "I don't know" to "let me check and give you a synthesized answer."

That gap comes from **whether you control the model's tools, memory, and loop**.

With a packaged product, all three are built-in and fixed. Calling the API directly, all three are yours to define.

The concrete difference across several dimensions:

| Dimension | Packaged product | Direct API |
|-----------|-----------------|------------|
| Tools | Built-in, fixed — you can't change them | You define them, infinitely extensible |
| Memory strategy | Fixed window, no control | You control compression and persistence |
| Cost | Subscription, per-seat pricing | Per-token, tiered by model |
| Observability | Black box, hard to debug | Every request fully logged, every step traceable |
| Model selection | Single model or fixed bundle | Swap providers and models anytime |
| Integration | Closed product, their interface only | Integrate into any system |

The cost tiering row deserves a note. In a real production system, when an agent needs to execute thousands of sub-tasks — research tasks, summarization tasks, formatting tasks — these sub-tasks don't need the most expensive model. The strategy of "use a large model for complex planning, use a fast model for simple execution" can reduce the total bill by 20-30x while keeping quality comparable. That kind of fine-grained control is only possible when you're calling the API directly.

As Andrej Karpathy put it: "We are at the start of the decade of agents — requiring patience and persistent human-in-the-loop oversight." This book doesn't sell "Year of the Agent" anxiety. It takes a ten-year view and walks with you as you build Lena from scratch.

So here we go. This chapter's mission is to walk you through that door: from being a *user* of models to being a *builder* of them.

---

## Beat 3 — Theory

> *Pure theory. This section has three subsections, each building one layer of mental model. By the end of all three, you'll understand what LLMs can do, what they can't, and how agents fill in the "can't."*

### 3.1 LLM: A Function with a Cutoff Date

Convention: **LLM** = Large Language Model; **prompt** = the sequence of text fed into the model; **completion** = the sequence of text the model generates. These three terms are used consistently throughout; they won't be mixed with "input," "output," or "reply."

The most accurate engineering mental model for an LLM is **a function** — a mapping that given an input deterministically produces an output:

```
completion = LLM(prompt)
```

This function perspective is enormously useful because it dissolves a lot of misconceptions. It has three essential characteristics that, once understood, will make many "why can't the model do X" questions obvious:

**Characteristic 1: Stateless.** Each call is independent; they don't know about each other. Tell it "my name is Alice" in the first conversation, and it has completely forgotten by the second conversation — unless you **put the previous conversation's content into the current prompt**. That's why "multi-turn conversations" are an engineering problem: the programmer is responsible for appending history, the LLM has no memory mechanism. Memory is given by the programmer, not native to the model.

**Characteristic 2: Single-shot generation.** It only produces text; it executes no actions. It can *write* "call the weather API," but it won't actually *call* it — unless you (as the programmer) read those words, manually execute that API, then paste the result back into the prompt. Tool-calling capability is the **parsing and execution** of the LLM's output by your program, not a native capability of the LLM itself.

**Characteristic 3: Knowledge cutoff.** Training data has a cutoff; it doesn't know what happened afterward. This isn't a bug — it's the nature of the beast. An LLM is a compression and extraction of its training data, a system that "knows what it learned," not a real-time information system. Today's weather, today's stock price, a freshly published API doc — it doesn't know these things unless you use a tool to look them up on its behalf.

These three characteristics together explain why an LLM itself is not an agent: **it has no persistence (stateless), no agency (single-shot), no currency (cutoff date)**. These three limitations are the engineering problems this book unpeels one layer at a time.

### 3.2 Agent: A Program, Not a Call

Convention: **Agent** = a program built around an LLM, using loops, tool calls, and memory mechanisms to extend the LLM's single-shot generation capability into multi-step autonomous execution; **Tool** = an external capability the agent can invoke during execution (get the time, read a file, search the web, execute code…); **Memory** = mechanisms by which the agent retains and retrieves information during execution, including current session history (short-term) and cross-session persistence (long-term).

The simplest way to distinguish LLM from Agent: **LLM is a function, Agent is a program**.

A program has loops, state, and side effects; it can execute many steps. The minimum form of an agent is a while loop around an LLM:

```
Goal input
    │
    ▼
[LLM decides] ──→ "Need to run tool X(arg Y)" ──→ [Execute X(Y)] ──→ Result appended to context
    │                                                                   │
    ◄───────────────────────────────────────────────────────────────────
    │
    ▼
[LLM decides] ──→ "Task complete, output final reply"
    │
    ▼
  Done
```

This loop has an academic name: **the ReAct loop** (Reasoning + Acting). In the paper *ReAct: Synergizing Reasoning and Acting in Language Models* (Yao et al., ICLR 2023, arxiv: 2210.03629), researchers found that alternating the LLM's thinking steps (Thought) with action steps (Action), and feeding the tool's returned results (Observation) back to the model, significantly outperforms pure generation on complex tasks. You don't need to read the whole paper — you just need to know it validated one thing: **loop + tool + observation is the key structure bridging LLM and agent**.

This chapter doesn't implement this loop — that's Ch3's job. The point here is to build the intuition: the loop isn't "a coding technique," it's the **essential difference** between agent and LLM. In a very real sense, the entire work of an agent engineer is designing every detail of this loop: when does the loop stop, how are tools defined, how is memory managed, how are errors handled.

Following this line of thinking, the word "agent" is used extremely loosely in the field — some people call an LLM with one tool added an agent, others use it for entire multi-model collaboration systems. Simon Willison (simonwillison.net) has directly criticized this word's drift: "most of the people who use it seem to assume that everyone else shares and understands the definition" (2024-12-20). This book adopts the definition Anthropic gave in *Building Effective Agents* (2024-12-19) as its operational standard: an agent is "LLMs using tools based on environmental feedback in a loop" — **an LLM system that uses tools in a loop based on environmental feedback**. This is the shared starting point for all subsequent discussion in this book.

### 3.3 Three APIs: Same Thing, Three Dialects

Lena, this book's through-project, needs to be able to switch between different model providers — because in real engineering you might need to switch providers due to cost, compliance, latency, or features. Before getting to code, let's understand the core **format** differences between the three providers. It's not about which is better; their interface designs reflect different engineering decisions. Understanding those decisions means you won't treat the format as "magic incantations you need to memorize."

Convention: **Anthropic**'s API is called the Messages API; **OpenAI**'s is the Chat Completions API; **AWS Bedrock**'s is the Converse API (called through the boto3 SDK, not via raw HTTP JSON). All three have the **same goal** (send messages, get replies); the **formats differ**.

The most critical format differences between the three come down to two points:

**Difference 1: Where does the system prompt go?**

The system prompt is an instruction that sets the model's role and behavioral tone — think of it as "onboarding training before starting the job." The three providers handle this field differently:
- Anthropic: `system` is a **top-level independent field**, takes a string
- OpenAI: `system` is **a message inside the `messages` list**, `{"role": "system", "content": "..."}`
- Bedrock: `system` is a **top-level independent field**, but the format is a **list**: `[{"text": "..."}]`

This difference isn't accidental. Anthropic considers system and user messages to be semantically different layers that should be separated; OpenAI's design is more uniform, putting all conversational content into one list; Bedrock, needing to accommodate multiple model families (not just Anthropic), uses a more generic structure.

**Difference 2: How to write the model ID.**

This is the easiest place to trip up, especially with Bedrock:
- Anthropic: write the model version name directly, e.g. `claude-sonnet-4-6` (2024's `claude-3-5-sonnet-20241022` is deprecated; this book uses the 2026 Claude 4.X series)
- OpenAI: write the model name directly, e.g. `gpt-4o`
- Bedrock: must write the **inference profile ID**, e.g. `us.anthropic.claude-sonnet-4-6` — **not the base model ID**

Why is Bedrock different? Bedrock treats "inference profile" and "base model" as two distinct entities. The inference profile is what actually gets called at runtime; it has a geographic region prefix (`us.` / `eu.` / `ap.`) and handles load balancing and cross-region routing behind the scenes. If you pass a base model ID directly, Bedrock returns "model identifier is invalid" — note that this is not a permissions error, it's a wrong ID format. The full list of supported inference profile IDs can be found in the AWS documentation's Bedrock Supported Regions page (source: [AWS Bedrock cross-region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)).

Understanding these two differences means the code below is no longer "memorizing formats" but "applying design logic you already understand." This is exactly why this book consistently explains the reasoning before giving the code: **understanding makes code memorable; rote memorization makes code fragile**.

---

## Beat 4 — Scaffolding: Minimal API Call Skeleton

Now it is time to build Lena v0.1. Our goal is minimalism: one function, give it a prompt, it returns the model's reply. No loop, no tools, no memory. Just get the API working.

Let's verify the basic structure by building the smallest possible wrapper around the Anthropic provider:

```python
# lena_v01.py — Lena v0.1 minimal skeleton (Anthropic version)
# Dependencies: pip install anthropic
# Entire file: 18 lines, no framework dependencies

import anthropic

def chat(prompt: str) -> str:
    """Minimal LLM call: give a prompt, get back text."""
    client = anthropic.Anthropic()           # reads ANTHROPIC_API_KEY from env automatically
    response = client.messages.create(
        model="claude-sonnet-4-6",  # 2026 Claude 4.X series (2024 version deprecated)
        max_tokens=1024,                     # max reply token count, prevents infinite generation
        messages=[
            {"role": "user", "content": prompt}
        ],
    )
    return response.content[0].text          # extract text from the response object

if __name__ == "__main__":
    reply = chat("Explain what a large language model is in one sentence")
    print(reply)
```

Run it:

```bash
pip install anthropic          # ~5 seconds
export ANTHROPIC_API_KEY="sk-ant-..."
python3 lena_v01.py
```

Expected output (appears after ~2-3 seconds; content varies by model, 1-2 sentences):

```
A large language model is an AI system trained on massive amounts of text data that can understand and generate natural language.
```

That's it. This is Lena's starting point: one function, 18 lines, one call, prints a reply.

`max_tokens=1024` is worth explaining. LLM generation is open-ended — without a limit, it might produce very long content (that's a feature, not a bug). `max_tokens` tells the API "stop if output exceeds this length." For simple Q&A, 1024 is plenty; for scenarios requiring long document generation, you can increase it to 4096 or higher. This parameter controls **maximum output length per call**; it does not affect input length.

---

## Beat 5 — Progressive Assembly: Full Skeleton for Three Providers

Starting from the Anthropic version in Beat 4, add OpenAI and Bedrock support in turn, giving Lena v0.1 the ability to switch between three providers. Each expansion step has a verifiable expected output.

| Extension point | Why it's needed | How to add it |
|-----------------|-----------------|---------------|
| OpenAI support | Different `system` field format — starts making the need for provider abstraction tangible | Write a separate `chat_openai()` function; put `system` inside the messages list |
| Bedrock support | Inference profile ID + content is a list format | Use `boto3.client("bedrock-runtime")` to call `converse()` |
| Provider routing | Use a dictionary for a unified entry point, specify provider from command line | `PROVIDERS = {"anthropic": ..., "openai": ..., "bedrock": ...}` |

Complete Lena v0.1 (~62 lines):

```python
# lena_v01_full.py — Lena v0.1 complete version (three providers)
# Dependencies: pip install anthropic openai boto3
import os
import sys


def chat_anthropic(prompt: str) -> str:
    """Anthropic Messages API.
    Key format: system is a top-level field (string); content is a string.
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
    """OpenAI Chat Completions API.
    Key format: system is inside the messages list, role="system".
    """
    from openai import OpenAI
    client = OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful AI assistant named Lena."},
            {"role": "user",   "content": prompt},
        ],
    )
    return response.choices[0].message.content


def chat_bedrock(prompt: str) -> str:
    """AWS Bedrock Converse API (boto3 SDK).
    Key format: modelId must be an inference profile ID (with us./eu. prefix);
    content is a list, not a string.
    """
    import boto3
    client = boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )
    response = client.converse(
        modelId="us.anthropic.claude-sonnet-4-6",  # inference profile ID (2026 Claude 4.X series)
        messages=[{
            "role": "user",
            "content": [{"text": prompt}]    # content is a list, not a string
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
        print(f"Unknown provider: {provider}. Options: {list(PROVIDERS.keys())}")
        sys.exit(1)

    prompt = "Explain what a large language model is in one sentence"
    print(f"[Lena v0.1 | provider={provider}]")
    reply = PROVIDERS[provider](prompt)
    print(f"Reply: {reply}")


if __name__ == "__main__":
    main()
```

Expected output for all three providers (same prompt, same question; format identical, content varies by model):

```bash
python3 lena_v01_full.py anthropic
[Lena v0.1 | provider=anthropic]
Reply: A large language model is an AI system built on the Transformer architecture and pre-trained on massive text data, capable of understanding and generating natural language.

python3 lena_v01_full.py openai
[Lena v0.1 | provider=openai]
Reply: A large language model is an AI model trained on large amounts of text data that can understand and generate natural language.

python3 lena_v01_full.py bedrock
[Lena v0.1 | provider=bedrock]
Reply: A large language model is an artificial intelligence model trained on massive text data with the ability to understand and generate natural language.
```

Along the way, you just witnessed firsthand the most important format difference between the three providers: **Bedrock's `content` is a list, not a string**. This isn't a Bedrock quirk — it's a design choice made to uniformly support multi-modal input (text + images + documents). Each element in the list can be `{"text": "..."}` or `{"image": {...}}`. When you later need to give Lena image-understanding capability, this design becomes an advantage.

**Bedrock prerequisite**: Bedrock requires you to manually request model access in the AWS Console before use: go to Bedrock Console → Model access → Anthropic Claude series → Request access. Access is usually granted immediately, but your AWS account must have Bedrock activated in the corresponding region.

---

## Beat 6 — Run and Verify: The Three-Minute Day-0 Anchor

At this point, Lena v0.1 is fully runnable. Do one final verification with the minimal version:

```bash
# Environment setup (~30 seconds)
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# Run (~2-3 seconds, including network latency)
python3 lena_v01.py
```

Expected output (1 line, ~30-60 words):

```
A large language model is an AI system trained on vast amounts of text data, capable of understanding and generating natural language text.
```

**First LLM reply in under 3 minutes.** This is the book's Day-0 anchor — you are no longer a consumer, you're a builder.

**Common error diagnosis**:

| Error message | Root cause | Fix |
|--------------|------------|-----|
| `AuthenticationError: 401` | API key not set or expired | Check whether `ANTHROPIC_API_KEY` env var is set correctly |
| `model identifier is invalid` | Bedrock received a base model ID | Switch to inference profile ID with `us.` prefix |
| `ModuleNotFoundError: No module named 'anthropic'` | SDK not installed | Run `pip install anthropic` |
| `botocore.exceptions.NoCredentialsError` | AWS credentials not configured | Set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` |
| `ConnectionError` | Network issue (some regions need a proxy) | Check network connectivity or configure a proxy |

The following are Lena v0.1's known limitations — not bugs, just capabilities she doesn't have yet:

- **No memory**: Ask two questions; on the second, she doesn't remember the first
- **No tools**: Ask "what's today's date," she can only say "I don't have real-time information"
- **No loop**: Each call is independent; she won't take multi-step actions on her own
- **No error retry**: API returns 429 (too many requests) → program crashes immediately

These four limitations correspond to four directions in the rest of the book: Memory (Ch8), Tools (Ch3, Ch6), Loop (Ch3), Robustness (Ch7). Ch3 resolves the most critical one — giving Lena her first tool, `get_time()`, so she can actually tell you what time it is.

---

## Beat 7 — Design Note

---

> **Design Note: Why Not Start with a Framework?**
>
> The most obvious starting point would be a framework like LangChain, LlamaIndex, or smolagents — they claim to "spin up an agent in a few lines" and have tens of thousands of stars on GitHub. Many agent tutorials do start with frameworks, because it makes the first demo appear faster.
>
> Frameworks come with three real tradeoffs you should understand before deciding whether to start with one:
>
> - **Version instability**. LangChain refactored its core API four times in one year (source: HN discussions, repeatedly raised throughout 2024-2025); v0.1 code doesn't work in v0.2. When you only know the framework API without understanding the underlying mechanics, every upgrade is a re-learn, and you don't know why things changed.
> - **Difficult debugging**. Frameworks hide messages construction, tool call parsing, and retry logic internally. When agent behavior is wrong, you don't know which layer failed — is it your system prompt, the framework's message format conversion, the model's response format, or the tool's return value parsing? Armin Ronacher (Sentry founder) wrote explicitly in 2025: "existing SDKs aren't worth adopting yet. Model differences are significant enough that teams need custom abstractions." (quoted by Simon Willison, simonwillison.net, 2025-11-23) The thicker the abstraction layer, the worse this problem gets.
> - **Frameworks can be added later**. Write by hand first, understand every layer, then decide whether to bring in a framework — that path is open. The reverse — start with a framework, then peel back the abstraction to understand what's underneath — almost nobody actually does, because the framework insulates you from the internals.
>
> This book's choice to hand-write the loop isn't an argument that "frameworks are sinful." It's that **a framework is a choice you make after understanding, not a substitute for understanding**. Once you've written the core of an agent loop yourself in Ch3-5, you'll be able to read the source of any framework — LangChain, smolagents, LlamaIndex, all of them — and you'll know where you need a framework and where you don't.
>
> If your team is already deeply invested in LangGraph or AutoGen, this book's principles layer still applies completely. The core concepts in each chapter map one-to-one onto framework modules: this book's `AgentLoop` = LangGraph's `StateGraph`; this book's `ToolRegistry` = LangChain's `tool` decorator; this book's `Memory` = LangGraph's `MemorySaver`. Once the principles click, the framework is just a thin API.

---

## Full Book Roadmap: Lena's Version Evolution

These 30 lines of code are the starting point of this book. Below is the new capability Lena gains at each milestone across all 26 chapters — from chapter one you can see the final state and know exactly where you're heading:

```
Lena version evolution (all 26 chapters)

v0.0  Ch0   Full book overview: intelligence evolution map (no code, big-picture orientation)
v0.1  Ch1   Print one model reply, support three providers (this chapter)
v0.2  Ch2   Understand the ReAct loop; hand-trace Thought/Action/Observation state machine
v0.3  Ch3   First real tool (get_time), while loop, can answer "what time is it now"
─────────── End of Part 0: mental models established ───────────────────────────
v0.4  Ch4   LLM internals mental model (methodology chapter; output is intuition, not code)
v0.5  Ch5   Tech selection: provider / framework / memory strategy decision map
v0.6  Ch6   Tool registry: read_file / write_file / shell / web_search
v0.7  Ch7   SSE streaming output, concurrent tool execution (watch Lena "think out loud" in terminal)
v0.8  Ch8   SQLite session history + filesystem long-term memory, remembers your preferences across sessions
v0.9  Ch9   RAG: vector retrieval + external knowledge base, Lena can "go read" documents for the first time
v1.0  Ch10  Context compression, Prompt Caching, 50 rounds without blowing the token window
v1.1  Ch11  Sub-task decomposition, concurrent sub-agent dispatch, autonomous research tasks
v1.2  Ch12  Skills loading (Markdown files → triggerable instruction sets)
─────────── End of Part 1: Six Pillars established ───────────────────────────
v1.3  Ch13  Input-layer safety: Prompt Injection defense, permission boundaries
v1.4  Ch14  Execution-layer safety: sandbox, least-privilege credentials, execution auditing
v1.5  Ch15  Gateway persistent process, Telegram send/receive
v1.6  Ch16  MessageBus, hot-swappable channels
v1.7  Ch17  Heartbeat, proactive morning digest push at 8 AM every day
v1.8  Ch18  Cron scheduled tasks, crash recovery, cross-day checkpoint resume
─────────── End of Part 2: always-on personal assistant complete ─────────────
v1.9  Ch19  MCP extension protocol, connect filesystem / github / brave-search
v2.0  Ch20  Docker sandbox, safely execute arbitrary code inside a container
v2.1  Ch21  Evals pipeline, CI auto-scores every PR
v2.2  Ch22  Observability, launchd/systemd production deployment
v2.3  Ch23  Specialization: derive a specialized agent from Lena with one command
v2.4  Ch24  Browser Agent: autonomously browse the web to complete tasks
v2.5  Ch25  From general to specialized — full landscape of derivation patterns and engineering practices
─────────── End of book: generalist agent runtime complete ────────────────────
```

The **Six Pillars** are the architectural backbone running through this evolution map — each chapter advances in one of these directions, and each pillar is an indispensable component of a "general-purpose agent":

```
① Tool Universality   Any capability can be defined as a tool (Ch6-7)
   → Turn "knows Python" into a tool, turn "can search the web" into a tool;
     tools are the agent's only channel of interaction with the external world.

② Memory              Short-term memory + long-term memory + retrieval (Ch8-9)
   → An agent without memory is amnesiac;
     memory lets the agent accumulate knowledge across sessions and run complex multi-day tasks.

③ Planning            Autonomously decompose large goals into sub-steps (Ch11)
   → You tell the agent "research X and write a report";
     the agent decides what to look up first, what next, and how to synthesize.

④ Long-horizon        Maintain state across hours and days (Ch17-18)
   → Persistent process + heartbeat + cron make the agent a 24/7 worker,
     not a tool that needs to be manually started every time.

⑤ Safety              Not hijackable by prompt injection; behavior is auditable (Ch13-14)
   → General = powerful = dangerous;
     a general-purpose agent without safety constraints cannot be deployed.

⑥ Specialization      Derive specialized agents from the general runtime (Ch23-25)
   → Same Lena core, swap the system prompt + tool set,
     and it becomes a quant trading agent / news broadcast agent / code review agent.
```

These six pillars aren't independent feature points — they're **an interdependent system**. Tool Universality is the foundation; without tools an agent can do nothing. Memory is the amplifier; without memory an agent can remember nothing. Planning is the force multiplier, turning 1 goal into N ordered sub-steps. Long-horizon is the continuity guarantee, making the agent more than a one-shot utility. Safety is the trust foundation; an agent without safety can't run in production. Specialization is the final payoff, letting your general-purpose runtime snap into any scenario quickly.

This chapter is the starting point for all six pillars — and the only starting point: **first get one reply to print, then there's something to stack everything else on top of**.

---

## Three-Provider API Quick Reference

This table will be referenced repeatedly in later chapters. Here's the complete version:

| Dimension | Anthropic | OpenAI | AWS Bedrock |
|-----------|-----------|--------|-------------|
| API name | Messages API | Chat Completions | Converse API |
| Python SDK | `anthropic` | `openai` | `boto3` |
| Authentication | `ANTHROPIC_API_KEY` env var | `OPENAI_API_KEY` env var | AWS SigV4 (`AWS_ACCESS_KEY_ID`, etc.) |
| system location | Top-level field, string | Inside messages, `role="system"` | Top-level field, list `[{"text":"..."}]` |
| user content format | String | String | List `[{"text":"..."}]` |
| Model ID format | `claude-sonnet-4-6` | `gpt-4o` | `us.anthropic.claude-sonnet-4-6` (inference profile) |
| Reply path | `response.content[0].text` | `response.choices[0].message.content` | `response["output"]["message"]["content"][0]["text"]` |
| Stop signal field | `stop_reason` | `finish_reason` | `stopReason` |
| Token usage field | `usage.input_tokens` | `usage.prompt_tokens` | `usage.inputTokens` |
| Streaming support | SSE, `event: content_block_delta` | SSE, `data: {...}` | SDK streaming iterator |

In Ch6 we'll turn this table into a `BaseProvider` abstraction — by then you'll understand why that abstraction must exist and which layer should handle format conversion.

---

## Chapter Challenges (Optional)

1. **Format exploration**: Modify the Anthropic call in `lena_v01_full.py` to include a `system` parameter (`system="You are an assistant specializing in programming questions"`), and compare the model's tone with and without a system prompt.
2. **Error diagnosis**: Intentionally change Bedrock's `modelId` to the base model ID (remove the `us.` prefix), observe the error message, then change it back. This error message will help you quickly locate the issue in real-world work.
3. **Preview question**: Think about it: if you wanted Lena to "remember the first reply when answering the second question," what would you need to add, and where? Hint: `messages` is a list — append one entry each round. (Ch3 gives the full answer.)

---

*Next chapter: The secret of the ReAct loop — upgrading single-turn Q&A into looped decision-making. Lena v0.2 is waiting for you.*

---

## Navigation

➡️ **[Ch 2. The Secret of the ReAct Loop](../ch02-react-loop/README.md)** — How reasoning and acting interweave into the ReAct loop from scratch

[📘 Back to full table of contents](../../README.md)
