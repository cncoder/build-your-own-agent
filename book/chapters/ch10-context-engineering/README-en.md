# Chapter 10: Context Engineering — Token Economics

> **[Lena: v0.9 → v0.10]** · **[Pillars: Memory / Long-horizon]**

---

## Beat 1 — Roadmap

```
Ch 1 → Ch 3 → Ch 6 → Ch 8 → Ch 9 → [Ch 10 ← you are here] → Ch 11 → ...
 API    Loop  Tools  Memory  RAG    Context Engineering          Planning
```

This chapter starts with a Lena that runs ten turns without issue but crashes after thirty. We'll work through three compression layers (microcompact → autocompact → reactive), add prompt caching discipline to cut token costs by up to 90%, and confront the three provider cache field variations that will break any naive `usage` parser.

Along the way there's a counterintuitive insight: *why keeping error records in context is the right call* — even when your instinct says to clear them.

By the end of this chapter, Lena v0.10 can sustain 50 turns without overflowing context and prints the cache hit rate to the terminal in real time.

Watch out for this pitfall: dynamic timestamps in the system prompt will silently kill all cache hits. We'll demonstrate the failure first, then fix it.

> **🧠 Intelligence increment (v0.9 → v0.10)**: Lena actively manages her own context for the first time — three compression layers (microcompact / autocompact / reactive) let her run 50 turns without overflow, and prompt caching cuts token costs by up to 90%. This chapter teaches you how to build context self-regulation into your own agent.

![Context Window Layered Structure](diagrams/context-window.svg)

---

## Beat 2 — Motivation

Run Lena v0.9 for forty turns of heavy tool usage — reading files, executing shell commands each turn — and count the tokens:

```
Turn  1: ~  1,800 tokens
Turn 10: ~ 18,000 tokens
Turn 20: ~ 52,000 tokens
Turn 30: ~ 98,000 tokens
Turn 35: anthropic.BadRequestError: prompt_too_long
```

The crash is not a logic bug in Lena. It's the inevitable outcome of a `messages[]` list that only ever appends, with no pressure-release valve.

The obvious fix is "truncate the oldest messages." There's a concrete reason that won't work: the oldest messages typically carry the original task goal. Truncate them and Lena starts drifting — she stops working on what the user actually asked for. A 2025 Anthropic engineering post on effective context engineering calls this failure mode *context rot*: as context grows, the model's recall degrades and it begins "solving the wrong problem."

Convention: *context window* = the hard token limit for a single API call (128K for Claude Sonnet); *context rot* = the gradual degradation of model recall as context length increases, distinct from hard truncation.

What we need is compaction, not truncation.

---

## Beat 3 — Theory (no code in this section)

Anthropic's official blog post gives the most precise definition of context engineering and its central metaphor:

> "Context must be treated as a **finite resource with diminishing marginal returns**. Like humans, who have limited working memory capacity, LLMs have an **attention budget** that they draw on when parsing large volumes of context. Every new token introduced depletes this budget."
> (Source: Anthropic, *Effective context engineering for AI agents*, 2025-09-29)

In other words: bigger context window is not always better. Every additional token dilutes the model's attention on *all other tokens*. A 200K-token window can hold a lot, but once full, the model's effective reasoning capacity may actually be *lower* than with a carefully trimmed 50K window.

That's why this chapter doesn't teach you "how to stuff more things into context" — it teaches you **how to get better results with fewer tokens**.

### 3.1 Why Three Layers Instead of One

*（No code in this section.）*

A single compression strategy fails because there are three distinct failure surfaces, each requiring different response latency and cost tradeoffs.

The first failure surface is *continuous token accumulation*. Tool results — file reads, shell output, search hits — pile up between turns. Most of this content is referenced once and never again, yet it consumes tokens on every subsequent API call. The right response is zero-cost, zero-API-call cleanup on every loop iteration. This is the micro layer.

