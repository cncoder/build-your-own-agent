# Chapter 23: Specialization Pattern — One Runtime, N Specialized Agents

> **[Pillar: Specialization]**

---

## Beat 1 — Roadmap

```
Ch1  Ch2  Ch3  Ch4  Ch5  Ch6  Ch7  Ch8  Ch9  Ch10
 ●────●────●────●────●────●────●────●────●────●
Ch11 Ch12 Ch13 Ch14 Ch15 Ch16 Ch17 Ch18 Ch19 Ch20
 ●────●────●────●────●────●────●────●────●────●
Ch21 Ch22  ★Ch23★  Ch24
 ●────●────●────────●
         You are here
```

**This chapter's arc**: start from a general-purpose Lena that can deploy, observe, and run 24/7 (the Ch22 output) → understand how three specialization approaches work and their trade-offs → see multi-specialized-agent unified dispatch through Agent Squad's SupervisorAgent pattern → compare CrewAI's Crew and Flow orchestration paradigms → use TradingAgents' four-layer structure to understand the general skeleton of "role-play multi-agent" systems → finally run **Lena-SpecKit (lena-v0.23)** end-to-end: one command `python -m lena_speckit create trader` generates a complete specialized agent skeleton.

Along the way, you'll hit one gotcha: a "safety rule" written inside a system prompt can be bypassed by the LLM under certain boundary inputs. This isn't a bug — it's a structural limitation of LLMs. Understanding it tells you when rules belong in code, not in prompts.

**Lena version**: Ch22 ended at v0.22 (production-deployable). This chapter ends at **v0.23**, adding one new capability: *replicability* — one runtime, one command, N specialized agents.

> **Intelligence increment (v0.22 → v0.23)**: Lena can now spawn specialized versions of herself. Lena-SpecKit lets a single general-purpose runtime branch into quantitative trading / podcast / DevOps specialized agents with one command (`python -m lena_speckit create trader`), sharing safety guardrails and memory while only changing the system prompt and tool set. This chapter teaches you how to build the "general-to-specialized" forking pattern into your own agent architecture.

---

## Beat 2 — Motivation

Deploy Lena online for a week, and you'll get three types of requests.

Type 1: "I want an agent that only does quantitative trading — just price and indicators, nothing else."
Type 2: "Build me a podcast production agent that automatically collects, deduplicates, writes scripts, and synthesizes audio every morning."
Type 3: "Make a DevOps agent that watches AWS alerts and automatically executes remediation procedures."

The most intuitive approach: write a new agent from scratch for each need.

Let's count what that costs:

```python
# Actual cost of rewriting three agents from scratch
from_scratch_costs = {
    "agent_loop":        "3-4 days (rewrite the ReAct loop)",
    "tool_registry":     "2 days (rewrite tool registration)",
    "memory":            "2 days (rewrite the memory system)",
    "safety":            "3 days (rewrite safety guardrails)",
    "channel":           "2 days (re-integrate Telegram/Discord)",
    "deploy":            "1 day (rewrite systemd config)",
    "per_agent":         "13-15 days × 3 = 40+ days",
}
```

Forty days later you have three agents — but their memory implementations differ, each has its own safety gaps, and the deploy scripts exist in three incompatible versions. Three months later you change a fundamental tool-call convention and have to update three places.

This looks like a code reuse problem, and the obvious fix is inheritance. But it's actually more like **the relationship between an operating system and processes** — the OS is the immutable kernel; every process is a specialized program running on that kernel, sharing memory management, system calls, and the security model. You don't rewrite an OS for each process.

The Specialization Pattern applies this thinking: **the general-purpose Lena runtime is the kernel; specialized agents are processes running on it.** Write the kernel once; configure processes, don't rewrite them.

Without this pattern, building the first specialized agent costs 15 days. With Lena-SpecKit, it costs 15 minutes.

---

## Beat 3 — Theory

