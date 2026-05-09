# Prologue: The Agent Intelligence Model — A Map for This Book

> **Lena's starting point**: v0.0 (blank) → By the end of this chapter, you'll have a coordinate system that runs through the entire book

---

## Beat 1 · Roadmap

```
Where you are: Prologue ← you are here
─────────────────────────────────────────────
[Prologue] Intelligence Map  →  [Ch1-5] Foundation
→  [Ch6-12] Six Pillars   →  [Ch13-18] Always-on + Safety
→  [Ch19-22] Extension & Production   →  [Ch23-24] Specialization
→  [Ch25] Epilogue: From General to Your Own Agent
─────────────────────────────────────────────
Chapter arc: starting from "a bot that just learned to call an API" →
through "8 quantifiable intelligence dimensions" →
arriving at "the 24-chapter unlock map," with one pitfall along the way:
discovering that most people think intelligence is a single metric,
when it's actually an eight-dimensional composite.
```

Lena finishes Ch1 knowing only how to print a model reply (v0.1). The mission of this book is to have her unlock 8 intelligence dimensions across 24 chapters and become a general-purpose agent capable of doing anything autonomously (v0.24).

But before we start building, we need a map. Without one, you'll reach Chapter 8 thinking you're doing "memory optimization," not realizing you're unlocking one of the hardest dimensions in the entire system. You'll reach Chapter 11 thinking you're writing "task decomposition," not realizing this is the watershed that upgrades Lena from "executor" to "planner."

With a map in hand, every chapter has direction.

---

## Beat 2 · Motivation

### What happens without an intelligence model?

Let's look at a concrete counterexample. In the second half of 2024, a flood of tutorials taught readers to "build your AI customer service agent in 5 minutes." The standard recipe: one system prompt + one tool (query orders) + a while loop.

What can this kind of agent accomplish? About 3 types of tasks: check order status, answer FAQs, transfer to a human agent.

What can it *not* do?

- **No memory**: Forgets everything after the conversation ends. If a user told it "I prefer concise replies" yesterday, they'll have to say it again today.
- **Can't break down tasks**: When a user says "process refunds for these three orders," it can only handle them one by one — no concurrent processing.
- **Can't run overnight**: A user submits a refund request at 1 AM that needs 2 hours to process. The agent has no concept of "waiting" — session timeout means it's gone.
- **No safety boundary**: A carefully crafted prompt can make it look up anyone else's order.
- **Can't evolve**: Three months later the company adds a new refund policy, and nobody knows what to update.

These aren't deficiencies in implementation details — they are **missing architectural dimensions**. An agent that only has "reasoning" capability is like a robot with only hands. It can execute instructions, but it can't plan, can't remember, can't learn, and can't operate safely in the real world.

Anthropic put it plainly in *Building Effective Agents* (2025):

> "Generative AI answers questions. AI agents solve problems."

Between answering questions and solving problems lies a chasm of intelligence dimensions. This book bridges that chasm.

---

## Beat 3 · Theory

### 3.1 What is agent "intelligence"? (Pure theory, no code)

Convention: **Intelligence** = the quantifiable combination of capabilities an agent demonstrates on open-ended tasks; **Capability** = a single, independently measurable behavioral dimension. Intelligence is composite; capabilities are components.

An agent's intelligence is not the model's intelligence — you can use the same Claude Sonnet to build a bot that "always replies in three words," or to build a general-purpose agent that autonomously executes tasks across days. The difference is entirely in the harness design (the outer runtime). This distinction matters enormously. This book teaches harness construction, not model training.

### 3.2 Eight independently measurable intelligence dimensions (Pure theory, no code)

The following 8 dimensions come from observing and abstracting a large number of agent systems. Each dimension has a **minimum observable behavior** — you can verify whether an agent has that dimension's capability with a single test case.