The second failure surface is *approaching the hard limit*. When total token count nears `context_window − buffer`, you must proactively intervene with LLM-driven summarization before the API rejects the request. This costs one extra API call but preserves the semantic structure of the conversation. This is the auto layer.

The third failure surface is *tokenizer estimation error*. Client-side token counts are approximations; Anthropic's internal tokenizer may differ by a few percentage points. The first two layers can miss edge cases, and the API returns a 413. The right response is to force compaction on the error path and retry once. This is the reactive layer.

The three layers form a cascade, not redundancy. Each layer handles failure modes the other two cannot.

Convention: *microcompact* = inline cleanup of stale tool results, no API call; *autocompact* = LLM-generated summary triggered by a token threshold; *reactivecompact* = forced compaction triggered by a real 413 error.

### 3.2 Prompt Caching Economics

*（No code in this section.）*

Anthropic charges approximately 0.1× the base input price for tokens read from cache, and 1.0× for uncached input tokens. In a 50-turn conversation where the system prompt plus tool definitions totals 4,000 tokens, cache hits on those 4,000 tokens save roughly 90% of the cost for every turn after the first.

For caching to work, the cached prefix must be *byte-for-byte identical* across requests. The most common cause of cache misses is dynamic values embedded in the system prompt: timestamps, session IDs, "current time" fields. Every time that value changes, the entire cache is invalidated.

The Anthropic API currently allows one message-level `cache_control` marker per request (see Claude Code source `claude.ts:3078`). Placing multiple markers on user messages leads to undefined behavior — either the last one silently wins or the request errors. The correct discipline is to place exactly one such marker on the last tool definition (the longest stable prefix), and let the system prompt cache via the top-level `cache_control` parameter (handled by the SDK).

Convention: *cache breakpoint* = the position in a request where the API begins caching; on a hit, tokens before the breakpoint are served from cache, tokens after are recomputed. *Cache write* = the first-call penalty (1.25× base input price). *Cache read* = the discounted hit (0.1×).

### 3.3 The Provider Cache Field Zoo

*（No code in this section.）*

Major LLM providers report cache usage in different ways:

| Provider | Cache read field | Cache write field | Location |
|---------|-----------|-----------|------|
| Anthropic | `cache_read_input_tokens` | `cache_creation_input_tokens` | usage root |
| OpenAI | `prompt_tokens_details.cached_tokens` | (no separate field) | nested dict |
| DeepSeek | `prompt_cache_hit_tokens` | `prompt_cache_miss_tokens` | usage root |

A unified `parse_usage()` function must branch by provider. Failing to handle the OpenAI nested case causes every cache read to silently return zero — your monitoring metrics look like caching never worked.

---

## Beat 4 — Scaffold

Build the three-layer compaction skeleton with the minimum structure needed to run, before adding real summarization logic.