### 3.1 What Is "Specialization"?

The Specialization Pattern is already well-defined in agent engineering practice. Anthropic's *Building Effective Agents* (2024-12-19) describes this thinking as orchestrator-worker layering: the reasoning layer (LLM reasoning capability + memory system + ReAct loop) stays general-purpose; the execution layer (tool set + operating procedures) is swapped as needed — "universal brain, replaceable hands."

Convention: **runtime** = the agent's immutable kernel (LLM calls, tool execution framework, memory management, safety guardrails); **configuration layer** = the replaceable role definition (system prompt, tool set, skills). Specialization = keep the runtime unchanged, swap the configuration layer.

Understanding this distinction tells you what layer each of the three specialization approaches operates on:

```
┌─────────────────────────────────────────────┐
│              Runtime (unchanged)              │
│  LLM Provider · Tool execution · Memory      │
│  AgentLoop · Safety guardrails · Channel     │
├─────────────────────────────────────────────┤
│              Configuration layer (swappable) │
│  Approach ①  System Prompt (role, limits, style) │
│  Approach ②  Tool Profile (which tools are allowed) │
│  Approach ③  Skills (domain SOPs + procedures)    │
└─────────────────────────────────────────────┘
```

The three approaches aren't mutually exclusive — production-grade specialized agents typically stack all three. The difference: with 30 minutes, approach ① is enough; with half a day, stack ①②; to turn the agent into a genuine domain expert, you need approach ③.

### 3.2 SupervisorAgent: The Agent-as-Tools Pattern

Once you have multiple specialized agents, a second problem appears: which entry point does the user use?

Hardcoded routing ("if message contains 'trading' → TradingBot, if contains 'alert' → DevOpsBot") breaks because users don't speak in your designed keywords. "How's BTC doing" contains no "trading," yet it obviously belongs to TradingBot.

Agent Squad (`2FastLabs/agent-squad`, 8k stars) proposes the SupervisorAgent solution: wrap each specialized agent as a **tool**, and let a meta-agent with LLM reasoning capability make routing decisions.

Convention: **SupervisorAgent** = a meta-agent that treats other agents as tools, responsible for intent understanding and task delegation; **leaf agent** = a specialized agent wrapped as a tool, responsible for execution only, not for routing.

This pattern derives from OpenAI Agents SDK's "Handoffs" concept (2025) and Anthropic's *Building Effective Agents* (2024-12-19) orchestrator pattern — both are fundamentally the same idea: delegate the scheduling decision itself to the LLM rather than a rules engine.

### 3.3 CrewAI's Two Paradigms: Autonomous Collaboration vs. Event-Driven

Multi-agent orchestration comes in two fundamentally different philosophies.

**Crew (autonomous collaboration)**: define a group of agents and tasks, and let the framework automatically orchestrate based on task dependencies. Restaurant analogy: chef, waiter, and cashier each have a role; one order (task) triggers the entire service chain.

**Flow (event-driven)**: define a state machine where each agent's output is the trigger condition for the next. Assembly line analogy: sensor → quality inspector → packaging machine; each stage's output is the next stage's input; the entire line runs continuously.

Convention: **Crew** = role-collaboration for one-off tasks (project-based); **Flow** = state-machine orchestration for continuously-running systems (product-based).

The paper *Role-Play Prompting Elicits Complex Reasoning in Large Language Models* (Kong et al., 2023) validated a counterintuitive finding: giving an LLM an explicit role identity ("you are a quantitative analyst") improves accuracy by 9–12% on tasks requiring professional reasoning compared to generic instructions without a role. You don't need to read the entire paper — just know the core finding: **role prompts work. It's not superstition; it's experimentally verified.**

---

## Beat 4 — Scaffolding

Now let's build the Lena-SpecKit skeleton. It does one thing: given a role name and tool set, generate a complete specialized agent directory.