| Dimension | Definition | Minimum Observable Behavior |
|-----------|------------|------------------------------|
| **① Reasoning** | Make evidence-based decisions in multi-step tasks | Given an ambiguous instruction, asks the right clarifying questions instead of guessing |
| **② Memory** | Maintain context and knowledge across sessions | In the second conversation, recalls preferences agreed on in the first |
| **③ Planning** | Autonomously decompose large goals into executable sub-tasks | Given "help me prepare next week's presentation," breaks it into at least 4 concrete sub-steps |
| **④ Collaboration** | Delegate work to other agents and integrate results | Dispatches 3 sub-agents concurrently to query 3 data sources, then auto-summarizes |
| **⑤ Learning** | Update its own behavior through feedback and experience | After a user correction, error rate on the same type of task decreases next time |
| **⑥ Safety** | Proactively degrade or request human confirmation under uncertainty | Pauses and seeks confirmation when encountering irreversible operations (deleting files) |
| **⑦ Self-Awareness** | Monitor its own state and adjust execution strategy | When context approaches the limit, proactively compresses rather than crashing |
| **⑧ Extensibility** | Integrate new capabilities without modifying the core code | After adding a new tool, it's available in the next conversation without a restart |

Convention: **Dimension** = an independently measurable component of intelligence; **Pillar** = the teaching framework used to organize chapters in this book (Six Pillars). Multiple dimensions can map to the same pillar.

### 3.3 Intelligence is a composite effect, not a single metric (Pure theory, no code)

At first glance, agent intelligence looks like a single metric ("this agent is smarter than that one"), but it's actually more like an ecosystem — improvements in one dimension can trigger cascading improvements in others, and a deficit in one dimension can drag down the whole.

**Example**: Planning capability (③) needs Memory (②) as its foundation — without memory, an agent plans from scratch every time and can never accumulate experience like "this approach failed last time." Collaboration (④) needs Safety (⑥) as a constraint — without safety boundaries, multiple concurrent agents can interfere with each other and produce unpredictable side effects.

Internal Anthropic research confirms this: for complex tasks requiring simultaneous pursuit of multiple independent directions, multi-agent systems (Collaboration dimension ④) outperform single-agent systems by 90.2% (*Building Effective Agents*, p.14). But this gain **presupposes** that each sub-agent has sufficient Reasoning (①) and Safety (⑥) capability — otherwise multi-agent just means multiple copies of errors.

---

## Beat 4 · Scaffolding

Let's turn "intelligence self-evaluation" into runnable code with a minimal Python script:

```python
# code/evaluator.py — Intelligence self-evaluation framework (skeleton)
# Purpose: Score any agent across 8 intelligence dimensions
# Run: python3 evaluator.py
# Expected output: 8-dimensional 0-10 scores + a text radar chart

from dataclasses import dataclass, field
from typing import Callable

@dataclass
class DimensionTest:
    """Test specification for one intelligence dimension"""
    name: str          # Dimension name
    description: str   # Minimum observable behavior description
    score: int = 0     # 0-10, where 0 = completely absent

@dataclass 
class IntelligenceEval:
    """8-dimensional intelligence evaluator skeleton"""
    agent_name: str
    dimensions: list[DimensionTest] = field(default_factory=list)
    
    def add_dimension(self, name: str, desc: str, score: int = 0):
        self.dimensions.append(DimensionTest(name, desc, score))
    
    def total_score(self) -> float:
        if not self.dimensions:
            return 0.0
        return sum(d.score for d in self.dimensions) / len(self.dimensions)
    
    def report(self) -> str:
        lines = [f"\n=== {self.agent_name} Intelligence Evaluation ==="]
        for d in self.dimensions:
            bar = "█" * d.score + "░" * (10 - d.score)
            lines.append(f"  {d.name:12s} [{bar}] {d.score}/10")
        lines.append(f"\n  Overall score: {self.total_score():.1f}/10")
        return "\n".join(lines)

# Run the skeleton
if __name__ == "__main__":
    eval = IntelligenceEval("Lena v0.1")
    # Beat 5 will fill in the actual scoring logic
    print(eval.report())
```

Run `python3 evaluator.py` and you'll see an empty report for "Lena v0.1." That's expected — we haven't filled in the scoring logic yet. We'll build it up incrementally from here.

---

## Beat 5 · Progressive Assembly

### Scoring v0.1 Lena

Let's translate the minimum observable behaviors for each of the 8 dimensions into concrete tests, and use them to evaluate a v0.1 Lena (can only call an LLM API, remembers nothing, has no tools):

| Extension point | Why it's needed | How to add it |
|-----------------|-----------------|---------------|
| Initialize 8 dimensions | Establish the evaluation baseline | Pre-populate 8 dimensions in `IntelligenceEval.__init__` |
| v0.1 scoring logic | Verify "how weak an initial agent is" | Manually assign scores based on v0.1 capabilities |
| Text radar chart | Turn numbers into intuition | Render with ASCII bar chart |

