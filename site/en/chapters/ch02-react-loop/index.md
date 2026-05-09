# Ch 02 · From Chat to Agent: The Secret of the ReAct Loop

---

## Beat 1 — Roadmap

```
Ch 01 → [Ch 02] → Ch 03 → Ch 04 → ...
  ↑         ↑
Lena v0.1  Lena v0.2 (this chapter)
print reply   mental model of the loop
              (code implemented in Ch 03)
```

This chapter starts with a question: **Why can't ChatGPT actually get things done for you?**

We work through the mental model of the ReAct loop (building intuition around Thought → Action → Observation), map out Anthropic's five workflow patterns from "Building Effective Agents," and compare the Tool Use protocol format across providers. By the end, you'll have a clear grasp of the essential difference between an agent and a chatbot: it's not that the model is smarter — **the architecture simply has one extra feedback loop**.

Along the way we'll hit a detail that trips up a lot of people: why does the `role` field on a tool result message say `"user"` instead of `"tool"`? That gets answered in the protocol section.

Lena upgrades from v0.1 to v0.2 in this chapter — the code file is unchanged, but your understanding of it will have made a leap. The main deliverable here is a **hand-drawn state machine diagram** that becomes the blueprint for the next chapter's code.

> **🧠 Intelligence increment (v0.1 → v0.2):** Lena gains the mental architecture for autonomous reasoning. After understanding the ReAct loop (Thought → Action → Observation), she is no longer a one-shot Q&A machine — she is an agent that can independently decide when to call a tool and when to stop. This chapter teaches you how to internalize the ReAct loop into your own agent.

![ReAct loop architecture](diagrams/react-loop.svg)

---

## Beat 2 — Motivation: Why Chatbots Aren't Enough

Imagine a concrete task: you want Lena to "clean up log files in the project directory that haven't been modified in three months."

What would `lena-v0.1` from Ch 01 say?

```
You:  Clean up log files in the project directory that haven't been modified in three months
Lena: Sure, you can use this command:
      find /path/to/logs -name "*.log" -mtime +90 -delete
      Note: back up your files before running this…
```

It gave you a command. The task isn't done — you still have to run it yourself.

This isn't about the model being insufficiently smart. Swap in GPT-4o, Claude Opus, or Gemini 1.5 Pro and the response will be more detailed, but the structure is the same: **give advice, don't act**. The root cause is structural: a single API call lacks the "execute → observe → reason again" feedback loop.

Let's put a number on that gap. Yao et al.'s ReAct paper (ICLR 2023, arXiv: 2210.03629) ran comparisons on two task types: on HotpotQA multi-hop QA, ReAct significantly outperformed pure CoT and fixed the hallucination problem that chain-of-thought reasoning tends to suffer from; on ALFWorld decision-making tasks, ReAct beat the imitation learning baseline by **34 percentage points** in absolute success rate.

Thirty-four percentage points isn't a marginal gain — it's a structural leap. The reason is simple: multi-step reasoning tasks require intermediate state, and that intermediate state has to come from real external feedback. You can't get it by having the model "imagine" it internally.

That's the core question this chapter answers: what exactly is that "real external feedback" loop?

---

## Beat 3 — Theory

### 3.1 Three Nodes: Starting from Intuition {#three-nodes}

In 2022, researchers at Princeton and Google Research published the paper [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) (arXiv: 2210.03629). You don't need to read the whole thing — just take away the core finding:

> **Interleaving Reasoning and Acting within the same LLM call flow outperforms either pure reasoning or pure acting.**

"Interleaving" is the key word. Not finishing all the reasoning first and then acting, and not acting randomly and reasoning afterward — but reasoning immediately before each action and observing immediately after, with each observation becoming the starting point of the next reasoning step. This "Thought → Action → Observation → Thought → …" chain is the ReAct loop.

It has three nodes, and the intuition is straightforward:

**Thought (Reasoning):** The LLM's "inner monologue." It surveys the current state and works out what to do next. For example: "The user wants to delete log files not modified in three months. I need to know which files qualify — I should list them first."

**Action:** The LLM issues a tool call request. For example: "Run `find /logs -mtime +90 -name '*.log'`." Note that at this step the LLM is only *requesting* execution — it cannot run code itself. The tool call is an instruction dispatched to an external executor.

**Observation:** After the tool actually executes, the result is returned to the LLM. For example: "Found 3 files: access.log.2024-01, error.log.2024-01, debug.log.2024-01." This is **real-world feedback**, not something the LLM guessed.