Let's implement the minimal SpecKit skeleton — just the `create` command, no templates yet:

```python
# lena_speckit/creator.py (30-line skeleton, handles only the minimal case)
import os
import json
from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class AgentSpec:
    """Complete specification for a specialized agent."""
    name: str                      # agent name, also used as directory name
    role: str                      # role description, injected into system prompt
    tools: list[str] = field(default_factory=list)  # list of allowed tools
    skills: list[str] = field(default_factory=list) # list of skill files to inject
    output_dir: Path = field(default_factory=lambda: Path("agents"))

def create_agent(spec: AgentSpec) -> Path:
    """Generate a specialized agent directory structure from an AgentSpec."""
    agent_dir = spec.output_dir / spec.name
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Generate system_prompt.md (approach ①)
    (agent_dir / "system_prompt.md").write_text(
        f"You are {spec.name}, {spec.role}.\n\n"
        f"Your tools: {', '.join(spec.tools) or 'inherit general tool set'}\n"
    )

    # Generate tool_profile.json (approach ②)
    (agent_dir / "tool_profile.json").write_text(
        json.dumps({"allowed_tools": spec.tools}, ensure_ascii=False, indent=2)
    )

    # Generate config.json (base configuration)
    (agent_dir / "config.json").write_text(
        json.dumps({"agent_id": spec.name, "version": "0.23"}, indent=2)
    )

    return agent_dir
```

Running `create_agent(AgentSpec(name="trader", role="crypto analyst", tools=["get_price"]))` should produce three files in `agents/trader/`: `system_prompt.md`, `tool_profile.json`, `config.json`. This is the minimal skeleton — not yet runnable, but the directory structure is established. Next we add capabilities incrementally.

---

## Beat 5 — Progressive Assembly

Starting from the skeleton, add three features that real-world systems need:

| Extension | Why It's Needed | How to Add |
|-----------|-----------------|------------|
| Skills injection (approach ③) | System prompt can only express "personality"; domain SOPs need structured documents | Generate `skills/` directory, write skill markdown files |
| CLI entry point | Let users trigger from one command, not hand-written Python | Wrap `create_agent` with `argparse` |
| SupervisorAgent | Multiple specialized agents need a unified intelligent routing entry | Wrap each agent as a tool |

**Extension 1: Skills Injection**

Let's extend `create_agent` to also write the skills directory:

```python
# lena_speckit/creator.py (extended with skills injection)
SKILL_TEMPLATES = {
    "risk_checker": """# Risk Checker Skill
## Trigger
Call this skill before every trade.
## Checklist
- [ ] Single trade risk exposure ≤ 2% of total capital
- [ ] Cumulative daily loss ≤ 5% of total capital
- [ ] Consecutive loss count < 3
## Output
APPROVED / REJECTED (with reason)
""",
    "position_sizer": """# Position Sizer Skill
## Input
- Total capital (USDT)
- Current price
- Stop-loss distance (%)
## Calculation
Position size = (Total capital × Risk ratio) / Stop-loss distance
## Output
Recommended position size (4 decimal places)
""",
}

def create_agent(spec: AgentSpec) -> Path:
    agent_dir = spec.output_dir / spec.name
    agent_dir.mkdir(parents=True, exist_ok=True)

    (agent_dir / "system_prompt.md").write_text(
        f"You are {spec.name}, {spec.role}.\n\n"
        f"Your tools: {', '.join(spec.tools) or 'inherit general tool set'}\n"
        f"Your skills: {', '.join(spec.skills) or 'none'}\n"
    )
    (agent_dir / "tool_profile.json").write_text(
        json.dumps({"allowed_tools": spec.tools}, ensure_ascii=False, indent=2)
    )
    (agent_dir / "config.json").write_text(
        json.dumps({"agent_id": spec.name, "version": "0.23"}, indent=2)
    )

    # Approach ③: generate skills directory
    if spec.skills:
        skills_dir = agent_dir / "skills"
        skills_dir.mkdir(exist_ok=True)
        for skill_name in spec.skills:
            content = SKILL_TEMPLATES.get(skill_name, f"# {skill_name} Skill\n\nTo be filled in.\n")
            (skills_dir / f"{skill_name}.md").write_text(content)

    return agent_dir
```