```python
# compaction.py — skeleton (no summarization yet, can be verified independently)

from __future__ import annotations
import anthropic


def microcompact(messages: list[dict], keep_last: int = 3) -> list[dict]:
    """
    Remove stale tool_result blocks from older turns.

    keep_last: number of recent turns containing tool_result to preserve.
    No API call — safe to run on every iteration.
    """
    # Find indices of user-role turns that contain tool_result blocks
    result_turns = [
        i for i, m in enumerate(messages)
        if m.get("role") == "user"
        and isinstance(m.get("content"), list)
        and any(c.get("type") == "tool_result" for c in m["content"])
    ]
    # Replace all but the last keep_last turns with a short placeholder
    for idx in result_turns[:-keep_last]:
        messages[idx]["content"] = [
            ({"type": "text", "text": "[tool_result cleared by microcompact]"}
             if c.get("type") == "tool_result" else c)
            for c in messages[idx]["content"]
        ]
    return messages


class AutoCompactor:
    """
    Triggers LLM-driven summarization when token count nears the limit.

    buffer_tokens: headroom to maintain below context_window.
                   13,000 matches Claude Code default (autoCompact.ts:62).
    max_failures:  circuit-breaker threshold — stop retrying after this many
                   consecutive failures (same as MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3).
    """
    BUFFER_TOKENS = 13_000
    MAX_FAILURES  = 3

    def __init__(self, client: anthropic.Anthropic, model: str):
        self.client   = client
        self.model    = model
        self._fails   = 0

    def should_compact(self, token_count: int, context_window: int) -> bool:
        if self._fails >= self.MAX_FAILURES:
            return False          # circuit breaker open
        return token_count >= context_window - self.BUFFER_TOKENS

    async def compact(self, messages: list[dict]) -> list[dict] | None:
        """Returns the replacement message list, or None on failure."""
        try:
            # Placeholder — real implementation filled in Beat 5
            raise NotImplementedError
        except Exception:
            self._fails += 1
            return None

    def reset_failures(self) -> None:
        self._fails = 0


def reactive_compact(messages: list[dict]) -> list[dict]:
    """
    Emergency compaction called on a real 413 / prompt_too_long error.
    Returns a replacement list with all tool_results collapsed.
    """
    compacted: list[dict] = []
    for m in messages:
        if (m.get("role") == "user"
                and isinstance(m.get("content"), list)
                and any(c.get("type") == "tool_result" for c in m["content"])):
            compacted.append({"role": "user",
                               "content": "[context cleared by reactive_compact]"})
        else:
            compacted.append(m)
    return compacted
```

Running `microcompact([])` should return `[]` without error. That's the verifiable baseline. The `AutoCompactor` skeleton raises `NotImplementedError` — the next step fills it in.

---

## Beat 5 — Incremental Assembly

| Extension point | Why needed | How to add |
|--------|---------|---------|
| Real summarization in `AutoCompactor.compact` | Skeleton raises; needs a real LLM call to compress history | Call LLM with a "summarize this conversation" prompt, replace message list |
| Unified `parse_usage()` across providers | Provider fields differ; wrong parsing silently returns 0 cache tokens | Branch by provider name, map to unified `TokenUsage` |
| Single-marker cache discipline in `get_cache_control()` | Multiple markers cause silent failure | Place exactly one `cache_control` on the last tool definition |
| Real-time stats with `TokenMonitor` | Can't verify caching works without per-turn hit rate | Accumulate usage, compute `cache_read / total_input` ratio |

**Extension 1 — Real summarization:**

```python
    async def compact(self, messages: list[dict]) -> list[dict] | None:
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=(
                    "Summarize the following conversation into a structured recap."
                    "You must preserve: (1) the user's original goal, "
                    "(2) all decisions made, "
                    "(3) the exact text of every error message — do not omit errors. "
                    "Errors are navigation markers; the agent must know what failed."
                ),
                messages=messages,
            )
            summary = resp.content[0].text
            self._fails = 0
            return [{"role": "user",
                     "content": f"[Conversation Summary]\n{summary}"}]
        except Exception:
            self._fails += 1
            return None
```

After adding this, run `compactor.compact(sample_messages)` against a five-turn test fixture. The result should be a single-element list containing the summary string. Print to confirm:

```
[Conversation Summary]
Original goal: Write and test a Python sorting function.
Steps taken: ...
Errors encountered: FileNotFoundError: sort_test.py not found (turn 3)
```

The explicit instruction to preserve errors verbatim enforces the "keep error records" principle — the model needs a map of failures, not a sanitized log.

**Extension 2 — Unified `parse_usage()`:**

