# Chapter 11: Planning and Subagents — Teaching an Agent to Break Down Tasks

> **[Pillars: Planning + Long-horizon]**
> Lena v0.10 → v0.11

---

## Beat 1 — Roadmap

```
Ch01 → Ch02 → Ch03 → Ch04 → Ch05 → Ch06 → Ch07 → Ch08 → Ch09 → Ch10
→ [Ch11 ← you are here] → Ch12 → Ch13 → ...
```

This chapter starts with Lena v0.10 — a Lena that can use tools, has memory, and compresses context — and moves through three pivotal turns: ① the LLM autonomously decides "how many pieces to break this into," ② each piece is handed to an independent subagent running in parallel, and ③ results flow back as structured XML. The destination is Lena v0.11: give her "research X" and she automatically dispatches 3 Workers concurrently.

Along the way we'll hit a real pitfall: **the `agentId` isolation failure in TodoWrite** — when parent and child agents share a session key, the parent agent's todo list gets overwritten by a child. Understanding why the code uses `agentId ?? sessionId` here is the most important engineering detail in this chapter.

After this chapter, Lena gains two new capabilities: autonomous task planning and concurrent Worker dispatch.

> **🧠 Intelligence increment (v0.10 → v0.11)**: Lena can delegate for the first time — the LLM autonomously breaks large tasks apart, each subtask runs in an independent subagent concurrently, each holding its own context, so the main agent no longer carries all the cognitive load. This chapter teaches you how to build task distribution and concurrent orchestration into your own agent.

![Multi-Agent Three Topologies](diagrams/multiagent-topologies.svg)

---

## Beat 2 — Motivation

Let's start by looking at what happens without subagents.

```python
# lena-v0.10: sequential execution
start = time.time()
r1 = ask(lena, "Research LangGraph framework")   # ~3.2s
r2 = ask(lena, "Research CrewAI framework")      # ~3.8s
r3 = ask(lena, "Research AutoGen framework")     # ~4.1s
total = time.time() - start                      # ~11.1s

print(f"Total elapsed: {total:.1f}s")
# Output: Total elapsed: 11.1s
```

These three tasks are completely independent, and sequential execution wastes roughly 60% of the time. The deeper problem: **a single agent constantly switching between "LangGraph expert" → "CrewAI expert" → "AutoGen expert" produces lower quality output than three agents each focused on one thing.**

Same task with three Workers running concurrently:

```
[sub-001] Research LangGraph  ████████████ 3.2s ✓
[sub-002] Research CrewAI     ██████████████ 3.8s ✓
[sub-003] Research AutoGen    ████████████████ 4.1s ✓
                                 ↑ all three overlap, total ≈ 4.1s (slowest Worker)
```

Total time compresses to 4.1s, saving 63%. This isn't an optimization — it's an architectural shift.

---

## Beat 3 — Theory

### 3.1 The Hidden Assumption in ReAct

The ReAct loop established in Chapter 3 — Think → Action → Observation → Think → ... — has an assumption that was never challenged: **all reasoning happens in the same context, sequentially.**

That assumption is fine for single-threaded tasks. But it creates two ceilings:

**Time ceiling**: total elapsed time for N independent tasks = sum of each task's time. Concurrency compresses that sum to the maximum.

**Quality ceiling**: when a single agent switches tasks, residual information from the previous task lingers in context. Research LangGraph details, then research CrewAI, and LangGraph information is sitting there "polluting" the context, competing for attention.

Breaking through both ceilings requires a new pattern.

Convention: **Orchestrator** = the agent responsible for planning and scheduling (the brain); **Worker / Subagent** = the agent responsible for executing a single task (the hands). These two terms are used consistently from here on.

### 3.1b How Much Better Are Multi-Agent Systems Than Single Agents?

Anthropic's internal research data gives an impressive answer: on complex tasks, **multi-agent systems outperform single agents by 90.2%**.

> "The key insight is that intelligence reaches a threshold where multi-agent systems become a vital way to scale performance." (Source: Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*, 2025, p.14)

But that number comes with a precondition — the multi-agent architecture itself must be the right choice. The whitepaper also gives three primary multi-agent architecture variants and when each applies:

| Pattern | Core idea | When to use |
|---|---|---|
| **Hierarchical** | supervisor uses tool calling to invoke subagents | task decomposes into clear subtasks |
| **Collaborative** | peer-to-peer, no center, emergent coordination | exploratory / creative tasks |
| **Agentic Workflow** | predefined process (Sequential / Parallel) | predictable / fixed-step workflows |