```python
# code/evaluator.py — Complete version (with v0.1 scoring)

def build_v01_eval() -> IntelligenceEval:
    """v0.1 Lena: only LLM API calls, no tools, no memory"""
    ev = IntelligenceEval("Lena v0.1 (API calls only)")
    
    # Score per dimension + rationale
    ev.add_dimension("① Reasoning",     "Multi-step decision-making",        score=2)
    # Score 2: the model itself has reasoning ability, but the harness doesn't
    # amplify it; relies on LLM's intrinsic capability without structural support
    
    ev.add_dimension("② Memory",        "Remember context across sessions",  score=0)
    # Score 0: no persistence whatsoever; each conversation starts from zero
    
    ev.add_dimension("③ Planning",      "Autonomously decompose goals",      score=1)
    # Score 1: the model occasionally says "first do A then do B," but no
    # explicit planning support; gets lost on anything moderately complex
    
    ev.add_dimension("④ Collaboration", "Delegate to sub-agents",            score=0)
    # Score 0: single-threaded, single-session; no sub-task delegation at all
    
    ev.add_dimension("⑤ Learning",      "Evolve from feedback",              score=0)
    # Score 0: no feedback collection or behavior update mechanism
    
    ev.add_dimension("⑥ Safety",        "Proactive degradation/confirmation",score=1)
    # Score 1: the model has a safety instinct, but the harness has no guards;
    # completely defenseless against prompt injection
    
    ev.add_dimension("⑦ Self-Awareness","Monitor its own state",             score=0)
    # Score 0: when context fills up, throws an API error instead of compressing
    
    ev.add_dimension("⑧ Extensibility", "Add capabilities without core edits",score=1)
    # Score 1: you can manually edit the code to add tools, but it's not
    # plugin-style "without modifying the core"
    
    return ev

if __name__ == "__main__":
    print(build_v01_eval().report())
```

Expected output (this is what you should see):

```
=== Lena v0.1 (API calls only) Intelligence Evaluation ===
  ① Reasoning   [██░░░░░░░░] 2/10
  ② Memory      [░░░░░░░░░░] 0/10
  ③ Planning    [█░░░░░░░░░] 1/10
  ④ Collaboration [░░░░░░░░░░] 0/10
  ⑤ Learning    [░░░░░░░░░░] 0/10
  ⑥ Safety      [█░░░░░░░░░] 1/10
  ⑦ Self-Awareness [░░░░░░░░░░] 0/10
  ⑧ Extensibility [█░░░░░░░░░] 1/10

  Overall score: 0.6/10
```

Overall: 0.6. That's the starting point, not the destination. The mission of 24 chapters is to systematically raise every dimension's score.

---

## Beat 6 · Run and Verify

### Expected output

```bash
$ python3 book/chapters/ch00-intelligence-map/code/evaluator.py
```

Expected output is the radar chart above. Each dimension scores 0-10; v0.1 total is 0.6/10.

If you see `SyntaxError`, check your Python version — Python 3.10+ is required (`dataclass` with `field(default_factory=...)` behaves most reliably on 3.10+).

**Failure diagnosis**: If all scores come out as 0, check whether you called `build_v01_eval()` instead of directly instantiating `IntelligenceEval()`.

You can re-run this script at the end of every chapter, updating the relevant dimension's score to the level Lena can reach after completing that chapter — it's the progress dashboard for this entire book.

---

![Lena Evolution Path](diagrams/lena-evolution.svg)

## The 24-Chapter Map: Which Dimension Each Chapter Unlocks

Below is the progress map that runs through the entire book. After each chapter, your score on the corresponding dimension will increase. The version number in parentheses is Lena's version at the end of that chapter.

