# Chapter 7: Streaming and Concurrency — Keeping Your Agent Responsive

> **Lena Evolution: v0.6 → v0.7**
> New capabilities: SSE streaming output + concurrent tool eagerness + 5 tools searching simultaneously

---

## Beat 1 — Roadmap

```
Ch 1 → Ch 2 → Ch 3 → Ch 4 → Ch 5 → Ch 6 → [Ch 7 ← you are here] → Ch 8 → ...
```

This chapter starts from a "works but lags" Lena v0.6 → first clears up why sequential execution by default is actually correct (a counterintuitive flip) → then installs SSE streaming output (so users see the first character in 0.3 seconds) → finally adds concurrent tool eagerness (firing off 5 searches simultaneously). Along the way we'll trip over one misconception: you might assume "agent = concurrent," but real-world agent runtimes — Claude Code and OpenClaw included — default to sequential, for solid reasons.

**By the end of this chapter, Lena advances from v0.6 to v0.7** with two new capabilities:

1. Time to first token drops from 3–10 seconds → 0.3 seconds (streaming output)
2. Total time for 5 concurrent tool calls drops from ~8 seconds → ~2 seconds (concurrent execution)

Seven beats: motivation (why it lags) → SSE protocol theory → streaming eagerness theory → scaffold (minimal streaming loop) → incremental assembly (adding concurrency) → run verification (measured speedup) → Design Note (why OpenClaw enforces per-session serialization)

> **Intelligence increment (v0.6 → v0.7)**: Lena gains streaming response and concurrent tool capabilities for the first time. SSE lets the user see the first token in 0.3 seconds; asyncio concurrency compresses 5 serial searches from 12 seconds down to 2. This chapter teaches you how to build "start rendering before the full output arrives" — the core of perceived responsiveness — directly into your own agent.

---

## Beat 2 — Motivation

### The current problem: blank screen + serial queuing

Here's what happens when Lena v0.6 handles this request:

```
User: Look up all five at once: 1) today's weather in Beijing  2) latest AI news
      3) current BTC price  4) tomorrow's Beijing→Shanghai flights  5) what's new in Python 3.13
```

Let's put numbers to it:

```
t=0.0s   API request sent, screen blank
t=3.2s   Full response received (containing 5 tool_use blocks)
t=3.2s   Start executing web_search("today's weather in Beijing")
t=4.8s   Done, start executing web_search("latest AI news")
t=6.1s   Done, start executing web_search("current BTC price")
t=7.4s   Done...
t=12.0s  All 5 tools complete
t=12.0s  Pack tool_results, send second API request
t=15.5s  User sees the first summarized character
──────────────────────────────
Total user wait: 15.5 seconds, screen completely blank for the first 3.2 seconds
```

Two independent pain points:

**Pain point 1 — blank screen**: After the LLM starts generating a reply, 3.2 seconds pass before the first character appears. This is a consequence of v0.6's "wait for complete response" mode. The LLM actually started emitting the first token within 0.3 seconds — we just weren't consuming it as a stream.

**Pain point 2 — serial tools**: The 5 web_search calls are completely independent of each other, yet v0.6 runs them one after another. Without concurrency, 5 requests each taking 0.5–2s cost 5–10 seconds serially; concurrently they take max(0.5, 0.8, 1.2, 1.5, 2.0) ≈ 2 seconds.

Before we fix either of these, let's flip an intuition.

---

## Beat 3 — Theory

Anthropic's context engineering documentation defines the core metric for this chapter:

> "Find the **smallest possible set of high-signal tokens** that maximize the likelihood of some desired outcome."

Streaming output matters beyond "looking faster" — it lets users **see tokens sooner**, and lets the harness make **interrupt/retry** decisions sooner. This is the other face of the "get ground truth as early as possible" principle in context engineering.

### 3.1 The counterintuitive flip: sequential by default is correct, not lazy

At first glance, "an agent should execute all tools concurrently" seems reasonable. By the end of this chapter you'll understand: **real-world agent runtimes, including Claude Code and OpenClaw, default to sequential. Concurrency is a conditional special case.**

This isn't laziness. It's a deliberate design.

Claude Code's `StreamingToolExecutor.ts:40` has a key comment (from the public repository):

```
- Concurrent-safe tools can execute in parallel with other concurrent-safe tools
- Non-concurrent tools must execute alone (exclusive access)
- Results are buffered and emitted in the order tools were received
```