The Orchestrator-Worker topology implemented in this chapter maps to **Hierarchical** — the Orchestrator is the supervisor, Workers are dispatched via tool calling. This is also the most common, most debuggable shape in practice.

The whitepaper also gives an important counter-recommendation to prevent over-engineering:

> "Before scaling to multi-agent systems, consider whether adding specialized skills to your single agent might achieve your accuracy requirements more efficiently."

In other words, before going multi-agent, ask: can adding better skills to a single agent (see Ch 12) hit the target? If yes, don't use multi-agent. The value of multi-agent is breaking through the single agent's time and quality ceilings, not "looking more sophisticated."

(Source: Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*, 2025, p.14–15)

### 3.1c Real-World Case: 16 Parallel Claudes Write 100K Lines of Compiler

Anthropic safety researcher Nicholas Carlini published an experiment in February 2026: **16 Claude Opus instances running in parallel**, using a minimal bash loop harness, wrote a C compiler in Rust from scratch — one that can compile the Linux kernel 6.9 (x86 / ARM / RISC-V), totaling **100,000 lines of code**, at a cost of roughly 2,000 Claude Code sessions / $20,000 in API costs.

```bash
# Carlini's harness core: just a while-true loop
while true; do
    claude --dangerously-skip-permissions \
           -p "$(cat AGENT_PROMPT.md)" \
           --model claude-opus-X-Y
done
```

Mutual exclusion via file locks (`current_tasks/xxx.txt`), isolation via Docker + bare git repo. Some agents specialized in code review and documentation rather than writing compiler code — that's specialization at work.

The experiment proved two things:
1. **Orchestrator-Worker actually works at engineering scale** — not just a toy demo
2. **The harness can be minimal** — no complex framework needed; a bash loop + file locks + Docker is enough

(Source: Anthropic Engineering Blog, *Building a C compiler with a team of parallel Claudes*, 2026-02-05)

### 3.2 Orchestrator-Worker Topology

```
User
 └─ Orchestrator (planning layer)
      ├─ Analyze task, identify independently concurrent subtasks
      ├─ Generate four-element Prompts for each subtask
      ├─ Dispatch to Workers concurrently (asyncio.gather)
      └─ Aggregate <task-notification> results
           ├─ Worker-1 (independent ask() chain, independent agentId)
           ├─ Worker-2 (independent ask() chain, independent agentId)
           └─ Worker-3 (independent ask() chain, independent agentId)
```

Anthropic's engineering blog describes this design as *decoupling the brain from the hands*: the Orchestrator focuses on decisions (using a stronger model), Workers focus on execution (using lighter models), each doing what it does best.

Key fact: **Workers are not threads — they are independent LLM call chains.** Each Worker has its own message history, its own agentId, its own tool permissions. They share no context.

### 3.3 The agentId Design in TodoWrite

CC's `TodoWriteTool.ts` is only 115 lines, but its core is a single line:

```
AppState.todos[agentId ?? sessionId] = newTodos  // :67
```

**Why `agentId ?? sessionId` instead of always using `sessionId`?**

If we always used `sessionId`: the Orchestrator and all Workers run under the same session, so they share one todo table. A Worker updating todos would overwrite the Orchestrator's todos — a race condition.