| Chapter | Topic | Unlocked Dimension | Score Change |
|---------|-------|--------------------|--------------|
| Ch1 Hello, Agent | API call + first reply | — | Starting point |
| Ch2 ReAct Loop | Thought-Action-Observation | ① Reasoning | ①: 2→5 |
| Ch3 Lena Is Born | 50-line Agent + tool | ⑧ Extensibility | ⑧: 1→4 |
| Ch4 LLM Internals | Engineering intuition (methodology chapter) | — | Cognitive foundation |
| Ch5 Tech Selection | When to use Prompt/RAG/Agent | — | Decision framework |
| Ch6 Tool System | Any capability is a tool | ⑧ Extensibility | ⑧: 4→8 |
| Ch7 Streaming & Concurrency | SSE + concurrent tools | ① Reasoning | ①: 5→7 |
| Ch8 Memory & Context | Short-term + long-term memory | ② Memory | ②: 0→6 |
| Ch9 RAG & Vector Search | Reading external documents | ② Memory | ②: 6→8 |
| Ch10 Context Engineering | Token economics | ⑦ Self-Awareness | ⑦: 0→5 |
| Ch11 Planning & Subagents | Autonomous task decomposition | ③ Planning + ④ Collaboration | ③: 1→7, ④: 0→6 |
| Ch12 Skills | Reusable capability units | ⑤ Learning | ⑤: 0→5 |
| Ch13 Input-Layer Safety | Prompt Injection defense | ⑥ Safety | ⑥: 1→6 |
| Ch14 Execution-Layer Safety | Credentials + sandbox | ⑥ Safety | ⑥: 6→9 |
| Ch15 Gateway & Channel | Telegram + always-on | ⑧ Extensibility | ⑧: 8→9 |
| Ch16 MessageBus | Event-driven decoupling | ④ Collaboration | ④: 6→8 |
| Ch17 Heartbeat | Proactive outreach | ③ Planning | ③: 7→8 |
| Ch18 Cron & Long Tasks | Checkpointing across days | ③ Planning | ③: 8→9 |
| Ch19 MCP Protocol | Everything can connect | ⑧ Extensibility | ⑧: 9→10 |
| Ch20 Docker Sandbox | True sandbox execution | ⑥ Safety | ⑥: 9→10 |
| Ch21 Evals | How to know if the agent got better | ⑤ Learning | ⑤: 5→8 |
| Ch22 Observability & Deployment | Getting Lena into production | ⑦ Self-Awareness | ⑦: 5→9 |
| Ch23 Specialization | General → specialized | ⑤ Learning | ⑤: 8→9 |
| Ch24 Browser Agent | Final capstone | All dimensions — final validation | Overall ≥8 |
| Ch25 From General to Autonomous | Derive your own agent | — | Graduation |

After finishing Ch24, Lena v0.24's intelligence scores should look like this:

```
① Reasoning      [████████░░] 8/10
② Memory         [████████░░] 8/10
③ Planning       [█████████░] 9/10
④ Collaboration  [████████░░] 8/10
⑤ Learning       [█████████░] 9/10
⑥ Safety         [██████████] 10/10
⑦ Self-Awareness [█████████░] 9/10
⑧ Extensibility  [██████████] 10/10

Overall score: 8.9/10
```

From 0.6 to 8.9 — that's the journey this book will complete.

---

## Beat 7 · Design Note

> **Why Not a Single Score? — "This agent is a 9"**

Intuitively, giving an agent one total score ("Claude 4 is smarter than GPT-5") is far simpler than maintaining 8 dimensions. Benchmark leaderboards (MMLU, SWE-Bench) do exactly that — one number, clean and simple.

That approach is reasonable in benchmark settings, but in agent harness design it creates three specific dangers:

1. **It hides structural defects**: An agent that scores 10 on Reasoning and 1 on Safety may have a high overall score, but it's dangerous. An agent that scores 5 on Reasoning and 9 on Safety may score lower overall, but it's trustworthy in production. A total score conflates these two fundamentally different systems.

2. **It gives no guidance for improvement**: Knowing an agent is "6 out of 10" tells you nothing about which dimension to improve first. Knowing "Memory 0 / Planning 1" immediately tells you whether the next step is adding a memory mechanism or a planning mechanism.

3. **It distorts composite effects**: As described above, intelligence dimensions have strong dependencies. Improvements in Planning capability depend heavily on the Memory foundation, and improvements in Memory, in turn, make Reasoning more stable on long-horizon tasks. Summing scores erases this structure.

Anthropic's Skills system (*Complete Guide to Skills*, p.5) embodies exactly this thinking: instead of giving Claude a single "capability score," it uses three-level progressive disclosure (frontmatter / body / linked files) to break "skills" into independently activatable modules — each module corresponds to one capability dimension, and each can be observed, updated, and tested in isolation.

This book's 8-dimension framework draws on the same idea: **decomposing intelligence into independently evolvable dimensions is the shared foundation for both harness design and this book's pedagogy.**

---

**Next chapter**: Map in hand, time to drive in the first nail. Ch1 will have you running your first LLM API call in 20 minutes with 10 lines of Python — the moment Lena's life begins.