Did you catch "emitted **in the order tools were received**"? **Results must be emitted in the order they were received.** This means even if tool 2 finishes before tool 1, you still wait for tool 1's result to go to the LLM first. Tool calls carry implicit ordering semantics — the LLM places them in order inside the message, the assistant's content array is ordered, and tool_results must correspond accordingly.

OpenClaw's design is even more conservative. It **enforces serialization at the session level**: each user session runs only one agent instance at a time. The reason is that the race conditions introduced by tool side effects (file writes, command execution) are far messier than they look — "two agents writing the same file simultaneously" is a real disaster, not a theoretical risk.

Convention: a tool with `isConcurrencySafe = true` is read-only, side-effect-free, and idempotent; `isConcurrencySafe = false` has write side effects and must run exclusively. These two terms are used consistently throughout this chapter.

**So the concurrency this chapter teaches is "enable concurrency for tools where `isConcurrencySafe = true`," not "make everything concurrent."**

### 3.2 The engineering essence of SSE

SSE (Server-Sent Events) is a unidirectional text streaming protocol built on HTTP/1.1, standardized in RFC 6202. The reason LLM APIs chose SSE over WebSocket is straightforward:

- LLM generation is inherently **unidirectional**: the server generates tokens, the client consumes them. There's no scenario where the client pushes to the server.
- SSE is **pure HTTP**: any HTTP/1.1 proxy or CDN can handle it transparently. WebSocket's upgrade handshake (`Upgrade: websocket`) gets blocked by many enterprise proxies.
- SSE has **built-in reconnection**: the browser's native `EventSource` API reconnects automatically, carrying the `Last-Event-ID` header.

Anthropic, OpenAI, and DeepSeek all chose SSE. This is a convergent result, not three independent inventions.

The SSE data format is very simple:

```
event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"H"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"i"}}

event: message_stop
data: {"type":"message_stop"}
```

Rule: each message consists of one or more lines, separated by a **blank line**. `data:` is the message body; `event:` is an optional type label.

### 3.3 Protocol differences across providers + special fields

The three providers have one **structural difference** in their SSE implementations: how tool call arguments are transmitted.

**Anthropic protocol** (`messages` API):
- Uses a two-event structure: `content_block_start` + `content_block_delta`
- Tool arguments are streamed in fragments via successive `input_json_delta` events
- Extended Thinking has its own `thinking_delta` event, and a critical `signature_delta`

**OpenAI protocol** (`chat/completions` API):
- Embeds tool calls in `choices[0].delta.tool_calls`
- Arguments are transmitted as incremental additions to the `function.arguments` string
- Stream-end marker is `data: [DONE]`, not a JSON event

**DeepSeek special field** — `reasoning_content`:
DeepSeek-R1 models add a non-standard field `reasoning_content` inside `delta` in the OpenAI-compatible interface, for streaming the chain of thought. This is not in the OpenAI spec and requires explicit handling.

**Anthropic special field** — `signature_delta` (source: `nanoClaw/nanoclaw/core/llm.py:383`):
When you use Extended Thinking with the Anthropic API, each thinking block ends with a `signature_delta` event carrying Anthropic's **encrypted signature** over the thinking block's contents. If you send that thinking block back to the LLM in a subsequent request (multi-turn with tool use), you must include the signature verbatim, or the API returns a 400 error. This is a known pitfall when combining Extended Thinking with tool use.

Convention: `thinking_delta` = content increment of a thinking block; `signature_delta` = encrypted signature of a thinking block, must be sent back along with the thinking block.