Convention: Thought = the LLM's text reasoning output (inner monologue); Action = the tool call request the LLM emits (not yet executed); Observation = the result returned after the tool actually runs (real data). These three terms are used consistently throughout.

The three nodes form a loop. At the end of each iteration, the Observation is appended to the conversation history, so the LLM can see it when constructing the next Thought. The loop runs until the LLM decides "task complete" and exits.

This is the essential difference between an agent and a chatbot: **a chatbot has no loop — every response is a one-shot inference; an agent has this loop — it can reason continuously based on real feedback until the task is done.**

### 3.2 The messages Array: A Ledger View {#messages-ledger}

Another way to understand ReAct is to think of the messages array as a **ledger**. Each iteration of the loop adds a few new entries:

```
[initial]
  user: "Clean up log files not modified in three months"

[after round 1 Thought + Action]
  assistant: [Thought text] + [Action: find command request]

[after round 1 Observation]
  user: [tool_result: found 3 files]

[after round 2 Thought + Action]
  assistant: [Thought: confirm these 3 files can be deleted] + [Action: rm command request]

[after round 2 Observation]
  user: [tool_result: deletion successful]

[after round 3 Final Thought]
  assistant: [Final: cleaned up 3 log files]
```

This ledger has two important properties:

**First, the ledger is the LLM's only input for each reasoning step.** The LLM has no "memory" — it can only see the contents of the messages array. Each loop's Observation is appended to the ledger and becomes the foundation for the next round of reasoning. The longer the ledger, the fuller the context the LLM has.

**Second, Observations cannot be fabricated.** The `tool_result` entries in the ledger come from real tool execution — not generated by the LLM itself. This is the fundamental reason ReAct is more reliable than "pure reasoning (where the LLM pretends to execute tools and makes up the results)": every reasoning step is anchored to real-world feedback.

A natural question follows: what does this ledger look like in the Anthropic API? Why is the `role` of `tool_result` set to `"user"` rather than `"tool"`? That's answered below in the protocol section.

---

## Beat 4 — Scaffold: The Minimal ReAct Loop Skeleton

Before looking at any code, turn the mental model into pseudocode. An effective ReAct loop only needs these steps:

```
1. Add user message to the messages ledger
2. Loop begins:
   a. Call LLM with current messages → get Thought + (optional) Action
   b. If no Action → this is the final response, exit loop
   c. If there is an Action → execute the tool, get Observation
   d. Append Observation to the messages ledger
   e. Go back to step 2a
```

That's the entire ReAct. Five steps. Now let's see what the minimal Python implementation looks like.

Let's verify the core loop by tracing through the minimal Python structure that every real agent is built on:

```python
# Minimal ReAct loop skeleton (no real tools yet — structure only)
# Source: skeleton extracted from build-your-own-openclaw/01-tools teaching example

def agent_loop(client, messages: list, tools: list, max_steps: int = 10) -> str:
    """
    Minimal form of the ReAct loop.

    Args:
        client      - Anthropic API client
        messages    - initial message list (containing user input)
        tools       - list of available tool definitions
        max_steps   - maximum number of loop iterations (prevents infinite loops, default 10)
    Returns:
        final text response
    """
    for step in range(max_steps):
        # Thought: call LLM, get reasoning and (possibly) a tool call request
        response = client.messages.create(
            model="claude-sonnet-4-6",  # 2026 Claude 4.X series (2024 versions deprecated)
            max_tokens=1024,
            tools=tools,
            messages=messages,
        )

        # Append assistant reply to the ledger
        messages.append({"role": "assistant", "content": response.content})

        # Exit condition: no tool call = task complete
        if response.stop_reason == "end_turn":
            # Extract final text response
            for block in response.content:
                if block.type == "text":
                    return block.text
            return ""

        # Action + Observation: execute all tool calls, collect results
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute_tool(block.name, block.input)   # real tool execution
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        # Append Observation to the ledger, start next iteration
        messages.append({"role": "user", "content": tool_results})

    return "Max steps reached, task incomplete"
```

Expected output: calling `agent_loop()` with a tool (e.g., `get_time`) should produce a loop that runs 1–2 steps and then outputs a natural language response. If the tool returns an error, the LLM will reason about the error message in the next Thought — that is also part of the Observation.

Two details worth noting:

1. **`stop_reason == "end_turn"` is the exit condition**, not `stop_reason == "tool_use"`. The Anthropic API uses `stop_reason` to tell you "why generation stopped": `"tool_use"` means the LLM wants to call a tool (loop continues), `"end_turn"` means the LLM considers the task done or needs no tool (loop exits).

2. **The Observation's `role` is `"user"`, not `"tool"`**. This is Anthropic's design — from the API's perspective, tool results are wrapped inside a user message (the `content` array holds a block with `type: "tool_result"`). OpenAI's design differs: it uses `role: "tool"`. This difference is detailed in the protocol comparison below.

---

## Beat 5 — Incremental Assembly: From Skeleton to a Runnable Loop

We have the skeleton. Now let's add the features a real system needs — one at a time.

| Extension | Why it's needed | How to add it |
|-----------|----------------|---------------|
| Real tool registration and execution | `execute_tool()` in the skeleton is a placeholder; needs to map tool names to actual functions | Use a dict `tool_registry = {"get_time": fn_get_time}` for dispatch |
| max_steps guard | Infinite loops are a common source of production incidents — if tools keep erroring, the LLM can fall into a "error → retry → error" cycle | `for step in range(max_steps)` hard cap; return an error description on overflow |
| Tool execution error catching | Tools can throw exceptions (network timeout / permission error / bad args); the error must be returned as an Observation | Wrap tool calls in `try/except`; write error messages into `tool_result.content` |
| stop_reason assertion | Defensive programming: if an unknown `stop_reason` appears, catch it early rather than silently passing | `assert response.stop_reason in ("end_turn", "tool_use")` |

Let's add these features one by one and verify after each:

**Extension 1: Wire up real tools**

```python
import datetime

# Tool registry: name → implementation function
TOOL_REGISTRY = {
    "get_current_time": lambda args: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "calculate": lambda args: str(eval(args.get("expression", "0"))),  # demo only — never use eval in production
}

# Tool definitions (JSON Schema sent to the LLM)
TOOLS = [
    {
        "name": "get_current_time",
        "description": "Returns the current local time in YYYY-MM-DD HH:MM:SS format",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "calculate",
        "description": "Evaluate a math expression",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression to evaluate, e.g. '2 + 3 * 4'"}
            },
            "required": ["expression"],
        },
    },
]

def execute_tool(name: str, args: dict) -> str:
    """Tool dispatch: name → implementation function"""
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return f"Error: unknown tool '{name}'"
    try:
        return fn(args)
    except Exception as exc:
        return f"Tool execution failed: {exc}"
```

After running this, `execute_tool("get_current_time", {})` should output something like `"2026-05-05 14:32:01"`. If you see that, the tool layer is in place.

**Extension 2: Complete loop (skeleton + tool registry merged)**

```python
import anthropic

def run_agent(user_input: str) -> str:
    """Full ReAct loop with tool execution and error handling"""
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": user_input}]

    for step in range(10):  # max_steps = 10
        response = client.messages.create(
            model="claude-sonnet-4-6",  # 2026 Claude 4.X series (2024 versions deprecated)
            max_tokens=1024,
            tools=TOOLS,
            messages=messages,
        )

        # Append assistant reply to the ledger
        messages.append({"role": "assistant", "content": response.content})

        # Print current step status (for debugging)
        print(f"[Step {step+1}] stop_reason={response.stop_reason}, "
              f"blocks={[b.type for b in response.content]}")

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return ""

        # Execute all tool calls, collect Observations
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute_tool(block.name, block.input)
                print(f"  → {block.name}({block.input}) = {result[:80]}")  # intermediate result
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "user", "content": tool_results})

    return "Max steps reached"
```

Run it and observe the intermediate output:

```python
result = run_agent("What time is it? Also, what is 137 * 256?")
print("\nFinal answer:", result)
```

Expected output:

```
[Step 1] stop_reason=tool_use, blocks=['text', 'tool_use', 'tool_use']
  → get_current_time({}) = 2026-05-05 14:32:01
  → calculate({'expression': '137 * 256'}) = 35072
[Step 2] stop_reason=end_turn, blocks=['text']

Final answer: It's currently 2026-05-05 14:32:01. 137 × 256 = 35,072.
```

Two steps, two tools called in parallel (parallel Actions). This is a real ReAct loop.

---

## Beat 5.5 — Wire-Level Trace: A Full messages Array Snapshot