The semantics of `agentId ?? sessionId` are: use agentId if available (each Worker has its own todo table), fall back to sessionId if not (the top-level Orchestrator's todo table). Every Worker's todo state is completely isolated.

Convention: **agentId** = unique identifier for a Worker instance; **sessionId** = unique identifier for the entire conversation. The former is a subdomain of the latter.

---

## Beat 4 — Scaffold

Build the minimal Orchestrator skeleton — it does exactly one thing: feed tasks to three Workers and wait for results.

Let's verify the smallest Orchestrator that can dispatch three workers and collect their results:

```python
# orchestrator_skeleton.py — Beat 4 scaffold (~50 lines, just proves the core structure)
import asyncio
import uuid
from dataclasses import dataclass


@dataclass
class SubagentResult:
    agent_id: str          # corresponds to CC's context.agentId
    task: str
    content: str
    elapsed: float

    def to_xml(self) -> str:
        """Simulate CC's <task-notification> XML return format"""
        return (
            f'<task-notification agent_id="{self.agent_id}" status="completed">\n'
            f'{self.content}\n'
            f'</task-notification>'
        )


class SubagentWorker:
    """Minimal implementation of an independent ask() call chain"""

    def __init__(self, task: str, parent_system_prompt: str):
        self.agent_id = f"sub-{uuid.uuid4().hex[:6]}"  # globally unique
        self.task = task
        # Fork inheritance: Worker's system prompt = parent prompt (shares prompt cache)
        self.system_prompt = parent_system_prompt

    async def run(self) -> SubagentResult:
        import time
        start = time.time()
        # Scaffold phase: use echo instead of a real LLM call
        await asyncio.sleep(0.1)  # simulate network latency
        content = f"[{self.agent_id}] Completed task: {self.task}"
        return SubagentResult(self.agent_id, self.task, content, time.time() - start)


async def run_parallel(tasks: list[str], system_prompt: str) -> list[SubagentResult]:
    """Concurrent dispatch: asyncio.gather is the key"""
    workers = [SubagentWorker(t, system_prompt) for t in tasks]
    return list(await asyncio.gather(*[w.run() for w in workers]))


# Verify the scaffold
if __name__ == "__main__":
    results = asyncio.run(run_parallel(
        ["Research LangGraph", "Research CrewAI", "Research AutoGen"],
        system_prompt="You are a research Worker."
    ))
    for r in results:
        print(r.to_xml())
```

Running `python3 orchestrator_skeleton.py` should show three `<task-notification>` XML blocks, each with a unique `agent_id` in `sub-xxxxxx` format. That's the foundation of agentId isolation.

---

## Beat 5 — Incremental Assembly

Starting from the skeleton, add three features that a real system needs:

| Extension point | Why needed | How to add |
|--------|---------|--------|
| LLM planning (plan phase) | Number and content of Workers depends on the task, can't be hardcoded | Orchestrator makes one LLM call to analyze the task, outputs a JSON split plan |
| Four-element Prompt | Workers given vague instructions produce unstable quality | Each Worker receives a structured prompt with Scope/Goal/Constraints/Output fields |
| `<task-notification>` aggregation | Orchestrator needs a uniform format to consolidate results | Worker results serialized to XML, Orchestrator uses LLM to aggregate |

**Extension 1: LLM planning phase**

The Orchestrator shouldn't hardcode "split into three" — it should let the LLM decide.

```python
PLANNER_PROMPT = """Analyze the task and determine if it can be split into independent concurrent subtasks.
Output JSON (JSON only, no explanation):
{"can_parallelize": true/false, "subtasks": [{"id": "1", "task": "..."}]}"""

async def plan(task: str, client) -> dict:
    resp = await client.converse(
        system=PLANNER_PROMPT,
        user=f"Task: {task}",
        max_tokens=400,
    )
    # Parse LLM's JSON output
    import re, json
    m = re.search(r'\{.*\}', resp, re.DOTALL)
    return json.loads(m.group()) if m else {"can_parallelize": False, "subtasks": [{"id":"1","task":task}]}
```

Intermediate result check: feed `"Research LangGraph, CrewAI, and AutoGen and compare them"` into `plan()`. You should get `can_parallelize: true` and 3 subtasks. If you get `can_parallelize: false`, the planner prompt needs tuning — this is a real pitfall, not theory.

**Extension 2: Four-element Prompt injection**

The bare instruction `"Research LangGraph"` lets Workers improvise; output formats vary wildly and are hard to aggregate. The four-element framework enforces alignment:

```python
def make_worker_prompt(scope: str, goal: str, constraints: str, output_format: str) -> str:
    return f"""### Scope
{scope}

### Goal
{goal}

### Constraints
{constraints}

### Output Format
{output_format}"""
```

The **Output Format** field is critical: tell the Worker what format to return, and the Orchestrator's aggregation LLM can process results predictably.

Intermediate result check: print the four-element prompt and confirm that `Scope` only mentions the target framework, and `Constraints` has an explicit "do not access other frameworks" constraint.

**Extension 3: `<task-notification>` aggregation**

```python
async def aggregate(original_task: str, results: list[SubagentResult], client) -> str:
    # Concatenate all Workers' XML output
    notifications = "\n\n".join(r.to_xml() for r in results)
    return await client.converse(
        system="You are an information integrator. Consolidate multiple subagent results into a complete report.",
        user=f"Original task: {original_task}\n\nSubagent results:\n{notifications}",
        max_tokens=2000,
    )
```

Intermediate result check: print `notifications` and verify three `<task-notification>` XML blocks appear, each with a different `agent_id`, confirming agentId isolation is working correctly.

---

## Beat 6 — Run and Verify

Assembled as the complete artifact. Full code in `code/lena-v0.11/`, run like this with expected output:

```bash
# Requires AWS credentials (us-west-2, Bedrock access)
cd code/lena-v0.11
python3 lena.py
```

Expected interaction (numbers may vary ±20% depending on network):

```
Lena v0.11 — Orchestrator-Worker Mode
==================================================
> Research the three major AI Agent frameworks in 2026 (LangGraph/CrewAI/AutoGen) and compare them

[Orchestrator] Analyzing task...
[Orchestrator] Splitting into 3 independent subtasks

  [sub-4a2f1c] ⏳ Researching LangGraph...
  [sub-9b3e7d] ⏳ Researching CrewAI...
  [sub-2c8f4a] ⏳ Researching AutoGen...

  [sub-4a2f1c] ✓ Researching LangGraph... (3.2s)
  [sub-2c8f4a] ✓ Researching AutoGen... (4.0s)
  [sub-9b3e7d] ✓ Researching CrewAI... (4.5s)

[Orchestrator] Aggregating results... (total elapsed: 6.8s, estimated serial: 11.7s)
```

If you hit `botocore.exceptions.NoCredentialsError`: check `~/.aws/credentials` or the `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` environment variables.

If you hit `ModelNotReadyException`: the inference profile ID must be `us.anthropic.claude-haiku-4-5` (with `us.` prefix), not `anthropic.claude-haiku-4-5` — this is a hard-learned Bedrock pitfall; model ID and profile ID formats differ.

---

## Beat 7 — Design Note

**Why Not Persist the Todo List?**

The implementation in `TodoWriteTool.ts:67` surprises many people on first read: `AppState.todos` is a pure in-memory object with no I/O. When the process exits, all todos disappear.

Alternative: write todos to SQLite or a local JSON file, supporting cross-session recovery.

Tradeoff analysis:

- **Cost of persistent todos**: every `TodoWrite` triggers disk I/O, adding visible latency in a high-frequency agent loop (every few seconds); more critically, persistence means dealing with "leftover todos from the last session" — are they valid pending items or expired garbage? Requires TTL or manual cleanup logic, significantly raising complexity.

- **Philosophy of in-memory todos**: TodoWrite's use case is **the agent's working draft**, not a user-facing task management system. Its purpose is to let the LLM maintain short-term memory of current progress within a session, not to build a persistent task queue. Session ends → todos naturally cleared → next session starts fresh. This aligns with agent design intuition.

- **agentId isolation is the guarantee that makes in-memory design work**: precisely because todos only live in memory, the `agentId ?? sessionId` key design guarantees that concurrent Workers don't interfere with each other — no lock contention, no transaction requirements.

Current choice rationale: for short-term in-session task tracking, in-memory + agentId isolation is the simplest design, and it's sufficient.

If a production system needs cross-session recovery (like the long-running tasks in Chapter 14), the right approach is a lightweight checkpoint mechanism with TTL, not adding persistence to TodoWrite — two different concerns should stay separate.

---

## Lena v0.11 New Capabilities

| Capability | Description |
|------|------|
| Autonomous planning | Orchestrator calls LLM to analyze task parallelizability, outputs split plan |
| Concurrent dispatch | `asyncio.gather` launches N Workers concurrently, time compresses to the slowest Worker |
| agentId isolation | Each Worker has an independent `agent_id`, todo state doesn't interfere across Workers |
| Four-element Prompt | Scope/Goal/Constraints/Output structured Worker instructions for stable aggregation quality |
| XML return format | `<task-notification>` return format, Orchestrator aggregates uniformly |

---

## Further Reading

- CC source `AgentTool.tsx:196`, `forkSubagent.ts:60`, `TodoWriteTool.ts:67` — the primary sources for all CC details in this chapter
- `buildForkedMessages()` in `forkSubagent.ts`: how forking a subagent uses the same placeholder tool_result to let all Workers share the prompt cache prefix
- `builtInAgents.ts`: CC's four built-in agent types (generalPurpose / plan / explore / verification)

---

*Next chapter →* **Ch 12: Skills — Reusable Capability Units**

"Lena v0.11 can break down tasks now. But every subagent starts from scratch describing how to do things — what if we could inject pre-written 'skill packages' into them?"