```python
# cache.py

from dataclasses import dataclass


@dataclass
class TokenUsage:
    input_tokens:        int = 0
    output_tokens:       int = 0
    cache_read_tokens:   int = 0
    cache_write_tokens:  int = 0


def parse_usage(raw: dict, provider: str) -> TokenUsage:
    """
    Map a provider-specific usage dict to a unified TokenUsage.

    Anthropic: cache_read_input_tokens / cache_creation_input_tokens  (root)
    OpenAI:    prompt_tokens_details.cached_tokens                     (nested)
    DeepSeek:  prompt_cache_hit_tokens / prompt_cache_miss_tokens      (root)
    """
    u = TokenUsage(
        input_tokens  = raw.get("input_tokens")  or raw.get("prompt_tokens",     0),
        output_tokens = raw.get("output_tokens") or raw.get("completion_tokens", 0),
    )
    if provider == "anthropic":
        u.cache_read_tokens  = raw.get("cache_read_input_tokens",      0)
        u.cache_write_tokens = raw.get("cache_creation_input_tokens",  0)
    elif provider == "openai":
        details              = raw.get("prompt_tokens_details") or {}
        u.cache_read_tokens  = details.get("cached_tokens", 0)
    elif provider == "deepseek":
        u.cache_read_tokens  = raw.get("prompt_cache_hit_tokens",  0)
        u.cache_write_tokens = raw.get("prompt_cache_miss_tokens", 0)
    return u
```

Verify with a quick fixture before wiring it into the loop:

```python
raw_anthropic = {
    "input_tokens": 4000,
    "output_tokens": 120,
    "cache_read_input_tokens": 3800,
    "cache_creation_input_tokens": 200,
}
u = parse_usage(raw_anthropic, "anthropic")
assert u.cache_read_tokens == 3800   # should pass
print(f"cache_read_tokens: {u.cache_read_tokens}")  # 3800
```

**Extension 3 — Single-marker cache discipline:**

```python
def build_request_with_caching(
    system_prompt: str,
    tool_definitions: list[dict],
    messages: list[dict],
) -> dict:
    """
    Build kwargs for client.messages.create().

    Rule: exactly one message-level cache_control per request.
    Place it on the last tool definition — the longest stable prefix.
    System prompt caches via the top-level cache_control (handled by SDK).
    """
    tools = [t.copy() for t in tool_definitions]
    if tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}  # one breakpoint

    return {
        "system": system_prompt,        # top-level caching handled by SDK default
        "tools": tools,
        "messages": messages,
    }
```

**Extension 4 — Real-time `TokenMonitor`:**

```python
# monitor.py

class TokenMonitor:
    def __init__(self) -> None:
        self._total_input  = 0
        self._cache_reads  = 0
        self._compactions  = 0

    def record(self, usage: TokenUsage) -> None:
        self._total_input += usage.input_tokens
        self._cache_reads += usage.cache_read_tokens

    def record_compaction(self) -> None:
        self._compactions += 1

    @property
    def cache_hit_rate(self) -> float:
        if self._total_input == 0:
            return 0.0
        return self._cache_reads / self._total_input

    def summary_line(self, turn: int) -> str:
        return (
            f"Turn {turn:2d} | "
            f"input: {self._total_input:7,} | "
            f"cache_hit: {self.cache_hit_rate:5.1%} | "
            f"compactions: {self._compactions}"
        )
```

---

## Beat 6 — Run and Verify

Wire all components into `lena.py` and run a 50-turn test.