The print output above only shows a summary. But what truly turns the ReAct loop from a "concept" into a "debuggable system" is the ability to see the **complete JSON state of the messages array after every loop iteration**. This is the only reliable source of evidence when hunting down agent bugs.

Below is the full evolution of the messages array when running `run_agent("What time is it? And what's 137 * 256?")`:

**Initial state (after user input):**

```json
[
  {
    "role": "user",
    "content": "What time is it? And what's 137 * 256?"
  }
]
```

**Round 1: after the LLM returns Thought + Action, the assistant message is appended:**

```json
[
  {                                              // ← msg[0] user input
    "role": "user",
    "content": "What time is it? And what's 137 * 256?"
  },
  {                                              // ← msg[1] assistant: Thought + Action
    "role": "assistant",
    "content": [
      {
        "type": "text",                          // Thought (inner monologue)
        "text": "Let me look up the time and calculate that for you."
      },
      {
        "type": "tool_use",                      // Action ①
        "id": "toolu_01A2B3C4D5",               // ← remember this ID ⬇
        "name": "get_current_time",
        "input": {}
      },
      {
        "type": "tool_use",                      // Action ②
        "id": "toolu_01E6F7G8H9",               // ← remember this ID ⬇
        "name": "calculate",
        "input": {"expression": "137 * 256"}
      }
    ]
  }
]
```

Notice that `content` is an **array** — one text block (Thought) plus two tool_use blocks (parallel Actions). This is a feature of the Anthropic API: a single assistant reply can request multiple tool calls simultaneously.

**Round 1: after tool execution, the Observation is appended (user message):**

```json
[
  {"role": "user", "content": "..."},            // msg[0]
  {"role": "assistant", "content": [...]},       // msg[1]
  {                                              // ← msg[2] Observation
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_01A2B3C4D5",      // ← paired with msg[1] Action ① ⬆
        "content": "2026-05-08 14:32:01"
      },
      {
        "type": "tool_result",
        "tool_use_id": "toolu_01E6F7G8H9",      // ← paired with msg[1] Action ② ⬆
        "content": "35072"
      }
    ]
  }
]
```

Both `tool_result` blocks go into the same user message — **each tool_result is paired with its corresponding tool_use via `tool_use_id`**. Order doesn't matter; ID matching is what counts. The arrows help you trace the pairings: each ⬇ has a corresponding ⬆.

**Round 2: after the LLM sees the Observation and generates the final response:**

```json
[
  {"role": "user", "content": "What time is it? And what's 137 * 256?"},
  {"role": "assistant", "content": [{"type": "text", ...}, {"type": "tool_use", ...}, {"type": "tool_use", ...}]},
  {"role": "user", "content": [{"type": "tool_result", ...}, {"type": "tool_result", ...}]},
  {
    "role": "assistant",
    "content": [
      {
        "type": "text",
        "text": "It's currently 2026-05-08 14:32:01. 137 × 256 = 35,072."
      }
    ]
  }
]
```

Final state: 4 messages, `stop_reason = "end_turn"`, loop exits.

**You can add `print(json.dumps(messages, indent=2, default=str))` to your own code to print a full trace.** When agent behavior goes wrong ("Why is it calling the same tool repeatedly?" "Why isn't it seeing the tool result?"), the answer is always in the messages array.

### Three Checkpoints for Reading a Trace

When you have a messages trace in hand, check in order:

1. **user/assistant alternation rule:** The Anthropic API requires messages to strictly alternate between user and assistant. Two adjacent `assistant` messages will cause a 400 error. This is one of the most common bug sources — if your code skips `messages.append({"role": "user", ...})` in some branch, this error will fire.

2. **tool_use_id pairing completeness:** Every ID produced by a `tool_use` block must have exactly one corresponding `tool_result` referencing it. One missing → API error; one extra → API error; wrong ID → API error. The error messages for all three are not very intuitive, but the root cause is the same: the pairing is broken.

3. **content type consistency:** An `assistant`'s `content` is an array (list of blocks); a `user`'s `content` can be a string or an array. When a user message contains `tool_result`, it must use the array format. If you send the tool output as a plain string `"content": "tool result"`, the API won't error, but the LLM won't treat it as a tool result — it will read it as ordinary user text.

---

## Beat 5.6 — Debugging Exercise: Find the Bug in Each of These Three Snippets

By now you have strong intuitions about the ReAct loop's data structures. Below are three code snippets, each containing one bug. Try to find them before reading the answers.

**Bug 1: Infinite loop**