Checkpoint: `create_agent(AgentSpec(name="trader", role="crypto analyst", tools=["get_price"], skills=["risk_checker"]))` should produce:

```
agents/trader/
├── system_prompt.md       # includes role + tools + skills list
├── tool_profile.json      # {"allowed_tools": ["get_price"]}
├── config.json            # {"agent_id": "trader", "version": "0.23"}
└── skills/
    └── risk_checker.md    # risk management SOP
```

**Extension 2: CLI Entry Point**

Let's wire up the command-line interface:

```python
# lena_speckit/__main__.py
import argparse
from pathlib import Path
from .creator import AgentSpec, create_agent

def main():
    parser = argparse.ArgumentParser(prog="lena_speckit")
    sub = parser.add_subparsers(dest="command")

    p_create = sub.add_parser("create", help="Create a new specialized agent")
    p_create.add_argument("name", help="agent name")
    p_create.add_argument("--role", required=True, help="role description")
    p_create.add_argument("--tools", default="", help="comma-separated tool list")
    p_create.add_argument("--skills", default="", help="comma-separated skill list")
    p_create.add_argument("--output-dir", default="agents", help="output directory")

    args = parser.parse_args()
    if args.command == "create":
        spec = AgentSpec(
            name=args.name,
            role=args.role,
            tools=[t for t in args.tools.split(",") if t],
            skills=[s for s in args.skills.split(",") if s],
            output_dir=Path(args.output_dir),
        )
        agent_dir = create_agent(spec)
        print(f"✓ Created agent: {spec.name}")
        print(f"  Directory: {agent_dir}")
        print(f"  Tools: {len(spec.tools)}")
        print(f"  Skills: {len(spec.skills)}")

if __name__ == "__main__":
    main()
```

The CLI is now runnable:

```
$ python -m lena_speckit create trader \
    --role "crypto market analyst" \
    --tools "price_feed,orderbook,news_search" \
    --skills "risk_checker,position_sizer"

✓ Created agent: trader
  Directory: agents/trader
  Tools: 3
  Skills: 2
```

**Extension 3: SupervisorAgent**

With multiple specialized agents in place, you need an intelligent routing layer. The core idea is agent-as-tools: wrap each specialized agent as a tool, then let the SupervisorAgent's LLM decide which one to call.

```python
# lena_speckit/supervisor.py
import json
from pathlib import Path
from anthropic import Anthropic

class SupervisorAgent:
    """
    Agent-as-tools pattern.
    Each specialized agent is wrapped as a tool;
    the supervisor's LLM handles routing.
    """
    def __init__(self, agents_dir: Path = Path("agents")):
        self.client = Anthropic()
        self.agents_dir = agents_dir
        self.agents = self._load_agents()    # {name: system_prompt}
        self.tools = self._build_tools()     # Anthropic tool schema list

    def _load_agents(self) -> dict[str, str]:
        agents = {}
        for agent_dir in self.agents_dir.iterdir():
            prompt_file = agent_dir / "system_prompt.md"
            if prompt_file.exists():
                agents[agent_dir.name] = prompt_file.read_text()
        return agents

    def _build_tools(self) -> list[dict]:
        tools = []
        for name, prompt in self.agents.items():
            # Use the first line of the system prompt as the tool description
            description = prompt.split("\n")[0].lstrip("# ")
            tools.append({
                "name": f"delegate_to_{name}",
                "description": f"Delegate to the {name} specialized agent: {description}",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "The specific task to delegate"}
                    },
                    "required": ["task"],
                },
            })
        return tools

    def _run_leaf_agent(self, agent_name: str, task: str) -> str:
        """Invoke a leaf agent to complete a single task."""
        system_prompt = self.agents[agent_name]
        resp = self.client.messages.create(
            model="us.anthropic.claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": task}],
        )
        return resp.content[0].text

    def handle(self, user_message: str) -> str:
        """Main entry point: LLM routing + delegated execution."""
        messages = [{"role": "user", "content": user_message}]
        while True:
            resp = self.client.messages.create(
                model="us.anthropic.claude-sonnet-4-6",
                max_tokens=4096,
                system="You are a task routing agent. Analyze user intent and delegate to the most suitable specialized agent.",
                tools=self.tools,
                messages=messages,
            )
            if resp.stop_reason == "end_turn":
                return resp.content[0].text

            # Handle tool calls (delegation to leaf agents)
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    agent_name = block.name.replace("delegate_to_", "")
                    result = self._run_leaf_agent(agent_name, block.input["task"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
```