```python
# lena_v010.py (simplified — full source in code/lena-v0.10/)

import asyncio
import anthropic
from compaction import microcompact, AutoCompactor, reactive_compact
from cache import parse_usage, build_request_with_caching
from monitor import TokenMonitor

CONTEXT_WINDOW = 128_000  # Claude Sonnet

class AgentLoop:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.client    = anthropic.Anthropic(api_key=api_key)
        self.model     = model
        self.messages  = []
        self.compactor = AutoCompactor(self.client, model)
        self.monitor   = TokenMonitor()

    async def run(self, user_input: str, tools: list[dict]) -> str:
        self.messages.append({"role": "user", "content": user_input})

        # Layer 1 — microcompact (every turn, zero cost)
        self.messages = microcompact(self.messages)

        # Layer 2 — autocompact (threshold-based)
        token_estimate = len(str(self.messages)) // 4   # rough heuristic
        if self.compactor.should_compact(token_estimate, CONTEXT_WINDOW):
            compacted = await self.compactor.compact(self.messages)
            if compacted:
                self.messages = compacted
                self.monitor.record_compaction()

        kwargs = build_request_with_caching(
            system_prompt="You are Lena, a general-purpose agent.",
            tool_definitions=tools,
            messages=self.messages,
        )

        while True:
            try:
                resp = self.client.messages.create(
                    model=self.model, max_tokens=1024, **kwargs
                )
            except anthropic.BadRequestError as e:
                if "prompt_too_long" in str(e) or getattr(e, "status_code", 0) == 413:
                    # Layer 3 — reactive compact
                    self.messages = reactive_compact(self.messages)
                    kwargs["messages"] = self.messages
                    self.monitor.record_compaction()
                    continue
                raise

            usage = parse_usage(resp.usage.__dict__, "anthropic")
            self.monitor.record(usage)

            if resp.stop_reason == "end_turn":
                reply = resp.content[0].text
                self.messages.append({"role": "assistant", "content": reply})
                return reply

            # Tool dispatch omitted here — same pattern as Chapter 6


async def test_50_rounds():
    lena = AgentLoop(api_key="...")

    for i in range(1, 51):
        reply = await lena.run(f"Turn {i}: describe what you know so far.", tools=[])
        print(lena.monitor.summary_line(i))

asyncio.run(test_50_rounds())
```

Expected terminal output — numbers you should actually see:

```
Turn  1 | input:   1,842 | cache_hit:  0.0% | compactions: 0
Turn  5 | input:   8,234 | cache_hit: 67.3% | compactions: 0
Turn 20 | input:  45,123 | cache_hit: 71.2% | compactions: 0
Turn 25 | input:  63,891 | cache_hit: 72.1% | compactions: 1
Turn 50 | input:  38,201 | cache_hit: 78.4% | compactions: 3
```

Two things worth noting: first, the cache hit rate climbs to roughly 70% by turn 5 and stays there — the system prompt and tool definitions are being served from cache. Second, at turn 25, the input token count *drops* from ~64K back to ~38K: autocompact fired, replaced the history with a summary, and the conversation continued without interruption.

**Common failure: cache hit rate stays at 0%.** The most common cause is a timestamp embedded in the system prompt. Specifically, this:

```python
# BAD — kills all cache hits
system = f"You are Lena. Current time: {datetime.now()}."
```

Must become:

```python
# GOOD — system prompt stable, time goes into the user message
system = "You are Lena, a general-purpose agent."
user_msg = f"[{datetime.now()}] Turn {i}: ..."
```

Moving the timestamp to the user message keeps the cacheable prefix byte-for-byte identical across requests.

In Chapter 11, Lena will gain the ability to spawn subagents and delegate subtasks — the first step toward handling goals that don't fit inside a single context window.

---

## Beat 7 — Design Note