```python
def agent_loop(client, messages, tools):
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1024,
            tools=tools, messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        for block in response.content:
            if block.type == "tool_use":
                result = execute_tool(block.name, block.input)
                messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": block.id, "content": result}]
                })

        # What's wrong here?
```

<details>
<summary>Answer</summary>

There is no exit condition. When `response.stop_reason == "end_turn"`, the code should `return`. Without an exit, even when the LLM considers the task complete (and stops requesting tools), the loop continues — it either sends an empty user message or feeds the assistant response back to the API, causing an infinite loop or an API error.

Fix: immediately after `messages.append(...)`, check `if response.stop_reason == "end_turn": return extract_text(response)`.

</details>

**Bug 2: API 400 error "messages must alternate"**

```python
for block in response.content:
    if block.type == "tool_use":
        result = execute_tool(block.name, block.input)
        messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": block.id, "content": result}]
        })
```

<details>
<summary>Answer</summary>

If one response contains 2 `tool_use` blocks (parallel tool calls), this code appends **2** user messages — violating the user/assistant alternation rule. The correct approach is to collect all tool results into one list and append them as a **single** user message:

```python
tool_results = []
for block in response.content:
    if block.type == "tool_use":
        result = execute_tool(block.name, block.input)
        tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
if tool_results:
    messages.append({"role": "user", "content": tool_results})
```

</details>

**Bug 3: Tool returns a result but the LLM can't see it**

```python
result = execute_tool(block.name, block.input)
messages.append({
    "role": "user",
    "content": f"Result from tool {block.name}: {result}"
})
```

<details>
<summary>Answer</summary>

`content` uses a plain string instead of the `tool_result` format. The LLM will treat it as an ordinary user message and cannot pair it with the prior `tool_use`. The API will error: "missing tool_result for tool_use_id xxx". You must use `{"type": "tool_result", "tool_use_id": block.id, "content": result}` format.

</details>

If you got all three right, you already understand the underlying communication protocol of ReAct better than 90% of agent developers. If not — go back to Beat 5.5 and walk through the JSON snapshot again, field by field.

---

## Beat 6 — Running Verification: From Loop to Production-Grade Code

Let's see what this loop looks like in real production code.

Compare two existing implementations — one for teaching, one for production:

**Teaching-grade (`build-your-own-openclaw` 01-tools example)**

```python
# Core loop (source: build-your-own-openclaw/01-tools/src/mybot/core/agent.py)
async def chat(self, message: str) -> str:
    self.state.add_message({"role": "user", "content": message})
    tool_schemas = self.tools.get_tool_schemas()

    while True:                                          # ReAct loop body
        messages = self.state.build_messages()
        content, tool_calls = await self.agent.llm.chat(messages, tool_schemas)

        self.state.add_message({"role": "assistant", "content": content,
                                 "tool_calls": [...]})   # Thought + Action into ledger

        if not tool_calls:
            break                                        # exit: no tool calls

        await self._handle_tool_calls(tool_calls)       # Observation into ledger

    return content
```

**Production-grade (mini-coding-agent core loop, ~40 lines)**

The production implementation adds three layers of defense: step counting (`tool_steps < self.max_steps`), attempt cap (`attempts < max_attempts`), and retry logic for malformed model output. The skeleton is identical — the extra layers are just protection.

```python
# mini_coding_agent.py MiniAgent.ask() ReAct core (simplified)
while tool_steps < self.max_steps and attempts < max_attempts:
    attempts += 1
    raw = self.model_client.complete(self.prompt(user_message), self.max_new_tokens)
    kind, payload = self.parse(raw)        # parse Thought

    if kind == "tool":
        tool_steps += 1
        result = self.run_tool(payload["name"], payload["args"])  # Action + Observation
        self.record({"role": "tool", "name": ..., "content": result})
        continue                            # back to loop head

    if kind == "final":
        return (payload or raw).strip()    # exit: got final response
```

The shared skeleton across both: `while` → call model → if tool, execute and continue → if no tool, return. Those six pseudocode lines scale from a 40-line teaching script to a production codebase of several hundred lines, but the structure never changes.

**Verification:** use the code in this chapter's `code/lena-v0.2/` directory and run:

```bash
pip install anthropic
python lena_v02.py "What time is it?"
```

Expected output (within 2–3 seconds):