Checkpoint: create two specialized agents, then test routing.

```python
# Create two agents
from lena_speckit.creator import AgentSpec, create_agent
create_agent(AgentSpec(name="trader", role="quantitative analyst, focused on technical indicator analysis", tools=["get_price"]))
create_agent(AgentSpec(name="devops", role="DevOps engineer, focused on AWS alert monitoring and operations", tools=["list_alarms"]))

# Start supervisor
from lena_speckit.supervisor import SupervisorAgent
sup = SupervisorAgent()
print(f"Loaded agents: {list(sup.agents.keys())}")
# Output: Loaded agents: ['trader', 'devops']
```

---

## Beat 6 — Running and Verification

Let's assemble the final runnable demo and see it end-to-end:

```bash
# Install
pip install anthropic  # the only dependency

# Clone this chapter's code
# code/lena-v0.23/

# Create a trader agent
python -m lena_speckit create trader \
  --role "crypto market analyst" \
  --tools "price_feed,orderbook,news_search" \
  --skills "risk_checker,position_sizer"
```

Expected output:

```
✓ Created agent: trader
  Directory: agents/trader
  Tools: 3
  Skills: 2
```

Generated directory structure:

```
agents/trader/
├── config.json
├── system_prompt.md
├── tool_profile.json
└── skills/
    ├── risk_checker.md
    └── position_sizer.md
```

Now create a second agent and test SupervisorAgent routing (requires a valid `ANTHROPIC_API_KEY`):

```python
# examples/supervisor_demo.py
from pathlib import Path
from lena_speckit.creator import AgentSpec, create_agent
from lena_speckit.supervisor import SupervisorAgent

# Prepare two agents
create_agent(AgentSpec(
    name="trader",
    role="quantitative analyst, focused on technical indicators and market signals",
    tools=["get_price", "get_indicators"],
    skills=["risk_checker"],
))
create_agent(AgentSpec(
    name="devops",
    role="DevOps engineer, focused on AWS alert monitoring and operations remediation",
    tools=["list_alarms", "get_logs"],
    skills=[],
))

# Start supervisor
sup = SupervisorAgent()
print(f"Loaded specialized agents: {list(sup.agents.keys())}\n")

# Test routing
response = sup.handle("What does the RSI trend look like for BTC recently? Is it a good time to enter?")
print("Routing result:")
print(response)
```