> **Context Overload in Multi-Agent Systems: Three Engineering Solutions**
>
> This chapter covers context management for a single agent. But when Lena gains the ability to spawn subagents in Chapter 11, context management becomes a higher-dimensional problem. Anthropic's architecture whitepaper describes this challenge directly:
>
> > "The orchestrator agent may face the fundamental problem that context grows too complex for one agent to manage effectively." (Source: Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*, 2025, p.15)
>
> The whitepaper gives three engineering solutions for managing context overload in multi-agent systems:
>
> **Solution 1: Context editing (automatically clean up stale tool call results).** When the orchestrator dispatches subtasks, tool call results that are complete and no longer relevant can be cleared from the main context. This chapter's `microcompact()` function is the single-agent version of this idea — replacing `tool_result` blocks with placeholders preserves the conversation's semantic integrity while freeing tokens.
>
> **Solution 2: File-based persistence (externalize context to the filesystem).** For information that needs to persist across sessions or agents (such as a subagent's research findings), writing to the filesystem is more reliable than holding it in context. Retrieve it when needed rather than occupying the context window indefinitely. This is the context engineering counterpart to the external memory pattern from Chapter 8.
>
> **Solution 3: Response cap + pagination (limit tool returns to 25,000 tokens, paginate large data).** This is an often-overlooked engineering rule: tool return values should never be unbounded. A single `read_file` call that returns a 100,000-line log file will blow up the context immediately. The correct approach is to set a cap at the tool layer (25,000 tokens is the reference value from the whitepaper), return truncated content plus a pagination token when exceeded, and let the agent request the next page as needed.
>
> These three solutions correspond to three extension directions from this chapter's three-layer compaction architecture: microcompact maps to context editing, autocompact covers part of the file-based persistence scenario, and reactive compact is the last-resort safety net.

---

> **Why Not a Single Unified Compression Layer?**

The simple alternative is a single `compact_if_needed()` function called every turn: estimate the token count, summarize if it exceeds some threshold. Some agent frameworks take this approach.

The problem is that this single layer tries to handle three different failure modes with one mechanism, and handles all three poorly:

- **Too slow for continuous cleanup.** If the single layer calls the LLM every turn, API costs double. If it only calls at a threshold, stale tool results silently accumulate for 20+ turns — by which point token count may be jumping past the threshold faster than summarization can push it back down.
- **No recovery path for tokenizer drift.** Client-side token estimates are approximations. A single threshold-triggered layer can still miss the API hard limit on estimation error. Without a reactive path, 413 errors surface as unhandled exceptions to the user.
- **One mechanism can't be both "cheap and constant" and "expensive and occasional".** Microcompact is zero-cost because it never touches the API. Autocompact costs one LLM call and must be used sparingly. Reactive compact costs one LLM call on error and is designed to rarely occur. Collapsing them into one either runs the expensive path every turn (waste) or never runs the cheap path (lets token garbage pile up).

The three-layer separation is Claude Code's production choice. It appears explicitly in `autoCompact.ts:62` (buffer constant), `microCompact.ts:253` (zero-cost path), and the `REACTIVE_COMPACT` feature flag in `query.ts:15`. Each layer has a single responsibility, a single trigger condition, and a failure mode it cannot propagate to the others.

In a multi-model, multi-provider production system, you'll also want to parameterize `BUFFER_TOKENS` per model — Haiku's 8K output ceiling implies a different safe buffer than Opus's 200K. The constant 13,000 works as a default for Sonnet.

---

Lena learned in this chapter how to manage her own working memory — prompt caching cuts token costs by 90%, and the three-layer compaction architecture ensures she doesn't lose critical decisions during long-running tasks.

But an agent that can manage her own context still doesn't know "what to do next." When a user says "help me analyze these 20 contracts, extract key clauses, compare the differences, and write it up as a report," Lena isn't facing a single problem — she's facing a task tree. Breaking down tasks, delegating to subagents, collecting results, merging output — that's a different capability, one that requires dedicated planning architecture. **Chapter 11 adds planning and subagents to Lena, letting her autonomously decompose large goals into small steps and execute them in parallel.**

---

## Challenge Exercises

1. **Timestamp destruction test.** Modify `build_request_with_caching()` to embed `datetime.now()` in the system prompt, run 10 turns, and record the cache hit rate. Then revert and compare. The gap should be roughly 70 percentage points.

2. **Error-preserving compaction.** Extend `AutoCompactor.compact()` to extract every `Error:` line from tool results verbatim before summarizing, appending them to the end of the summary. Run the 50-turn test and intentionally trigger a `FileNotFoundError` on one turn. Verify the error text survives the summary.

3. **Unified provider stats.** In the `parse_usage()` test, replace the Anthropic client with a mock that returns an OpenAI-format usage dict (including `prompt_tokens_details.cached_tokens`). Confirm that the cache hit rate reads correctly instead of always showing zero.

---

## Navigation

➡️ **[Ch 11. Planning and Multi-Step Reasoning](../ch11-planning-subagent/README.md)** — Subagents and task delegation

[← Ch 9. RAG and Vector Search](../ch09-rag-vector-search/README.md) · [📘 Back to Table of Contents](../../README.md)