```
[Step 1] stop_reason=tool_use
  → get_current_time() = 2026-05-05 14:32:01
[Step 2] stop_reason=end_turn
It's 2:32 PM.
```

If you see `AuthenticationError`, check whether the environment variable `ANTHROPIC_API_KEY` is set. If the loop keeps running, check whether `max_steps` has an upper bound.

---

At this point you understand the essence of the ReAct loop. The next key question: what are the format differences between Anthropic and OpenAI for tool call messages? This is essential protocol knowledge for building cross-provider agents.

### Tool Use Protocol: Anthropic vs OpenAI Format Comparison

All major LLM providers support tool calling, but the formats differ significantly. Rather than listing parameters one by one, let's focus on the **four key points** that actually bite you in practice.

**Key point 1: tool definition field names differ**

Anthropic uses `input_schema`; OpenAI uses `function.parameters`. But the contents of both are JSON Schema.

```json
// Anthropic tool definition
{"name": "get_weather", "input_schema": {"type": "object", ...}}

// OpenAI tool definition
{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object", ...}}}
```

**Key point 2: tool call arguments — one is an object, the other is a string**

This is the most common trap. Anthropic's `input` is a structured JSON object you can use directly. OpenAI's `arguments` is a **stringified JSON** that you must `json.loads()` before using:

```python
# Anthropic — use directly
args = tool_use_block.input          # already a dict: {"city": "Shenzhen"}

# OpenAI — needs parsing
args = json.loads(tool_call.function.arguments)  # string → dict
```

If you forget `json.loads()`, you get the string `'{"city": "Shenzhen"}'` instead of `{"city": "Shenzhen"}`, and the subsequent `args["city"]` will error — in a way that looks baffling in the logs.

**Key point 3: tool result role differs — this also answers "why is it user?"**

```json
// Anthropic: tool results go inside a user message
{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "...", "content": "result"}]}

// OpenAI: tool results are an independent "tool" role message
{"role": "tool", "tool_call_id": "...", "content": "result"}
```

Anthropic chose to put tool results inside `user` messages because, by design, a tool result is "feedback from the user (environment) to the LLM" — on the same side as user messages. This design decision has an internal logic to it; it is not a typo.

**Key point 4: the structure of assistant messages differs**

Anthropic's assistant `content` is an **array** that can contain both text and tool calls simultaneously. OpenAI's assistant `content` is a string (or null), with tool calls in a separate `tool_calls` array. This affects how you structure your response-parsing code.

Convention: `tool_use_id` (Anthropic) and `tool_call_id` (OpenAI) have different field names but the same function — pairing a tool result with its corresponding tool call request.

If you're building an agent that supports multiple APIs, the cleanest approach is to normalize these differences in a Provider abstraction layer, so the ReAct loop code above it is completely unaware of which API is in use. This is exactly the pattern that the `build-your-own-openclaw` teaching example demonstrates in `01-tools` — `BaseTool.get_tool_schema()` outputs a unified format, and the Provider layer translates it to each vendor's format.

### Anthropic Building Effective Agents: Five Workflow Patterns

Having understood the ReAct loop, a natural question follows: how complex do real agent systems get? When do you need ReAct, and when is a simple prompt enough?

Anthropic's December 2024 article [Building Effective Agents](https://www.anthropic.com/news/building-effective-agents) provides a clear classification framework, organizing agent system architectures into five workflow patterns in order of increasing complexity:

```
1. Augmented LLM         LLM + retrieval/tools/memory (single-step augmentation, no loop)
       ↓ need multiple steps?
2. Prompt Chaining       fixed sequence of steps, each output is the next step's input
       ↓ need conditional branching?
3. Routing               LLM classifier selects processing path
       ↓ need parallelism?
4. Parallelization       sub-tasks execute in parallel, aggregate multi-stream results
       ↓ need autonomous decomposition?
5. Orchestrator-Workers  a controller LLM autonomously decomposes tasks, sub-agents execute
```

Anthropic lays down a guiding principle in the same article:

> Anthropic's *Building Effective Agents* (2024-12-19) advises: avoid agents when you can — most scenarios are well served by a single LLM call; if you genuinely need an agent, choose the simplest architecture that solves the problem.

The operational implication: if a problem can be solved with Prompt Chaining (a pipeline of fixed steps), don't use a ReAct loop. If it can be solved with Routing (classify input, take different paths), don't use Parallelization. Every step up doubles complexity and halves debuggability.