Expected output (no real price_feed needed — the supervisor delegates to the trader's system prompt):

```
Loaded specialized agents: ['trader', 'devops']

Routing result:
[trader agent analysis based on system prompt...]
```

**Common failure diagnostics**:

- `ModuleNotFoundError: No module named 'anthropic'` → run `pip install anthropic`
- `AuthenticationError` → check the `ANTHROPIC_API_KEY` environment variable is set
- `agents/` directory is empty → SupervisorAgent finds no agents; run the `create` command first
- Routing always goes to the same agent → check whether the first lines of both agents' `system_prompt.md` are sufficiently differentiated

**The boundary of system prompts**: it's worth pausing to test a failure case.

```python
# BAD: writing safety rules inside the system prompt
bad_prompt = """
You are TradingBot.
Safety rule: single trade risk exposure must not exceed 2% of total capital.
"""

# Test: pass in an empty symbol string
response = client.messages.create(
    system=bad_prompt,
    messages=[{"role": "user", "content": 'Place order, symbol="", quantity=10000'}],
    ...
)
# LLM may reply "Sure, order placed" — it ignored the rule
```

This isn't because `bad_prompt` is poorly written — **LLMs will ignore rules in prompts when presented with boundary inputs**. This is a structural limitation, not a prompt engineering problem. The correct approach is to put risk controls in code:

```python
# GOOD: risk controls in code, impossible to bypass
def place_order(symbol: str, qty: float, total_capital: float) -> dict:
    if not symbol:
        raise ValueError("symbol cannot be empty")  # code-level hard block
    max_position = total_capital * 0.02
    if qty * current_price(symbol) > max_position:
        raise ValueError(f"Risk exposure exceeded: {qty * current_price(symbol):.2f} > {max_position:.2f}")
    return _execute_order(symbol, qty)
```

Where the rule lives determines its reliability: **personality and style belong in prompts; safety and guardrails belong in code**.

In the next chapter, we specialize Lena into a concrete Browser Agent — she won't just use tools, she'll control a real browser to complete end-to-end automation tasks. This is the final stress test for a general-purpose agent's capabilities.

---

## Beat 7 — Design Note

### Why Not Always Specialize?

With Lena-SpecKit available, it's easy to fall into "specialize everything" mode — creating a new `lena_speckit create` for every new requirement until you're maintaining 20 specialized agent config directories.

This is a common form of over-engineering.

**Alternative**: keep the general-purpose agent and inject temporary roles via context.

```python
# General-purpose agent + temporary role injection
response = client.messages.create(
    system="You are Lena, a general-purpose agent.",
    messages=[
        {"role": "user", "content": "From now on, act as a quantitative analyst and analyze BTC's technical indicators."},
        {"role": "user", "content": "BTC RSI is currently 42, MACD just formed a golden cross. How would you read this?"},
    ],
)
```

The trade-offs of this approach:

- 🟢 Zero maintenance cost, no agent directories to manage
- 🟢 Roles can switch flexibly within a conversation
- 🔴 Context contamination: the "quantitative analyst role" from this conversation bleeds into subsequent ones
- 🔴 Tool set cannot be isolated by role (all general-purpose tools remain exposed)
- 🔴 Cannot inject role-specific skills (every conversation requires re-explaining the SOP)

**When to specialize**:

| Condition | Recommendation |
|-----------|----------------|
| Needs persistent operation (heartbeat / cron) | Specialize — temporary roles can't persist |
| Needs tool set isolation (security requirement) | Specialize — general-purpose agent has too many tools |
| Needs stable domain SOPs (fixed operating procedures) | Specialize — skills injection is more reliable than re-explaining SOPs verbally every time |
| One-off task, disposable | Don't specialize — general-purpose agent is sufficient |
| Rapid prototype, role definition still uncertain | Don't specialize — get it working first, then solidify |

The current SpecKit implementation has one known limitation: skill templates are hardcoded with no ability to dynamically load from a file directory. In a production system, you'd want skills to come from a Git-managed markdown directory, updatable via `git pull` rather than regenerating the agent config — this is the "shared skills ecosystem" direction described in Anthropic's *Equipping Agents for the Real World with Agent Skills* (2025-10-16).

### Dynamic Agent Generation: The Conceptual Foundation of Lena-spawn

The SpecKit "one-command-to-spawn-a-specialized-agent" pattern aligns closely in spirit with the **Dynamic Agent Generation** emerging pattern described in the Anthropic whitepaper. The whitepaper defines this pattern as (p.22):

> "agents created at runtime by assembling components from libraries of prompts, tools, and configurations, then dissolved after task completion."

In other words: instead of pre-building fixed specialized agents, dynamically assemble them at runtime from a component library (prompt library + tool library + config library), then dissolve them when the task is complete. This is exactly the core idea of Lena-spawn — the command `python -m lena_speckit create trader` is fundamentally a runtime assembly: pulling the trader's tool list and skills from `DOMAIN_CONFIGS`, writing them to config files, forming a new specialized agent instance.

(Source: Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*, 2025, p.22)

The key difference between dynamic generation and static specialization is **lifecycle**: statically specialized agents are persistent (create them once and they wait for tasks); dynamically generated agents are ephemeral (assembled when a task arrives, dissolved when it completes). For long-running heartbeat agents (like a quantitative trading monitor), static specialization is more appropriate; for one-off high-complexity tasks (like analyzing a 100-page contract), dynamically generating a temporary specialized agent is more economical — use it and discard it.

### The Ecommerce Scenario: A 5-Phase Path from Single Agent to Multi-Agent

The Anthropic whitepaper uses a real-world e-commerce customer service evolution case (p.24-25) to show how the Specialization Pattern develops in actual business. This path has broad applicability — almost every team deploying agents at scale goes through similar phases:

| Phase | Approach | Value |
|-------|----------|-------|
| **Phase 1** | Single agent answers customer inquiries | Prove feasibility, build confidence |
| **Phase 2** | Add routing (order queries / product questions / complaints) | Improve accuracy, reduce misrouting |
| **Phase 3** | Connect a Specialized agent after each route | Specialization brings depth; each agent can be independently optimized |
| **Phase 4** | Multi-agent orchestration (inventory + payment + logistics coordination) | Handle complex requests spanning multiple systems |
| **Phase 5** | Add Evaluator agents for continuous quality improvement | System self-monitors; forms a closed loop |

Notice the cadence: each phase only advances after the previous one is validated. Without Phase 1's single-agent value proof, there's no Phase 2 routing. Without Phase 2's accuracy data, there's no knowing which categories justify building a dedicated Phase 3 agent.

This is the engineering meaning of the whitepaper's quote: **"your architecture should evolve with your needs. Start simple, measure everything, add complexity only when it delivers measurable value."**

---

## Appendix: Lena Evolution Timeline

```
v0.1  Print one model reply (Ch1)
v0.3  REPL + single tool (Ch3)
v0.6  4 concurrent tools (Ch6)
v0.14 RAG search_knowledge_base (Ch9 + Ch14)
v0.16 MessageBus + Channel (Ch16)
v0.18 Cron + checkpoint/resume (Ch18)
v0.22 Observability + deployment (Ch22)
★ v0.23 Specialization + SpecKit (this chapter)
```

---

Lena learned "how to go from general to specialized" in this chapter. SpecKit's three-piece kit (specialized system prompt + tool subset + memory filter) lets the same runtime fork into domain expert agents without rewriting the core logic.

But the ultimate proving ground for the Specialization pattern is a real task that requires all six pillars to be online simultaneously: browsing the internet. A Browser Agent needs to perceive the DOM, generate click sequences, handle dynamic loading, maintain login state, and design fallbacks under anti-bot constraints — more complex than any single pillar. **In Chapter 24, we use everything from the first 23 chapters to build lena-v0.24 Browser Agent — the final comprehensive test of a general-purpose agent.**

---

## Navigation

➡️ **[Ch 24. Browser Agent (Grand Finale)](../ch24-browser-agent/README-en.md)** — The ultimate stress test of all 23 chapters' capabilities in a Browser Agent

[← Ch 22. Observability and Deployment](../ch22-observability-deploy/README-en.md) · [📘 Table of Contents](../../README.md)