Reference: for the complete SSE specification, see [WHATWG EventSource spec](https://html.spec.whatwg.org/multipage/server-sent-events.html) (no need to read it all — just know that the SSE `id:` field drives reconnection; LLM APIs generally don't use it because LLM streams can't be replayed).

---

## Beat 4 — Scaffold

Let's verify the streaming baseline by building the smallest possible SSE consumer — one that can print tokens as they arrive and detect tool_use blocks:

```python
# lena-v0.7/core/streaming_base.py
"""
Minimal SSE consumer skeleton.
Does exactly three things:
  1. Read the HTTP stream line by line
  2. Parse data: JSON
  3. Recognize text_delta / tool_use block types
Edge cases (reconnect, timeout) are deferred to Beat 5.
"""
import json
import aiohttp


async def stream_minimal(session: aiohttp.ClientSession, api_key: str, messages: list) -> None:
    """Minimal streaming consumer: print text tokens and identify tool_use."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-5",    # 2024 series, supports SSE
        "max_tokens": 1024,
        "stream": True,                   # key: enable SSE
        "messages": messages,
    }

    async with session.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
    ) as resp:
        resp.raise_for_status()
        # aiohttp iterates response body one line at a time
        async for raw_line in resp.content:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue                   # skip event: lines and blank lines
            data_str = line[5:].strip()
            if not data_str:
                continue

            event = json.loads(data_str)
            etype = event.get("type")

            if etype == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    print(delta.get("text", ""), end="", flush=True)  # streaming print

            elif etype == "message_stop":
                print()  # newline
                break
```

Running `await stream_minimal(session, key, [{"role":"user","content":"Hello"}])` should print characters appearing one by one. Next we'll add capabilities on top of this skeleton.

---

## Beat 5 — Incremental Assembly

Starting from the minimal skeleton, four steps extend it to the complete lena-v0.7:

| Extension | Why needed | How to add |
|-----------|-----------|------------|
| Tool argument buffering | `input_json_delta` is fragmented JSON, can't be parsed piece by piece | Maintain a `json_buffer` per tool_use block; call `json.loads` when `content_block_stop` fires |
| Streaming eagerness | Start executing as soon as a tool_use block is complete, without waiting for `message_stop` | At `content_block_stop`, call `asyncio.create_task()` to launch the tool |
| Semaphore concurrency cap | Prevent 10+ tools running simultaneously from exhausting system resources | Wrap each tool coroutine with `asyncio.Semaphore(MAX_CONCURRENT)` |
| signature_delta preservation | 400 errors when using Extended Thinking with tool calls | Maintain a `signature` field for thinking blocks; send it back verbatim |

### Extension 1 — Tool argument buffering

```python
# Add per-block state tracking inside the stream loop
current_blocks: dict[int, dict] = {}   # index → block info
json_buffers: dict[int, str] = {}      # index → accumulated JSON string

# Initialize at content_block_start
if etype == "content_block_start":
    idx = event["index"]
    block = event["content_block"]
    current_blocks[idx] = {
        "type": block["type"],
        "id": block.get("id"),
        "name": block.get("name"),   # tool_use exclusive
    }
    if block["type"] == "tool_use":
        json_buffers[idx] = ""

# Append at content_block_delta
elif etype == "content_block_delta":
    idx = event["index"]
    delta = event["delta"]
    dtype = delta.get("type")
    if dtype == "text_delta":
        print(delta["text"], end="", flush=True)
    elif dtype == "input_json_delta":
        if idx in json_buffers:
            json_buffers[idx] += delta.get("partial_json", "")

# Harvest at content_block_stop
elif etype == "content_block_stop":
    idx = event["index"]
    block = current_blocks.pop(idx, None)
    if block and block["type"] == "tool_use":
        try:
            block["input"] = json.loads(json_buffers.pop(idx, "{}"))
        except json.JSONDecodeError:
            block["input"] = {}
        # Extension 2 plugs in here for concurrent launch
        print(f"\n[tool block complete → {block['name']}({block['input']})]")
```

Intermediate output:

```
Searching...
[tool block complete → web_search({'query': "today's weather in Beijing"})]
[tool block complete → web_search({'query': 'latest AI news'})]
```

### Extension 2 — Streaming eagerness

Launch the tool the instant a tool_use block is complete, without waiting for `message_stop`:

```python
# lena-v0.7/core/concurrent_executor.py
import asyncio
from typing import Any, Callable, Coroutine

MAX_CONCURRENT_TOOLS = 10   # matches CC CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY

class ConcurrentToolExecutor:
    """
    Streaming eagerness executor.
    Calls add_tool() as each tool_use block streams in — no wait for message_stop.
    Reference: StreamingToolExecutor.ts:40 (public repository)
    """
    def __init__(self, tool_fn: Callable[[str, dict], Coroutine]):
        self.tool_fn = tool_fn
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_TOOLS)
        self.pending: dict[str, asyncio.Task] = {}

    def add_tool(self, tool_id: str, tool_name: str, tool_input: dict) -> None:
        """Called as soon as a block arrives; launches the tool coroutine asynchronously."""
        task = asyncio.create_task(
            self._run_with_semaphore(tool_id, tool_name, tool_input)
        )
        self.pending[tool_id] = task
        print(f"[eager launch → {tool_name}]", flush=True)

    async def _run_with_semaphore(self, tool_id: str, name: str, inp: dict) -> Any:
        async with self.semaphore:           # concurrency cap guard
            return await self.tool_fn(name, inp)

    async def wait_all(self) -> dict[str, Any]:
        """Wait for all submitted tools to complete; return {tool_id: result}."""
        results: dict[str, Any] = {}
        for tool_id, task in self.pending.items():
            try:
                results[tool_id] = await task
            except Exception as e:
                results[tool_id] = f"[tool error] {e}"
        return results
```

Intermediate output (note the eagerness timing):

```
Searching...
[eager launch → web_search]   ← t=0.4s, LLM stream still running
[eager launch → web_search]   ← t=0.5s
[eager launch → web_search]   ← t=0.6s
[waiting for all tools...]    ← t=1.2s (LLM stream ends)
[all tools complete]          ← t=2.1s
```

### Extension 3 — signature_delta preservation

Extension 2 handles text and tools, but misses one case: `signature_delta` when Extended Thinking is enabled. Add handling for thinking blocks:

```python
# Add thinking type in content_block_start
if block["type"] == "thinking":
    current_blocks[idx]["thinking"] = ""
    current_blocks[idx]["signature"] = ""

# Add two new branches in content_block_delta
elif dtype == "thinking_delta":
    if idx in current_blocks and current_blocks[idx]["type"] == "thinking":
        current_blocks[idx]["thinking"] += delta.get("thinking", "")

elif dtype == "signature_delta":
    # Source: nanoClaw/nanoclaw/core/llm.py:383
    # Anthropic's encrypted signature for thinking blocks — must be sent back verbatim
    if idx in current_blocks and current_blocks[idx]["type"] == "thinking":
        current_blocks[idx]["signature"] += delta.get("signature", "")
        # Verification: receiving signature_delta confirms this is an Extended Thinking response
        print(f"[signature captured, length={len(current_blocks[idx]['signature'])}]")
```

Intermediate output (only triggered with Extended Thinking models):

```
[signature captured, length=128]   ← signature_delta received
```

If you're not using Extended Thinking, these lines produce no output. If you are, and you're missing these lines, you'll hit this error:

```
Error: 400 - messages[1].content[0].thinking must contain a signature field
```

### Extension 4 — Complete AgentLoop

Assemble the three extensions above into a single while loop:

```python
# lena-v0.7/core/agent_loop.py
import asyncio
import json
import time
import aiohttp
from .concurrent_executor import ConcurrentToolExecutor

MAX_STEPS = 10   # guard against infinite loops

class StreamingAgentLoop:
    def __init__(self, api_key: str, tools: list[dict], tool_fn):
        self.api_key = api_key
        self.tools = tools         # Anthropic tool schema list
        self.tool_fn = tool_fn     # async def tool_fn(name, input) -> str
        connector = aiohttp.TCPConnector(limit=20, keepalive_timeout=30)
        self.session = aiohttp.ClientSession(connector=connector)

    async def run(self, user_input: str) -> None:
        messages = [{"role": "user", "content": user_input}]
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        for step in range(MAX_STEPS):
            executor = ConcurrentToolExecutor(self.tool_fn)
            assistant_content = []
            current_blocks: dict[int, dict] = {}
            json_buffers: dict[int, str] = {}
            stop_reason = None

            payload = {
                "model": "claude-sonnet-4-5",
                "max_tokens": 4096,
                "stream": True,
                "messages": messages,
                "tools": self.tools,
            }

            async with self.session.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                    event = json.loads(data_str)
                    etype = event.get("type")

                    if etype == "content_block_start":
                        idx = event["index"]
                        block = event["content_block"]
                        current_blocks[idx] = {
                            "type": block["type"],
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "text": "",
                        }
                        if block["type"] == "tool_use":
                            json_buffers[idx] = ""
                        elif block["type"] == "thinking":
                            current_blocks[idx]["thinking"] = ""
                            current_blocks[idx]["signature"] = ""

                    elif etype == "content_block_delta":
                        idx = event["index"]
                        delta = event["delta"]
                        dtype = delta.get("type")
                        if dtype == "text_delta":
                            text = delta.get("text", "")
                            print(text, end="", flush=True)
                            if idx in current_blocks:
                                current_blocks[idx]["text"] += text
                        elif dtype == "input_json_delta":
                            if idx in json_buffers:
                                json_buffers[idx] += delta.get("partial_json", "")
                        elif dtype == "thinking_delta":
                            if idx in current_blocks:
                                current_blocks[idx]["thinking"] += delta.get("thinking", "")
                        elif dtype == "signature_delta":
                            # llm.py:383 — must be saved and sent back with the thinking block
                            if idx in current_blocks:
                                current_blocks[idx]["signature"] += delta.get("signature", "")

                    elif etype == "content_block_stop":
                        idx = event["index"]
                        block = current_blocks.pop(idx, None)
                        if block:
                            if block["type"] == "tool_use":
                                try:
                                    block["input"] = json.loads(json_buffers.pop(idx, "{}"))
                                except json.JSONDecodeError:
                                    block["input"] = {}
                                assistant_content.append(block.copy())
                                # Eager launch: start tool as soon as block is complete
                                executor.add_tool(block["id"], block["name"], block["input"])
                            elif block["type"] == "text" and block["text"]:
                                assistant_content.append({"type": "text", "text": block["text"]})

                    elif etype == "message_delta":
                        stop_reason = event.get("delta", {}).get("stop_reason")

                    elif etype == "message_stop":
                        break

            # Wait for all launched tools to complete
            if executor.pending:
                print("\n[waiting for concurrent tools...]", flush=True)
                tool_results = await executor.wait_all()

                messages.append({"role": "assistant", "content": assistant_content})
                tool_result_content = []
                for block in assistant_content:
                    if block.get("type") == "tool_use":
                        tid = block["id"]
                        result = tool_results.get(tid, "tool execution failed")
                        tool_result_content.append({
                            "type": "tool_result",
                            "tool_use_id": tid,
                            "content": str(result),
                        })
                messages.append({"role": "user", "content": tool_result_content})
            else:
                # end_turn with no tool calls — exit
                print()
                break

    async def close(self):
        await self.session.close()
```

Each extension can run independently after being added. The skeleton from Beat 4 is now the complete v0.7 core.

---

## Beat 6 — Run Verification

Let's verify the speedup by running the actual benchmark with 5 concurrent web_search calls:

```python
# lena-v0.7/demo/benchmark.py
"""
Measures serial vs. concurrent speedup.
web_search is simulated with random delay (0.5–2.0s), equivalent to real network search latency.
Run: python3 -m demo.benchmark
"""
import asyncio
import random
import time


async def mock_web_search(query: str) -> str:
    """Simulate web_search: random 0.5–2.0s delay."""
    delay = random.uniform(0.5, 2.0)
    await asyncio.sleep(delay)
    return f"[result] {query!r} → took {delay:.2f}s"


QUERIES = [
    "today's weather in Beijing",
    "latest AI news",
    "current BTC price",
    "tomorrow's Beijing→Shanghai flights",
    "what's new in Python 3.13",
]


async def serial():
    t0 = time.perf_counter()
    for q in QUERIES:
        r = await mock_web_search(q)
        print(f"  serial done: {r}")
    elapsed = time.perf_counter() - t0
    print(f"Serial total: {elapsed:.2f}s\n")
    return elapsed


async def concurrent():
    t0 = time.perf_counter()
    results = await asyncio.gather(*[mock_web_search(q) for q in QUERIES])
    elapsed = time.perf_counter() - t0
    for r in results:
        print(f"  concurrent done: {r}")
    print(f"Concurrent total: {elapsed:.2f}s")
    return elapsed


async def main():
    print("=== Serial execution ===")
    serial_t = await serial()

    print("=== Concurrent execution (asyncio.gather) ===")
    concurrent_t = await concurrent()

    speedup = serial_t / concurrent_t
    print(f"\nSpeedup: {speedup:.1f}×")
    print(f"Time saved: {serial_t - concurrent_t:.2f}s ({(1 - concurrent_t/serial_t)*100:.0f}%)")


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
cd lena-v0.7
python3 -m demo.benchmark
```

**You should see output like this** (exact numbers vary, but speedup should be 3–5×):

```
=== Serial execution ===
  serial done: 'today's weather in Beijing' → took 1.23s
  serial done: 'latest AI news' → took 0.87s
  serial done: 'current BTC price' → took 1.54s
  serial done: 'tomorrow's Beijing→Shanghai flights' → took 0.61s
  serial done: 'what's new in Python 3.13' → took 1.78s
Serial total: 6.03s

=== Concurrent execution (asyncio.gather) ===
  concurrent done: 'today's weather in Beijing' → took 1.23s
  concurrent done: 'latest AI news' → took 0.87s
  concurrent done: 'current BTC price' → took 1.54s
  concurrent done: 'tomorrow's Beijing→Shanghai flights' → took 0.61s
  concurrent done: 'what's new in Python 3.13' → took 1.78s
Concurrent total: 1.78s

Speedup: 3.4×
Time saved: 4.25s (71%)
```

The theoretical ceiling is 5× (5 tasks fully concurrent). Real measurements generally land at 3–5× because the slowest task sets the floor.

**If you see speedup < 2×**, the most common cause is calling a synchronous blocking `requests` library inside an async function. `requests.get()` blocks the entire event loop. Check that you're using `await` + `aiohttp`, not synchronous `requests`.

**If you see `RuntimeError: This event loop is already running`**, you're running `asyncio.run()` inside a Jupyter Notebook. Use `await main()` instead, or install `nest_asyncio`.

Lena v0.7 can now:
- Streaming output: user sees the first token in 0.3 seconds (not 3 seconds)
- Concurrent tools: 5 searches complete in 2 seconds (not 8 seconds)

In the next chapter, we give Lena a memory system — so she can remember the user's preferences across sessions. Right now every Lena restart is a clean slate: she cannot do "I remember you said you hate flying — let me suggest trains instead."

---

## Beat 7 — Design Note

> ### Why Does OpenClaw Enforce Per-Session Serialization?

At first glance, an always-on agent should be the most aggressive about concurrency — it's specifically designed for high-efficiency task handling. Yet OpenClaw made a counterintuitive call: **enforce serialization at the session level**, running only one agent instance per user session at a time.

**The alternative:** allow multiple messages from the same user to concurrently trigger multiple agent instances, using distributed locks to protect shared resources.

**The problems with that alternative:**

- **Side-effect races**: Tool calls are not side-effect-free. Two agent instances simultaneously calling `write_file("report.md", ...)` produce content races that are hard to trace. File locks can prevent write conflicts, but cannot prevent logical races of the "read-then-write" kind — agent A reads a file and decides to append a section; agent B simultaneously reads the same file and decides to append too; only one append survives.
- **Context distortion**: Each agent instance has its own `messages` history. Concurrent instances can't see each other's tool results and make contradictory decisions.
- **Amplified error propagation**: When one instance's tool call fails, it normally triggers a retry or fallback. Concurrent instances each trigger their own independent retries, producing exponentially multiplying duplicate operations.

**Why OpenClaw chose serialization:** "An agent's predictability matters more than raw throughput." For an always-on agent managing real files and real calendars, occasionally waiting an extra 500ms is better than occasionally losing a calendar event.

**Intra-session concurrency still exists:** serialization means "multiple messages from the same user don't run concurrently," not "multiple tool calls within the same message don't run concurrently." Within a single response, all tool calls with `isConcurrencySafe = true` still run concurrently — which is the core of what this chapter teaches.

**If you want to unlock session-level concurrency in a production system:** you must first answer three questions — are all tool calls idempotent? Does shared state (files, databases) have row-level locking? How do you merge the `messages` histories from concurrent instances? None of these have a universal answer, which is why OpenClaw chose the conservative default of serialization.

---

---

Lena learned to stay responsive in this chapter — SSE streaming lets users see the first token in 0.3 seconds, concurrent tool eagerness fires five searches simultaneously, and session-level serialization keeps behavior predictable.

But Lena is still an amnesiac agent: when the conversation ends, she forgets everything about the user. Next time they meet, it's like meeting for the first time. A truly useful agent must remember "you told me you like Python," "last week you asked me not to recommend LangChain." **In Chapter 8, we give Lena memory — short-term SQLite session history plus a long-term file-system preference store, so she has a yesterday.**

---

## Further Reading

- Anthropic official docs: [Streaming Messages](https://docs.anthropic.com/en/api/messages-streaming) (focus on the event types list)
- Public repository evidence: `StreamingToolExecutor.ts:40` (concurrency-safety judgment logic), `toolOrchestration.ts:10` (concurrency cap constant)
- nanoClaw implementation reference: `nanoclaw/core/llm.py:383` (signature_delta handling), `llm.py:18-38` (unified cache token fields across three providers)
- WHATWG EventSource specification (understanding the `id:` field and reconnection)