**The relationship between ReAct and the five patterns:** ReAct is the underlying mechanism of the Orchestrator-Workers pattern (the most complex tier). When you implement an Orchestrator controller agent, the internal loop it uses to decompose and dispatch tasks is ReAct. The five patterns are combinations and extensions of the loop at the system architecture level.

---

## Beat 7 — Design Note: Why Not Plan-and-Execute?

> *(Sidebar · ~350 words)*

**Plan-and-Execute** is another agent architecture: first have the LLM generate a complete step list (Plan), then execute each step in order (Execute), without modifying the plan mid-way. At first glance this seems "more organized" than ReAct — after all, we usually plan before acting. So why do mainstream frameworks almost universally default to ReAct rather than Plan-and-Execute?

**The core problem: a plan is a set of assumptions about the future, and the future is unpredictable.**

Take "clean up log files not modified in three months." Plan-and-Execute might generate:

```
Step 1: List all files under /var/log
Step 2: Filter for files modified more than 90 days ago
Step 3: Delete these files
```

At execution time: Step 1 reveals `/var/log` has subdirectories and some files require root access; Step 2 reveals that certain "log files" are actually important audit logs that shouldn't be deleted — but Step 3's instruction is already locked as "delete."

Plan-and-Execute locks all decisions when information is still incomplete. ReAct re-reasons at every Thought based on the Observation. Discovered an audit log? Change the decision right there in the Thought — don't delete it. Encountered a permission error? The next Thought requests sudo.

**When is Plan-and-Execute better than ReAct?**

Two situations:

1. **Steps are fully determined and predictable:** converting 100 CSV files to JSON — each file is processed the same way, no dynamic decisions needed. Plan-and-Execute is more efficient here (half the LLM calls, half the cost).

2. **Human approval workflows:** produce a Plan for a person to review and approve, then execute. Pausing a ReAct loop mid-execution to wait for human approval is more complex to engineer.

Summary: **ReAct suits exploratory, dynamic tasks; Plan-and-Execute suits structured, predictable tasks.** Most real agent tasks fall into the former, which is why ReAct became the default. More advanced architectures can combine both — a coarse-grained Plan with ReAct executing each step at fine granularity — but that's the subject of Ch 11 (Planning and Sub-agents).

This is also precisely the core advice Anthropic gives in *Building Effective Agents*: "Start with simple prompts, optimize them with comprehensive evaluation, and add multi-step agentic systems only when simpler solutions fall short." That's why Ch 1 had readers make just a single API call: if the simple approach is enough, don't use an agent. ReAct is the right next step only when the simple approach genuinely isn't sufficient.

Note: this analysis reflects mainstream practice as of early 2026. The field evolves rapidly — Plan-and-Execute variants (such as re-planning loops with feedback) are being adopted by more and more production systems, and the gap is narrowing.

---

## Beat 8 — Thought Experiment: When the ReAct Loop Goes Wrong

Before writing code, mentally "run" a few edge cases. These are abstract versions of real production incidents.

**Scenario 1: A tool always returns an error**

Suppose `get_current_time` always returns `"Error: timezone not set"` due to a misconfigured server timezone. What does the ReAct loop do?

After seeing the error in round one, the LLM will try a different approach in its Thought (e.g., ask the user to set the timezone manually, or try another tool). But if **there's only this one tool**, it may fall into a "retry → fail → retry" cycle — which is why `max_steps` isn't optional, it's **mandatory**.

Production lesson: agent loops without `max_steps` have burned hundreds of dollars of API fees in a single day — the model keeps retrying a failing tool, each retry consuming tokens.

**Scenario 2: The LLM hallucinates a nonexistent tool**

You've defined `get_current_time` and `calculate`, but the LLM returns `{"name": "search_web", "input": {"query": "..."}}` — a tool you never registered.

The `execute_tool()` in the skeleton code reaches `TOOL_REGISTRY.get(name)`, gets `None`, and returns `"Error: unknown tool 'search_web'"`. This error message becomes the Observation returned to the LLM, which typically responds in the next Thought by switching to an available tool or answering directly.

This is an elegant property of ReAct: **errors are also information.** Tool execution failures are fed back to the LLM as Observations, and the model can learn from them and adjust its strategy. This is far better than "program crashes."

**Scenario 3: The messages array grows without bound**

Each loop iteration appends 2 messages (assistant + user). A 50-step task produces 100+ messages. Most LLMs have a context window limit — exceed it and either the API errors or early messages get truncated, causing the LLM to "forget" earlier operations.

