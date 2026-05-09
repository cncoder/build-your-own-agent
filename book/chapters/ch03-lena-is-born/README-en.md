# Chapter 3: Lena Is Born — A Runnable Agent in 50 Lines of Python

> **[Pillar: Tool Universality]**

---

## Beat 1 — Roadmap

```
Ch 1 → Ch 2 → [Ch 3 ← you are here] → Ch 4 → Ch 5 → …
```

In the last chapter you understood what the ReAct loop is, drew a state machine diagram, and wrote down the key insight: "the next LLM call includes the observation from the previous step." That was a **paper agent**.

This chapter turns that diagram into **real, runnable Python code**.

The path looks like this: start from an empty skeleton that only prints `"OK"` → add the tool registration mechanism → connect to the LLM → write the while loop → parse `tool_use` → backfill `tool_result`. Each step runs; each step prints a meaningful output. The final product is `lena-v0.3`: type "What time is it?" in the terminal, and Lena responds by calling a real tool.

After this chapter, Lena upgrades from v0.1 (bare API call) to **v0.3**, gaining two new capabilities: **tool calling + multi-turn loop**.

There's one trap along the way: when backfilling the tool result, you must first store the "LLM decided to call a tool" message in history before appending the result — miss this step and the API errors. A lot of people get stuck here the first time.

> **🧠 Intelligence increment (v0.2 → v0.3):** Lena runs through a proper cross-provider abstraction for the first time — using a unified `BaseProvider` interface to connect Anthropic, OpenAI, and Bedrock. Switching models requires zero changes to business logic. This chapter teaches you how to build the provider abstraction layer into your own agent.

---

## Beat 2 — Motivation

Andrej Karpathy, in his 2025 YC Startup School talk, offered a sharp analogy:

> "LLMs are kind of like these fallible people spirits that we have to learn to work with."

This sentence defines the core problem of this chapter: what we're writing is not a script that calls an API — it's a **skeleton that knows how to collaborate with a fallible spirit**. It has to tolerate the spirit making mistakes, guide the spirit toward doing the right thing, and stop the spirit when it goes off the rails. That skeleton is the core agent loop of Lena.

First, let's feel what happens without tools.

```python
# Lena v0.1 without tools (Ch 1 output)
response = client.messages.create(
    model="claude-haiku-4-5-20251001",  # 2026 Claude 4.X series (2024 versions deprecated)
    max_tokens=64,
    messages=[{"role": "user", "content": "What time is it?"}],
)
print(response.content[0].text)
```

After running this, you'll see something like:

```
I don't have access to a real-time clock, so I can't tell you the current time.
You can check your phone or computer for the accurate time.
```

This is a correct and honest answer — the LLM wasn't trained with access to live data, so it genuinely doesn't know the current time.

Now imagine this scenario: you want to build a scheduling assistant. The user asks "what meetings do I have this afternoon?" and you want Lena to check the calendar before answering. Or the user says "summarize the sales data in this CSV for me," and you want Lena to actually read the file.

These tasks share a common trait: **the LLM can't complete them from training data alone — it must access external capabilities**. Clocks, file systems, APIs, databases — these are all outside what an LLM can naturally reach.

The solution isn't a smarter model. It's giving the LLM "tools" so it can actively initiate calls, retrieve results, and then make decisions. That's the problem this chapter solves.

The beauty of this solution is its generality. Today you give Lena `get_time`; tomorrow you can add `read_file`; the day after, `web_search`. The "brain" of Lena (the AgentLoop) needs no modification — it simply reads the tool list, passes the tool descriptions to the LLM, and executes whichever tool the LLM selects. Tools are the boundary of an agent's capabilities, and that boundary is entirely yours to define. This is why the SPEC document calls it the "Tool Universality Pillar": any external capability can be wrapped as a tool, and the agent's core code has zero awareness of what any specific tool does.

> **Convention: Tool = one schema + one handler.** The schema is the user manual for the LLM; the handler is the Python function that actually runs. The LLM only ever sees the schema and never executes code; execution always happens inside your Python process. From here on, "schema" refers to the usage description, "handler" refers to the execution function.

---

## Beat 3 — Theory

### 3.1 The Three Components of an Agent

Break open a minimal viable agent and you'll find it only does three things:

**LLM** — the decision engine. It reads all current context (the user's words, tool usage descriptions, history of execution results) and decides what to do next: call a tool, or give the final answer directly.

**Loop (while loop)** — the execution engine. A single API call only lets the LLM make one decision. If the LLM decides to call a tool this time, you need to execute the tool, feed the result back to the LLM, and let the LLM decide again — this feedback cycle is the essence of the while loop. Without the Loop, you only have one-shot Q&A — not an agent.

**Tools** — the action capabilities. The LLM can describe actions but cannot execute them; your code can execute actions but doesn't know when it should. Tools are the interface between the two: the LLM outputs "I want to call X(args)," and your code receives that intent and actually runs X.

> **Convention: agent = LLM + Loop + Tools.** This triplet is the minimal viable definition. LangChain, AutoGen, CrewAI — all frameworks — are fundamentally this triplet wrapped in a prettier API. The names change; the essence is the same.

This simplicity is well documented. Anthropic writes in [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) (2024-12-19):

> "Many agents will be overkill. Start with prompting. If prompting doesn't work, start with the simplest agent architecture. Don't add complexity until you demonstrably need it."

The implication: the tool-calling while loop *is* the "simplest agent architecture." Before you need anything more, these 50 lines are enough.

**The limitations of each dimension of the triplet** are also worth spelling out clearly:

- **LLM only, no Loop:** each user input gets exactly one LLM response. If the LLM needs to call a tool to retrieve data and then reason about that data, the flow can't complete. You get only the LLM's first-step decision, not a final result.
- **Loop only, no Tools:** the LLM cycles over and over, but all it can do is generate text. The loop spins in place; no new information enters.
- **Tools only, no Loop:** tools get called once. The user asks something, you call a tool, return the result directly — but if the task requires deciding whether to call a second tool based on the first tool's result, that chained decision can't happen.

All three are indispensable. This is also why Ch 2 used a state machine to describe the agent: Thought → Action → Observation → Thought, at the code level, maps directly to LLM + while loop + tools_execute.

### 3.2 The tool_use Protocol: How the LLM "Calls" a Tool

The LLM cannot call functions directly — its output is always text. An actual tool call is a two-step process:

**Step one: the LLM outputs an intent.** When the LLM judges it needs to call a tool, instead of outputting a normal text response, it outputs a special JSON block inside the `content` array. The format is roughly (Anthropic native format):

```
type: tool_use
name: get_time
id:   toolu_01AbCd… (unique per call, used to correlate the result)
args: {}
```

Simultaneously, the `stop_reason` field in the API response is `"tool_use"` rather than `"end_turn"` — this is the signal your code uses to determine "does a tool need to be called?"

**Step two: your code executes and backfills.** Your code reads `stop_reason == "tool_use"`, parses out the tool name and args, calls the corresponding Python function, and gets the result. Then it appends that result in a specific format to `messages[]` and calls the LLM again — this time the LLM sees the tool result and gives the final answer.

Throughout this whole flow, `messages[]` is the only state container. Every LLM call sees the complete history — the user's message, the LLM's decisions, the tool results — and then decides the next step based on this full context.

> **Convention: stop_reason = "tool_use" means the LLM is requesting a tool call; stop_reason = "end_turn" means the LLM is giving its final answer.** The branching logic in agent_loop is entirely based on these two values.

This mechanism is fully specified in the Anthropic official docs at [Tool Use Overview](https://docs.anthropic.com/en/docs/build-with-claude/tool-use). You don't need to read it all — just know one core conclusion: **tool_result must be backfilled with the user role, and it must come immediately after the assistant message containing the tool_use** — this is the most error-prone part, and Beat 5 covers it specifically.

### 3.3 MVA 6 Modules: The Industry Common Denominator

Before we start writing code, let's take a high-level look at the whole picture.

After comparing three public teaching-grade agent implementations (nano-claw TS version: 247 lines in `src/agent/loop.ts`; nanoClaw Python version: `core/agent.py`; and an ultra-minimal pydantic-ai version: `src/agent_app.py`), we can distill a **6-module consensus for a Minimum Viable Agent (MVA)** — these three projects were written by people from different backgrounds, in different languages, yet they independently converged on the same module boundaries:

| Module | Responsibility | Why it deserves its own module |
|--------|---------------|-------------------------------|
| **Config** | Read environment variables and CLI args, decouple configuration sources | API keys and model names shouldn't be hardcoded — or you'd have to edit code every time you change machines |
| **Provider** | Normalize format differences across LLM APIs, so AgentLoop is unaware of them | Anthropic / OpenAI / Bedrock have different formats; isolating them in the Provider layer means zero awareness above it |
| **Memory** | Manage the `messages[]` conversation history, maintain "current context" | Every LLM call is stateless; `messages[]` is the entire secret of having state |
| **ToolRegistry** | Register tools + execute them, route by name to the correct handler | Tool variety grows; AgentLoop shouldn't need to know "what this tool is called" |
| **AgentLoop** | while loop + stop_reason branching, the neural center of the agent | Decision logic and tool execution logic must be separated — otherwise changing a tool means touching the loop |
| **Skills** | Reusable capability packages (SOP + optional code), not covered in this chapter, expanded in Ch 10 | Tools are functions; Skills are the SOP for "how to do a class of things" — two different dimensions of abstraction |

These 6 modules are the **common denominator of all agent frameworks**. LangChain has `LLMChain` (AgentLoop), `BaseTool` (ToolRegistry), `ConversationBufferMemory` (Memory); AutoGen has `ConversableAgent` (AgentLoop + Provider). The names change; the essence is the same. Understanding this is important: frameworks aren't inventing new concepts — they're putting prettier wrappers around existing ones.

The construction strategy in this chapter is **skeleton-first**: write all 6 modules as empty functions or stub classes first, confirm the pipeline works end-to-end, then fill in real logic module by module. Add only one new part to the skeleton at a time, and run it to verify after each addition. This has much higher fault tolerance than "write all the code then run it" — when you know "the last step was fine, so this step broke it," locating a bug shrinks from hours to minutes.

Raschka uses this exact strategy in *Build a Large Language Model from Scratch*, Chapter 4: first build a `DummyGPTModel` with all sub-modules as `pass` placeholders, confirm the overall shape, then fill in `LayerNorm`, `FeedForward`, and `MultiHeadAttention` layer by layer. This chapter follows the same approach.

---

## Beat 4 — Scaffold

We start with the **skeleton-first strategy** (from Raschka's *LLMs from Scratch* Ch04, where `DummyGPTModel` is first built and then filled in layer by layer): write all 6 modules as empty classes/functions, each one "runs" but does nothing, then fill in real logic one by one.

Let's build the skeleton by putting all six modules as empty stubs, then run it to confirm the wiring is correct:

```python
# lena-skeleton.py — 6-module empty skeleton (runs, but has no real logic)

# ── Module 1: Config ─────────────────────────────────────────────────────────
# Responsibility: read .env and CLI args, so other modules need no hardcoded config
import argparse, os

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--provider", default="stub")   # start with stub, replace later
    p.add_argument("--max-turns", type=int, default=10)
    return p.parse_args()

# ── Module 2: Provider (stub) ─────────────────────────────────────────────────
# Responsibility: normalize format differences across LLM APIs, AgentLoop is unaware of switching
class StubProvider:
    """Skeleton provider: returns a fixed answer without calling any real API. Useful for pipeline validation."""
    def chat(self, messages, tools):
        return StubResponse(content="stub reply", tool_calls=[])

    def make_assistant_with_tool_use(self, response):
        return {"role": "assistant", "content": []}

    def make_tool_result_message(self, tool_id, result):
        return {"role": "user", "content": []}

class StubResponse:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls   # empty list = no tool calls

# ── Module 3: Memory ──────────────────────────────────────────────────────────
# Responsibility: maintain messages[] list; all state lives here
messages = []   # simplest Python list for this chapter; upgraded to SQLite persistence in Ch 7

# ── Module 4: ToolRegistry (stub) ─────────────────────────────────────────────
# Responsibility: register tools + route by name to correct handler
def get_tool_schemas():
    return []   # no tools yet

def execute_tool(name, inputs):
    return f"Unknown tool: {name}"   # doesn't execute anything yet

# ── Module 5: AgentLoop ───────────────────────────────────────────────────────
# Responsibility: while loop + stop_reason branching, the neural center of the agent
def agent_loop(user_input, provider, max_turns):
    messages.append({"role": "user", "content": user_input})
    tools = get_tool_schemas()

    for turn in range(max_turns):
        response = provider.chat(messages, tools)

        if response.tool_calls:           # tool call branch (won't trigger yet)
            messages.append(provider.make_assistant_with_tool_use(response))
            for tc in response.tool_calls:
                result = execute_tool(tc["name"], tc["inputs"])
                messages.append(provider.make_tool_result_message(tc["id"], result))
            continue

        messages.append({"role": "assistant", "content": response.content})
        return response.content

    return "(max turns reached)"

# ── Module 6: Skills (not implemented in this chapter) ────────────────────────
# Responsibility: reusable capability packages (SOP + optional code), expanded in Ch 10
# skills = []   # leave empty for now

# ── REPL main loop ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    args = parse_args()
    provider = StubProvider()
    print("Lena skeleton ✦ try typing anything")
    while True:
        user = input("You: ").strip()
        if user in ("exit", "quit"):
            break
        print(f"Lena: {agent_loop(user, provider, args.max_turns)}\n")
```

Run this skeleton:

```bash
python3 lena-skeleton.py
You: hello
Lena: stub reply

You: what time is it?
Lena: stub reply
```

The pipeline is connected: user input → AgentLoop → Provider → response. Now replace StubProvider with a real LLM, fill in `get_time` in the empty ToolRegistry, and you have this chapter's full implementation. Let's do that step by step.

---

## Beat 5 — Incremental Assembly

Starting from the skeleton, fill in three real capabilities in sequence:

| Extension | Why it's needed | How to add it |
|-----------|----------------|---------------|
| Fill ToolRegistry with get_time | The LLM needs a callable tool to actually "do things" | Define schema + handler, register in TOOLS list |
| stop_reason check | Distinguish between LLM ending naturally (returns text) vs. requesting a tool (continue loop) | Check whether `response.tool_calls` is empty |
| tool_result backfill order | The LLM needs correctly formatted history to continue reasoning | Store the assistant message first, then append tool_result |

### Extension 1: Populate the ToolRegistry

Let's implement the first real tool — a clock that tells the current time:

```python
# tools.py (complete version)

from datetime import datetime
from typing import Any

def get_time_handler(timezone: str = "local") -> str:
    """The function that actually executes get_time. Depends only on the standard library; zero side effects."""
    now = datetime.now()
    return now.strftime(f"Current time: %Y-%m-%d %H:%M:%S ({timezone})")

TOOLS: list[dict[str, Any]] = [
    {
        "schema": {
            "name": "get_time",
            "description": "Get the current local time. Call this when the user asks questions like 'what time is it?' or 'what's today's date?'",
            "input_schema": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Timezone description, default 'local'",
                        "default": "local",
                    }
                },
                "required": [],   # all parameters optional, LLM can call with no args
            },
        },
        "handler": get_time_handler,
    }
]

def get_tool_schemas() -> list[dict]:
    """Return the schema list for all tools (the part sent to the LLM)."""
    return [t["schema"] for t in TOOLS]

def execute_tool(name: str, inputs: dict) -> str:
    """Route by name and execute a tool, return string result."""
    for tool in TOOLS:
        if tool["schema"]["name"] == name:
            try:
                return str(tool["handler"](**inputs))
            except Exception as e:
                return f"Tool execution error: {e}"
    return f"Unknown tool: {name}"
```

Quick verification that the handler works:

```python
>>> from tools import get_time_handler, execute_tool
>>> get_time_handler()
'Current time: 2026-05-06 00:24:16 (local)'
>>> execute_tool("get_time", {})
'Current time: 2026-05-06 00:24:16 (local)'
>>> execute_tool("no_such_tool", {})
'Unknown tool: no_such_tool'
```

The tool itself works. Now replace StubProvider with the real LLM.

### Extension 2: Connect the Provider

This is the part of this chapter most worth examining carefully, because **Anthropic and OpenAI's protocol formats genuinely differ** — not in minor details, but in multiple places across the message structure.

Here's a comparison:

| Comparison point | Anthropic | OpenAI |
|-----------------|-----------|--------|
| Location of tool call | Inside `response.content[]` array as a block | Top-level `response.choices[0].message.tool_calls` field |
| Args field | `input` (Python dict) | `arguments` (JSON string, needs json.loads) |
| Tool result role | `"user"` (with a special content format) | `"tool"` (an independent fourth role) |
| Correlation ID field name | `tool_use_id` | `tool_call_id` |

These 4 differences are independent — each one can cause an API error on its own. The value of the Provider layer is encapsulating these differences inside it, so the AgentLoop's core code doesn't need to know which API it's using.

You might think: just use OpenAI's compatibility interface and align all providers to one format. That's viable and many projects take that approach. But the trade-off is losing each provider's native features — for example, in Anthropic's tool call response, text and tool intent can coexist in the same `content` array (the LLM says "let me check," then provides a tool_use block), while OpenAI's format separates them into different fields. If you want to preserve this "thinking text," you need the native format. That's why this chapter adapts each provider's format in the Provider layer rather than forcing everything to match one vendor.

Let's look at what Anthropic's tool call response actually looks like, piece by piece:

```python
# Structure of Anthropic's tool call response (illustrative)
response.content = [
    # block 1: LLM's thinking text (may or may not be present)
    {"type": "text", "text": "Let me check the current time for you…"},

    # block 2: tool call intent
    {
        "type": "tool_use",
        "id": "toolu_01AbCd...",   # ← unique ID per call; tool_result must reference this
        "name": "get_time",
        "input": {}                # ← args are a dict (not a string)
    }
]
response.stop_reason = "tool_use"  # ← this is the key signal for branching
```

Then there's the tool_result backfill format — here's the trap:

```python
# Correct backfill order (both steps required; order cannot be reversed)

# Step one: store the LLM's "decided to call tool" message into messages first
messages.append({
    "role": "assistant",
    "content": [
        {"type": "text", "text": "Let me check…"},          # if the LLM had text
        {"type": "tool_use", "id": "toolu_01AbCd...",
         "name": "get_time", "input": {}}
    ]
})

# Step two: execute the tool, backfill the result with user role
messages.append({
    "role": "user",
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_01AbCd...",   # ← must match the id above
            "content": "Current time: 2026-05-06 00:24:16 (local)"
        }
    ]
})
```

If you skip step one and append the tool_result directly, the Anthropic API returns `400 Bad Request`, with an error message roughly saying "cannot find the corresponding tool_use message." This is one of the most common errors beginners encounter.

Why does the API require this order? Because in Anthropic's protocol design, a tool_result message is linked to a specific tool_use block via `tool_use_id`. The API needs to find that ID in history to understand "what tool call this result belongs to." If the ID can't be found in history, the API cannot reconstruct the complete causal chain — so it rejects the request.

This design isn't gratuitous. If the LLM calls 3 tools simultaneously in a single response (which you'll encounter in Ch 5), `tool_use_id` is the only way the API can know "which result corresponds to which call." Without ID correlation, tool results become orphaned messages.

This is why this chapter uses a `make_assistant_with_tool_use()` method to encapsulate this — so that every tool call in AgentLoop is forced to follow these two steps, rather than relying on developers to remember the order.

```python
# provider.py (AnthropicProvider core, remainder in code/lena-v0.3/provider.py)

class AnthropicProvider:
    def chat(self, messages, tools):
        resp = self.client.messages.create(
            model=self.model, max_tokens=1024,
            system="You are Lena, a helpful AI assistant.",
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
        """Package the response containing tool_use as an assistant message (must store this first)."""
        content = []
        if response.content:
            content.append({"type": "text", "text": response.content})
        for tc in response.tool_calls:
            content.append({"type": "tool_use", "id": tc["id"],
                             "name": tc["name"], "input": tc["inputs"]})
        return {"role": "assistant", "content": content}

    def make_tool_result_message(self, tool_id, result):
        """Package the tool result as a user message (step two)."""
        return {"role": "user",
                "content": [{"type": "tool_result",
                              "tool_use_id": tool_id, "content": result}]}
```

### Extension 3: Assemble the Complete AgentLoop

With ToolRegistry and Provider in place, wire them into the AgentLoop from the skeleton:

```python
# lena.py — agent_loop() (complete implementation)

def agent_loop(user_input: str, provider, max_turns: int) -> str:
    messages.append({"role": "user", "content": user_input})
    tools = get_tool_schemas()   # ← always fetch the latest tool list

    for turn in range(max_turns):
        # ── Call the LLM, get a normalized response ────────────────────────────
        response = provider.chat(messages, tools)

        if response.tool_calls:
            # ── Critical: store assistant (with tool_use) first, then append tool_result ──
            messages.append(provider.make_assistant_with_tool_use(response))

            for tc in response.tool_calls:
                result = execute_tool(tc["name"], tc["inputs"])
                print(f"  [tool] {tc['name']}({tc['inputs']}) → {result}")
                messages.append(provider.make_tool_result_message(tc["id"], result))

            continue   # back to top of loop, let LLM see tool results and decide again

        # ── LLM gives a text response directly, loop ends ─────────────────────
        messages.append({"role": "assistant", "content": response.content})
        return response.content

    return "(max tool call turns reached)"
```

Note the role of `max_turns`: this is defensive code that prevents tool calls from entering an infinite loop. A poorly designed tool or a particular prompt may cause the LLM to repeatedly call the same tool. The 10-turn cap ensures the agent doesn't consume tokens endlessly.

If your use case genuinely requires more than 10 tool call turns per task (e.g., writing a long report requires repeated research lookups), you can increase the number — but start small and adjust when business needs arise, rather than setting 100 from the start.

Combine these three extensions and you have the complete `lena-v0.3`. Take a moment to trace the full data flow: user input comes in, passes through Config parsing, AgentLoop driving, Provider translation, ToolRegistry execution, and Memory appending, and the final response comes out. Each module does exactly and only what it's responsible for. This is why the 6-module consensus converged to the same structure in three independent implementations — when a problem is decomposed naturally, different people arrive at the same boundary division independently.

**An intuition about Memory:** the Memory in this chapter is a Python list that grows after every `agent_loop` call. After asking "what time is it?", `messages[]` has 4 entries; ask another question and more get appended. This means as the conversation grows, the token cost of each LLM call grows too — because the `messages` you pass in keep getting longer. This isn't a problem in short conversations, but in real long-running tasks it will hit the context window limit. The solution is Context Engineering, which Ch 8 covers in detail. For now, just remember: `messages[]` is the agent's entire memory, and its only bottleneck.

---

## Beat 6 — Running Verification

### Installation and Running

```bash
cd code/lena-v0.3
pip install -r requirements.txt
cp .env.example .env   # edit to add your API key

# Anthropic (requires ANTHROPIC_API_KEY)
python3 lena.py

# OpenAI (requires OPENAI_API_KEY)
python3 lena.py --provider openai

# AWS Bedrock (requires aws credentials configured, us-west-2)
python3 lena.py --provider bedrock
```

### Real Terminal Output (Bedrock, verified 2026-05-06)

```
$ python3 lena.py --provider bedrock

Lena v0.3 ✦ provider=bedrock
Type 'exit' or press Ctrl-C to quit

You: What time is it?
  [tool] get_time({}) → Current time: 2026-05-06 00:24:31 (local)
Lena: It's currently **2026-05-06 00:24**. It's quite late! 🌙
Rest well — let me know if there's anything else I can help with! 😊

You: What day of the week is it?
Lena: Based on the time I just retrieved, **May 6, 2026** is a **Wednesday**! 📅

You: exit
Goodbye!
```

A few details worth noting:

**The LLM was called twice.** On the first question about the time, you see the `[tool]` line print — meaning the AgentLoop ran one full "call tool → backfill → ask LLM again" cycle, and the LLM's second call produced the final response.

**The second question didn't trigger another tool call.** When asked "what day of the week," there's no `[tool]` print, because the time information is already in `messages[]` and the LLM inferred the day of the week directly from context. This is the value of the Memory module: eliminating unnecessary repeated calls.

**If you encounter errors**, the two most common situations:

- `ANTHROPIC_API_KEY not found`: check whether `.env` is filled in correctly, or whether `source .env` took effect
- `400 Bad Request: messages: roles must alternate`: usually means `messages[]` has consecutive messages with the same role — check whether `make_assistant_with_tool_use` was skipped during a tool call

### How messages[] Evolves in One Conversation

This snapshot helps you understand the actual contents of the Memory module:

```python
# Complete state of messages[] after asking "What time is it?"

messages = [
    # user input
    {"role": "user", "content": "What time is it?"},

    # LLM's first response (decided to call a tool)
    {"role": "assistant", "content": [
        {"type": "text",     "text": "Let me check the current time…"},
        {"type": "tool_use", "id": "toolu_xxx",
         "name": "get_time", "input": {}}
    ]},

    # tool result (backfilled with user role)
    {"role": "user", "content": [
        {"type": "tool_result",
         "tool_use_id": "toolu_xxx",
         "content": "Current time: 2026-05-06 00:24:31 (local)"}
    ]},

    # LLM's second response (final answer)
    {"role": "assistant",
     "content": "It's currently **2026-05-06 00:24**. It's quite late! …"}
]
```

4 messages, 2 LLM calls, 1 tool call. This is the complete execution trace for the "what time is it?" task, all preserved in `messages[]`.

With this snapshot in hand, you can reason backward: if you wanted Lena to still "remember" today's conversation the next time she starts up, what would you need? The answer is direct — serialize `messages[]` to disk and restore it on the next startup. That's exactly what the Memory module in Ch 7 does: replace this Python list with SQLite persistence. The skeleton stays the same; the data layer gets upgraded.

One more detail in the snapshot above is worth paying attention to: `role: "user"` appears twice — once for the actual user input, once for the tool result backfill. This "impersonating user messages with tool results" is a deliberate choice in Anthropic's protocol. The meaning is: **tool results are, in the LLM's eyes, "input from the external world" — on the same semantic level as user input.** The LLM makes decisions based on these inputs, and doesn't care whether the input came from a human's keyboard or from the return value of a Python function. Once you understand this, you understand why an agent can "inject" any external data (sensor readings, database queries, web page content) into the LLM's decision context — it all goes through the same path: `role: "user"` + `type: "tool_result"`.

### Chapter Summary

At this point, starting from zero, you've implemented a complete runnable agent in roughly 150 lines of Python (lena.py + provider.py + tools.py combined). It meets three core criteria:

1. **Autonomous decision-making:** Lena decides on its own when to call a tool — you don't tell it "call get_time now"
2. **Multi-turn execution:** if a task requires multiple tool calls, Lena's while loop supports any number of turns
3. **Cross-provider operation:** the same AgentLoop code runs on all three LLM providers just by switching the `--provider` flag

These 3 points are the most fundamental skeleton of an agent that can "autonomously do anything." All subsequent chapters add new capabilities on top of this skeleton — more tools, persistent memory, sub-task decomposition, long-task recovery — rather than starting over.

---

## Beat 6.5 — Hands-on Lab: Run Your First Agent from Scratch

Above you saw someone else's output. Now it's your turn. Here is a complete, copy-pasteable sequence of operations — from an empty directory to Lena answering "what time is it?", **in under 5 minutes**.

**Prerequisites:** Python 3.10+, an Anthropic API key (or OpenAI key).

```bash
# Step 1: Create project directory
mkdir lena-lab && cd lena-lab

# Step 2: Install dependencies (just one)
pip install anthropic

# Step 3: Set API key
export ANTHROPIC_API_KEY="sk-ant-xxx"   # replace with your key
```

**Step 4: Create a single-file agent (all logic in one file for easy data flow understanding)**

Save the following as `agent.py`:

```python
import anthropic
from datetime import datetime

client = anthropic.Anthropic()
messages = []

TOOLS = [{
    "name": "get_time",
    "description": "Get the current local time",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}]

def execute(name, inputs):
    if name == "get_time":
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"Unknown tool: {name}"

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

    return "(step limit exceeded)"

if __name__ == "__main__":
    print("Lena Lab ✦ type exit to quit\n")
    while True:
        q = input("You: ").strip()
        if q in ("exit", "quit", ""): break
        print(f"Lena: {run(q)}\n")
```

**Step 5: Run and observe**

```bash
python3 agent.py
```

You should see:

```
Lena Lab ✦ type exit to quit

You: what time is it?
  🔧 get_time() → 2026-05-08 11:23:45
Lena: It's currently 11:23 AM on May 8, 2026.

You: what's 7 * 8?
Lena: 7 × 8 = 56.

You: exit
```

**Key observations:**
- The first question triggered a tool call (you saw the 🔧 output)
- The second question did **not** trigger a tool call — the LLM can compute that itself, so it answered directly
- This is the core wisdom of the ReAct loop: **the LLM decides when a tool is needed**

**Step 6: Add a tool of your own**

Add a new tool definition to the TOOLS list, and add a new branch to execute(). For example, add a "random number" tool:

```python
# Add to TOOLS list
{"name": "random_number", "description": "Generate a random integer from 1 to 100",
 "input_schema": {"type": "object", "properties": {}, "required": []}},

# Add to execute() function
if name == "random_number":
    import random
    return str(random.randint(1, 100))
```

Restart and ask Lena "give me a random number" — she'll call your new tool. **AgentLoop: zero lines changed.** This is the power of the Tool Universality pillar.

---

## Beat 6.6 — Troubleshooting: When Lena Goes Wrong

Hitting errors when running agent code is normal. Here are the 5 most common problems beginners encounter and their fixes:

| Error message | Root cause | Fix |
|--------------|-----------|-----|
| `AuthenticationError: 401` | API key invalid or not set | Run `echo $ANTHROPIC_API_KEY`, confirm it's non-empty and correctly formatted |
| `400: messages: roles must alternate` | Two messages with the same role appear consecutively in messages[] | Check whether `messages.append({"role": "user", ...})` was skipped after a tool call |
| `400: tool_use_id not found` | The ID in tool_result doesn't match the tool_use | Confirm you're using `b.id` (from the response), not an ID you made up |
| `TypeError: 'ContentBlock' is not subscriptable` | Treating an SDK object as a dict | Use `b.type` instead of `b["type"]` — the SDK returns objects, not dicts |
| Loop never stops, token count skyrockets | Missing `if resp.stop_reason == "end_turn": return` | Add exit condition; also confirm `max_steps` has an upper bound |

**Three debugging moves** (try in order):

1. **Print messages[]:** `import json; print(json.dumps(messages, indent=2, default=str))` — 90% of bugs live in the messages structure
2. **Print stop_reason:** `print(f"stop_reason={resp.stop_reason}")` — confirm whether the LLM wants to call a tool or end
3. **Stub out the real LLM:** have the provider return a fixed tool_use response, to isolate whether the problem is in the LLM or in your code

If all three moves fail, go back to the Wire-Level Trace section in Ch 2 and verify against the messages JSON format field by field. Bugs always live in the data, not the logic — agent code logic is just `while + if`; all the complexity is in getting the data structure format right.

---

## Beat 7 — Design Note

> **Why Not LangChain's AgentExecutor?**

LangChain's `AgentExecutor` (from `langchain>=0.1.0`) does exactly what this chapter's `agent_loop()` does: while loop + tool calling + result backfill. The difference is that it has more layers on top.

**The trade-offs of using AgentExecutor:**

- **Longer debugging path.** When something goes wrong, you have to trace through `AgentExecutor` → `BaseSingleActionAgent` → `LLMChain` → `ChatAnthropic` to find the actual API call. The code in this chapter has the entire call chain visible in one file.
- **Lower version stability.** LangChain underwent a major refactoring from `langchain` to `langchain-core` in 2023–2024, and the AgentExecutor API changed along with it. Code learned from v0.1 may be a completely different way of writing things by v0.3. Knowledge organized around a framework's API has a short shelf life.
- **Abstraction hides fundamentals.** Armin Ronacher (creator of Flask) was quoted in Simon Willison's blog observing this problem: "existing SDKs aren't worth adopting yet" — not because they're bad, but because using a framework before understanding the underlying principles leaves you without intuition for "what went wrong."

**The reason this chapter writes from scratch:** Anthropic and OpenAI's format differences are just 4 fields (see the comparison table in Beat 5), fully encapsulated in 100 lines of provider.py — no need to bring in a framework with tens of thousands of lines of code.

**When should you use LangChain?** When you need these ready-made components: LCEL streaming pipelines, the LangSmith observability platform, integration with a large ecosystem of existing tools (SerpAPI, Wikipedia, vector databases). These are LangChain's real value, not its agent loop abstraction.

**This is a trade-off, not a right-or-wrong question.** This book is not saying LangChain is bad to use — it's saying that relying on a framework before you understand how agents work underneath will leave you unable to locate problems when things go wrong. Once you can build and debug an agent in 100 lines of code, using LangChain is a qualitatively different experience — you know what the framework is doing, and you know which layer to look in when things error.

Write a working agent in 50 lines first; then look at frameworks. You'll feel much more in control. This is an observed effective path across multiple agent teaching courses: write the primitives by hand first, then use the framework. The order matters — do it in reverse and it's hard to build genuine understanding; when things break, all you can do is retry, not diagnose.

To be honest about limitations: the StubProvider → AnthropicProvider pattern in this chapter is essentially a **hand-rolled provider abstraction**. It works well for single tool calls, but is not robust at the edges. For example, if the LLM returns a mix of text and multiple tool_use blocks in one response, the current implementation handles it, but if a tool_use block also carries a `cache_control` field (Anthropic's prompt caching feature), your `make_assistant_with_tool_use` would need to pass that field through, otherwise the cache breaks. These details are the territory of Ch 8 Context Engineering. The current implementation is sufficient for this chapter's teaching goals — there's no need to aim for production completeness here. This is the "simple first, complex later" principle in action.

---

---

## Narrative Hook

Lena can now answer "what time is it?" But she only has one tool, and a truly useful assistant needs to read files, execute commands, and search the web. When you expand the toolkit from 1 tool to 4, you don't want to modify a single line of AgentLoop — that's the problem the **tool registration mechanism** is designed to solve. In the next chapter, we design a ToolRegistry where "adding tools doesn't change the core," and then use 4 tools to complete the first genuinely multi-step task.

---

## Revision Log

| Version | Date | Changes |
|---------|------|---------|
| v2 | 2026-05-05 | Rewritten from scratch: introduced skeleton-first pattern (Raschka DummyGPTModel strategy), 6 modules filled in one by one; added Beat 2 motivation code; moved MVA 6-module table to Beat 3 theory instead of presenting it all at once; strengthened explanation of tool_result backfill order; added R9 self-check table; fixed RULE-02 absolute path violations (further reading table); fixed RULE-13 missing chapter-end narrative hook |
| v1 | 2026-05-04 | Initial version (backed up as README-v1-discarded.md) |

---

## Navigation

➡️ **[Ch 6. The Tool System](../ch06-tool-system/README-en.md)** — Unified tool registry management: add tools without touching the core loop

[← Ch 2. The Secret of the ReAct Loop](../ch02-react-loop/README-en.md) · [📘 Back to table of contents](../../README.md)