This is the core problem Ch 10 (Context Engineering) will solve. A preview of the solutions: message compression (summarize old messages), sliding window (keep only the most recent N turns), external memory (write history to files/databases, retrieve on demand). For now, just remember: messages array growth is an inherent cost of ReAct, and it requires a management strategy.

**Key insight:** ReAct's three engineering challenges — infinite loop risk (solved by max_steps), hallucinated tools (solved by error handling), context bloat (solved in Ch 10) — are not bugs. They are inherent characteristics of the architecture. A good agent system anticipates and manages them, rather than pretending they don't exist.

---

## Chapter Exercise: Draw Your Agent's State Machine Diagram

The main deliverable for this chapter is a hand-drawn state machine diagram. This diagram will be the design document for the next chapter's code.

**Step 1: Choose an agent scenario you want to build** (can be fictional)
- An agent that helps you organize email
- An agent that monitors server health
- An agent that answers questions about a codebase
- Any scenario you can think of

**Step 2: Draw the three-node diagram on paper**

Must include:
- Three nodes: Thought / Action / Observation
- Directed arrows between nodes (with labels: what triggers each transition)
- Two exit conditions: task complete (exits from Thought) / max steps exceeded (forced exit)

**Step 3: Annotate each node**

```
Thought:
  Input:  [messages ledger (user messages + Observation history) + tool list]
  Output: [reasoning text + optional tool call request]

Action:
  Input:  [tool name + tool args]
  Output: [tool execution result (real data, not guessed by LLM)]

Observation:
  Input:  [tool execution result]
  Output: [new entry appended to messages ledger]
```

**Step 4: Validate your diagram**

Ask yourself:
- If a tool call fails (network timeout / permission error), what is the Observation? (An error message — that's also real feedback.)
- If the task needs 20 steps but max_steps = 10, what happens? (Forced exit condition is triggered.)
- In what situation does Thought go directly to the final response without an Action? (The LLM judges the task is already complete, or the task doesn't require a tool.)

Once this diagram is drawn, it becomes the design document for Ch 03's code implementation.

---

## Validation Checkpoints

Three criteria to verify that you've truly understood this chapter:

1. **Explain ReAct in one sentence:** explain to someone without a technical background why an agent needs a "loop," and have them understand it.

2. **Find the ReAct in source code:** open the source of any agent framework, and within 30 seconds find the `while` loop, the tool call, and where the result is appended back into messages.

3. **Classify against Anthropic's five patterns:** pick an AI product you're familiar with (GitHub Copilot, Notion AI, any chatbot) and identify which pattern it roughly fits, and why.

If you can do all three, Ch 02 is truly complete.

---

*Now we have the mental model and protocol knowledge for ReAct. In the next chapter (Ch 03), we turn this blueprint into real running code — 50 lines of Python, Lena upgrades from v0.2 to v0.3, and for the first time she truly "does things" rather than just "answers."*

---

## Further Reading

| Resource | Description | Link |
|----------|-------------|------|
| ReAct original paper | Yao et al., 2022, arXiv 2210.03629 | https://arxiv.org/abs/2210.03629 |
| Anthropic Building Effective Agents | Authoritative source for the five workflow patterns (2024-12-19) | https://www.anthropic.com/news/building-effective-agents |
| Anthropic Tool Use documentation | Official format spec, `input_schema` field definition | https://docs.anthropic.com/en/docs/tool-use |
| HuggingFace Agents Course Unit 1 | Systematic coverage of Thought/Action/Observation | https://huggingface.co/learn/agents-course/en/unit1 |

---

---

Lena learned "why the loop" in this chapter — the Thought/Action/Observation three-beat rhythm upgrades her from "generating text" to "executing tasks." But the loop only lives on paper right now; we haven't written a single line of real code.

The next chapter does one thing: turn this state machine diagram into 50 lines of Python that actually run. You'll see what the smallest AgentLoop looks like, and watch for the first time as Lena uses a tool to look up the time, writes a reply, and waits for the next message. This is the first runnable agent artifact in the entire book. **In Chapter 3, we give Lena a skeleton.**

---

## Navigation

➡️ **[Ch 3. Lena Is Born](../ch03-lena-is-born/README-en.md)** — Turn the paper state machine into 50 lines of real, runnable code

[← Ch 1. Hello, Agent](../ch01-hello-agent/README.md) · [📘 Back to table of contents](../../README.md)
