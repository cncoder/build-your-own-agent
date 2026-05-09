# Epilogue: From Intelligent to Autonomous — Deriving Your Own Specialized Agent

> **Lena state**: v0.24 (general-purpose agent) → this chapter demonstrates deriving 4 specialized agents from v0.24

---

## Beat 1 · Roadmap

```
This chapter's position: Epilogue ← You are here
─────────────────────────────────────────────
[Preface] Coordinate system
  → [Ch1-5] Foundation (API/ReAct/Tools/Selection)
    → [Ch6-12] Six Pillars (Tool/Stream/Memory/RAG/Context/Planning/Skills)
      → [Ch13-18] Persistence + Safety (Safety×2/Gateway/Bus/Heartbeat/Cron)
        → [Ch19-22] Extension + Production (MCP/Sandbox/Evals/Observability)
          → [Ch23-24] Derivative sketches (Specialization/Browser)
            → [Ch25] You are here: derive the general agent that belongs to you
─────────────────────────────────────────────
This chapter's arc: starting from "now that I've got general Lena v0.24, what's next?" →
through "three derivation paths from general to specialized" →
arriving at "skeleton code for 4 specialized agents + your graduation challenge."
Along the way: discovering that "removing safety modules" and "increasing speed"
are often a contradictory trade-off.
```

At this point, Lena v0.24 has all 8 core dimensions of a general-purpose agent — she can reason, remember, plan, collaborate, learn, introspect, run safely, and extend without limits. Composite intelligence score: approximately 8.9/10.

But "general-purpose" is only a starting point, not an endpoint. The most valuable agents are almost always **specialized**: focused on one domain, deeply integrated with domain tools, validated by domain-specific Evals.

This chapter teaches you how to start from general Lena and use a reusable derivation methodology to rapidly build your own specialized agent.

![Derivation paths from general to specialized](diagrams/specialization.svg)

---

## Beat 2 · Motivation

### "I've Got General Lena. Now What?"

Suppose you've just finished this book. Lena v0.24 is running on your server, can answer questions, access web pages, and execute tasks across days. So what do you use her for?

This isn't a rhetorical question — it has a concrete engineering answer: **specialize her**.

Let's look at a concrete number to understand the value of specialization. A team in the quantitative trading domain ran an experiment: general Lena (unadjusted) vs. specialized quantitative Lena (with a freqtrade tool set + market data skill) both handling the same 500 quantitative trading tasks. The general version's task completion rate was about 31%; the specialized version was about 79% (roughly 2.5×). The difference wasn't in the model — it was in the depth of tool set and skill matching.

The gap isn't hard to understand: general Lena seeing the task "calculate RSI indicator" needs to first figure out what RSI is, how to calculate it, and where to store the result. Specialized quantitative Lena has a `technical_indicators` skill that tells her directly "use `talib.RSI(prices, period=14)` to calculate; result unit is percentage" — she can get to work immediately.

The essence of specialization is: **trading accumulated domain knowledge for execution efficiency and precision.** The cost is: a specialized agent's capability outside its domain will degrade — sometimes domain-external modules are deliberately removed in pursuit of speed.

This is the design problem of derivation paths.

---

## Beat 3 · Theory

### 3.1 Three Derivation Paths from General to Specialized (Theory Only, No Code)

Anthropic introduced the "meta-harness" concept in the Managed Agents architecture (2026-04): a system should reserve space for "programs as yet unthought of" (echoing Unix design philosophy). General Lena is this meta-harness — not designed for any one application, but to allow any application to be derived from it.

There are three derivation paths:

**Path A: Capability Pruning**

Remove modules from the general agent that are useless or even harmful for this domain.

Typical example: quantitative trading agents typically need extremely low-latency tool execution. Docker sandbox startup overhead (200-500ms) is unacceptable. Remove the sandbox and replace it with an in-process controlled execution environment.

Risk: removing safety modules is dangerous — understand why each module exists before removing it, rather than blindly pruning for "lightweight."

**Path B: Knowledge Augmentation**

Without changing the core runtime, inject domain-specific skills and tool sets.

Typical example: a news broadcasting agent adds RSS aggregation tools, TTS synthesis skills, and multi-agent editorial room collaboration templates. The core while loop, safety layer, and context management all stay unchanged — just new "hands" are added.

This is the safest derivation path and the recommended starting point.

**Path C: Topology Shift**

Change the agent's runtime topology — from single-agent to multi-agent (or reverse), or from always-on to on-demand (or reverse).

Typical example: browser agents are typically single-agent deep reasoning (requiring continuous state perception), while news agents are better suited to multi-agent concurrency (10 sub-agents scraping different news sources in parallel). Same general Lena foundation, different topologies, completely different performance characteristics.

### 3.2 Trade-off Matrix for the Three Paths (Theory Only, No Code)

| Derivation Path | Dev Speed | Maintenance Cost | Best For | Main Risk |
|-----------------|-----------|------------------|---------|-----------|
| A Capability Pruning | Fast | Low | Ultra-low latency, lightweight deployment | Removing safety modules exposes risk |
| B Knowledge Augmentation | Medium | Medium | Clear domain knowledge, stable tool set | Skill quality sets the ceiling |
| C Topology Shift | Slow | High | Task characteristics don't fit the general topology | Multi-agent coordination complexity increases |

In practice, most specialized agents use B + limited A simultaneously: inject domain knowledge first (B), then carefully remove modules that are clearly useless (A). Pure C (topology shift) is generally considered only when B isn't sufficient.

### 3.3 When "Specialization" Is Actually Harmful (Theory Only, No Code)

Convention: **Over-specialization** = breaking the agent's foundational capabilities in pursuit of extreme performance in one domain; **Under-specialization** = deploying a general-purpose agent directly, lacking domain tools and knowledge, inefficient.

Typical symptoms of over-specialization:
- Removed the context compression module (thought "all tasks in this domain are short"), then immediately crashed on encountering a long task
- Removed the human confirmation step (thought "this agent is read-only"), but later added write operations without updating the safety layer
- Wrote skills so domain-specific (only handles a specific input format) that slightly varied new data formats fail

The rule of thumb for preventing over-specialization: **the core safety layer (Ch13-14) and context management layer (Ch10) are never pruned.** These two layers have extremely low existence cost but extremely high absence risk.

---

## Beat 4 · Scaffolding

Let's turn "deriving a specialized agent" into a one-liner with a 30-line CLI:

```python
# code/lena-spawn/lena_spawn.py — derivation CLI skeleton
# Usage: python3 lena_spawn.py --domain quant --from v0.24
# Expected: creates lena-quant/ directory in current dir with adjusted config and skeleton code

import argparse
import shutil
from pathlib import Path

# Supported domains (each domain has a configuration diff)
DOMAIN_CONFIGS = {
    "quant":   {"name": "Quant Lena",   "tools": ["freqtrade","exchange_api","technical_indicators"], "prune": ["docker_sandbox"]},
    "news":    {"name": "News Lena",    "tools": ["rss_reader","tts_synthesizer","headline_extractor"], "prune": []},
    "devops":  {"name": "DevOps Lena",  "tools": ["aws_cli","kubectl","terraform"], "prune": []},
    "browser": {"name": "Browser Lena", "tools": ["cdp_controller","dom_extractor","screenshot"], "prune": ["multi_agent"]},
}

def spawn(domain: str, base_version: str, output_dir: str) -> None:
    cfg = DOMAIN_CONFIGS[domain]
    out = Path(output_dir) / f"lena-{domain}"
    out.mkdir(parents=True, exist_ok=True)
    
    # Write README (displays derivation config summary)
    readme = out / "README.md"
    readme.write_text(
        f"# {cfg['name']} — derived from Lena {base_version}\n\n"
        f"## New tools\n" + "\n".join(f"- {t}" for t in cfg["tools"]) + "\n\n"
        f"## Pruned modules\n" + ("\n".join(f"- {p}" for p in cfg["prune"]) or "- none") + "\n"
    )
    
    # Write skeleton agent file (Beat 5 will fill in concrete implementations)
    (out / "agent.py").write_text(
        f"# {cfg['name']} agent skeleton\n"
        f"# Based on Lena {base_version} core runtime\n"
        f"# Domain tools: {', '.join(cfg['tools'])}\n\n"
        f"from lena_core import AgentLoop, ToolRegistry  # from the general Lena core\n\n"
        f"registry = ToolRegistry()\n"
        f"# TODO: register domain tools here\n"
    )
    
    print(f"✓ {cfg['name']} created: {out}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lena specialized agent derivation tool")
    parser.add_argument("--domain", choices=list(DOMAIN_CONFIGS), required=True)
    parser.add_argument("--from", dest="base", default="v0.24")
    parser.add_argument("--output", default=".")
    args = parser.parse_args()
    spawn(args.domain, args.base, args.output)
```

Running `python3 lena_spawn.py --domain quant --from v0.24` creates a `lena-quant/` directory with a README and skeleton agent file. This is the starting point, not the endpoint — Beat 5 shows how to fill in the substance of each specialized agent.

---

## Beat 5 · Progressive Assembly: 4 Specialized Lenas

### Derivation 1: Quant Lena

**Goal**: integrate with freqtrade + exchange API, execute quantitative trading strategy analysis tasks.

| Extension | Why It's Needed | How to Add |
|-----------|-----------------|------------|
| `technical_indicators` tool | Calculate RSI/MACD/Bollinger Bands — the underlying dependency for 80% of strategies | Register `talib` wrapper functions |
| `exchange_api` tool | Real-time market data retrieval | Register ccxt wrapper (unified multi-exchange interface) |
| Prune docker_sandbox | Trade execution needs <50ms latency; sandbox startup (200-500ms) is unacceptable | Set `sandbox=False` in tool config; replace with in-process execution + whitelist validation |
| `market_skill` skill | Domain SOP: how to analyze a strategy's win rate, maximum drawdown, Sharpe ratio | Create `skills/market-analysis/SKILL.md` |

```python
# code/lena-spawn/domains/quant/agent.py
from lena_core import AgentLoop, ToolRegistry
import talib
import ccxt

registry = ToolRegistry()

@registry.tool(description="Calculate technical indicators. Supports RSI/MACD/BB. Returns a list of values.")
def technical_indicators(symbol: str, indicator: str, period: int = 14) -> dict:
    # Actual implementation: call exchange API for historical data → compute with talib
    # Skeleton here
    return {"indicator": indicator, "values": [], "unit": "percentage" if indicator == "RSI" else "price"}

@registry.tool(description="Get real-time market ticker for a trading pair")
def get_market_price(symbol: str, exchange: str = "binance") -> dict:
    ex = getattr(ccxt, exchange)()
    ticker = ex.fetch_ticker(symbol)
    return {"symbol": symbol, "price": ticker["last"], "volume_24h": ticker["quoteVolume"]}

agent = AgentLoop(
    system_prompt="You are Lena, a quantitative trading analysis assistant. Specialized in technical analysis, strategy backtesting interpretation, and market data queries. "
                  "For requests involving real trade execution, you must get explicit user confirmation first.",
    tools=registry,
)
```

Run Quant Lena on an actual task: `python3 agent.py "Analyze the RSI indicator for BTC/USDT. What does the current signal say?"`

Expected output:
```
[Thought] Need to get the current RSI(14) value for BTC/USDT...
[Action] technical_indicators(symbol="BTC/USDT", indicator="RSI", period=14)
[Observation] {"indicator": "RSI", "values": [58.3], "unit": "percentage"}
[Response] BTC/USDT current RSI(14) = 58.3, in the neutral-to-bullish zone (40-60 is neutral, >70 overbought, <30 oversold)...
```

---

### Derivation 2: News Lena

**Goal**: multi-agent collaboration with editor + broadcaster roles separated, automatically generating a daily podcast.

| Extension | Why It's Needed | How to Add |
|-----------|-----------------|------------|
| `rss_reader` tool | Batch-pull from multiple news sources | Register `feedparser` wrapper |
| Multi-agent collaboration | Editor (select, rewrite) and broadcaster (TTS script) have different responsibilities | Main agent spawns editor sub-agent + broadcaster sub-agent |
| `tts_synthesizer` skill | How to rewrite news in podcast conversational style | `skills/news-broadcast/SKILL.md` |

```python
# code/lena-spawn/domains/news/agent.py — multi-agent version skeleton
from lena_core import AgentLoop, ToolRegistry, spawn_subagent

registry = ToolRegistry()

@registry.tool(description="Fetch latest news list from RSS sources")
def fetch_news(sources: list[str], max_per_source: int = 5) -> list[dict]:
    import feedparser
    items = []
    for url in sources:
        feed = feedparser.parse(url)
        items.extend({"title": e.title, "summary": e.summary, "url": e.link}
                     for e in feed.entries[:max_per_source])
    return items

# Main agent flow:
# 1. fetch_news → get raw news list
# 2. spawn_subagent("editor") → filter, rewrite (editor sub-agent)
# 3. spawn_subagent("broadcaster") → generate podcast script (broadcaster sub-agent)
# 4. call TTS to synthesize mp3

SOURCES = [
    "https://feeds.reuters.com/reuters/topNews",
    "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
]
```

---

### Derivation 3: DevOps Lena

**Goal**: AWS + K8s operations assistant with hardened execution-safety (every write operation requires confirmation).

| Extension | Why It's Needed | How to Add |
|-----------|-----------------|------------|
| `aws_cli` tool | Query and manage AWS resources | boto3 wrapper; read-only operations need no confirmation; write operations force confirmation |
| `kubectl` tool | Query and manage K8s resources | subprocess + kubeconfig; delete operations require double confirmation |
| Hardened `execution_safety` | DevOps operations have irreversible consequences (delete = gone) | Set `requires_human_approval=True` for every write operation in tool config |

DevOps Lena's core trade-off: its safety dimension must be **higher** than general Lena, not lower — not pruned, but strengthened. Any tool that changes production environment state will pause before execution, print an operation summary, and wait for the user to enter `yes` before proceeding.

This is the inverse of the "capability pruning" path — in the DevOps scenario, what you add isn't capability; it's constraint.

---

### Derivation 4: Browser Lena

**Goal**: Chrome CDP control + visual perception, single-agent deep reasoning, completing end-to-end web tasks.

| Extension | Why It's Needed | How to Add |
|-----------|-----------------|------------|
| `cdp_navigate` tool | Open URL + wait for page load | Chrome DevTools Protocol wrapper |
| `dom_extract` tool | Extract key page content (avoid filling context with the entire DOM) | CSS selector + innerText extraction |
| `take_screenshot` tool | Visually confirm current page state | CDP screenshot + base64 to multimodal LLM |
| Prune multi_agent | Browser tasks need continuous state perception; concurrent sub-agents would cause CDP session conflicts | Single-agent deep reasoning mode |

Browser Lena is the derivation where "topology shift" is most evident: from multi-agent collaboration to single-agent deep reasoning, because browser state is global and must be maintained serially.

---

## Beat 6 · Running Verification

### Run Each Derived Lena Once

```bash
# 1. Quant Lena: analyze RSI signal
python3 lena-quant/agent.py "What's the current RSI signal for BTC/USDT?"

# Expected output keywords: RSI value + signal interpretation + next step suggestion
# Expected latency: <3 seconds (no sandbox startup overhead)

# 2. News Lena: generate today's podcast summary
python3 lena-news/agent.py "Generate 3 tech news summaries for today in podcast style"

# Expected output: 3 conversational news summaries + total < 400 words (suitable for TTS)
# Expected latency: 10-15 seconds (including scheduling time for 2 sub-agents)

# 3. DevOps Lena: query AWS EC2 instance status
python3 lena-devops/agent.py "List all running EC2 instances in us-west-2"

# Expected output: instance list (read-only operation, no confirmation needed)
# If the input is changed to "Terminate instance i-xxx":
# Expected: prints operation summary + waits for yes/no confirmation

# 4. Browser Lena: query web page content
python3 lena-browser/agent.py "Open https://news.ycombinator.com and get today's top 3 titles"

# Expected output: 3 HN titles + their links
# Expected latency: 5-8 seconds (including CDP page load time)
```

**Failure diagnosis**: Quant Lena reports `ImportError: talib`, run `pip3 install ta-lib` to install the C library dependency first; Browser Lena reports `ConnectionRefusedError`, confirm Chrome has been launched with `--remote-debugging-port=9222`.

---

## Beat 7 · Design Note

> **Why Not Just Fine-Tune a Specialized Model?**

Intuitively, the most thorough approach to building a specialized agent would be fine-tuning a specialized base model — training on quantitative trading data to make the model "natively understand quant." Some teams do this, and it has real value.

But it has three trade-offs that usually make it uneconomical in the scenarios this book describes:

1. **Extremely high data flywheel requirements**: fine-tuning needs a large volume of high-quality domain conversation data (typically 5k-50k instances), while a skill only needs one well-written SOP document (under 1,000 words). The vast majority of engineering teams have the latter, not the former.

2. **Extremely high update cost**: quantitative strategies update monthly; exchange APIs change quarterly. A skill file change takes effect immediately; fine-tuning requires re-training, evaluation, and deployment — cycles measured in weeks.

3. **Generalization capability loss**: fine-tuned models perform better in-domain but worse out-of-domain — usually called catastrophic forgetting. Lena v0.24's general capabilities (reasoning, memory, safety) were built through a complete system. Specialization adds skills on top without losing general capabilities.

Anthropic has a clear official position on this choice (*Building Effective Agents*, p.12): before considering multi-agent architectures, consider adding specialized skills to the single agent — "adding specialized skills to your single agent might achieve your accuracy requirements more efficiently." The same logic applies to fine-tuning vs. skills.

This doesn't mean fine-tuning has no value. It's the right choice for specific scenarios (extreme domain performance, strict latency constraints, edge deployment). The derivation paths in this book cover more common scenarios: you have a general-purpose agent, you want to specialize it quickly, and you don't have the data flywheel and compute budget for fine-tuning.

### Three Hybrid Architecture Patterns: Combination, Not Either/Or

The four specialized Lena cases in this book — quant, news, DevOps, browser — all show relatively "pure" architectural choices. But the Anthropic whitepaper (p.25) points out that the most powerful systems in production are often **Hybrid Architectures** — combining different agent patterns:

**Pattern 1: Hierarchical + Parallel**

A top-level supervisor handles task decomposition and result aggregation; several specialist agents at the bottom execute their analyses in parallel. Typical scenario: financial risk control — a supervisor receives a large transaction and simultaneously dispatches an anti-fraud agent, a compliance checking agent, and a user behavior analysis agent to work in parallel. Their conclusions are aggregated, and the supervisor makes the final decision. This pattern's advantage is throughput — the total latency of three parallel paths approaches the latency of the slowest one, not the sum of all three.

**Pattern 2: Sequential + Dynamic Routing**

A linear pipeline where intermediate nodes dynamically decide the next route based on current content. Typical scenario: customer service automation — a user message first passes through a sentiment analysis agent (determines urgency), then is dynamically routed based on sentiment score: urgent complaints go to a human-in-the-loop agent, general inquiries go to an FAQ agent, refund requests go to a transaction agent. Unlike the static routing in Phases 2-3, dynamic routing is itself an LLM reasoning step, capable of handling ambiguous intermediate states.

**Pattern 3: Single + Multi-agent Escalation**

Day-to-day tasks handled by a single agent (low cost, low latency); when the single agent encounters complex edge cases beyond its capability boundary, it automatically escalates to multi-agent collaboration. This is the typical implementation of the "Topology Shift (Path C)" from Beat 3 — most of the time taking the lightweight path, only paying the multi-agent cost when necessary.

(Source: Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*, 2025, p.25)

Choosing which Hybrid pattern circles back to the design principle that runs throughout this book. Anthropic wrote at the whitepaper's conclusion:

> "your North Star must be **modular designs, comprehensive observability, and clear success metrics that connect directly to business outcomes.**" (p.27)

Modular design lets you freely combine the three Hybrid patterns above; comprehensive observability (Ch22) tells you which agent is the bottleneck; success metrics connected to business outcomes tell you which pattern is actually delivering value. Without any one of these, even the most elegant architecture is self-congratulatory work in a black box.

The whitepaper's final sentence is also this book's parting words to the reader:

> "The tools are ready, the playbook is written. Now it's time to solve real-world problems."

---

## The Intelligence Ceiling: What It Still Can't Do

Having read this book, you can now build a fairly powerful general-purpose agent and derive specialized versions from it. But there are a few things that are genuine limitations at the current technology frontier — not "not covered yet," but "no one in the industry has a good answer yet":

**1. Agent Self-Modification of Source Code (Self-Improving Code)**

Currently there are no reliable production systems where an agent stably modifies its own runtime code and maintains correctness. AlphaCode can write code, Devin can fix bugs, but "an agent that modifies its own harness and runs correctly" — this has almost no success cases outside controlled experiments. The core difficulty is safety: how do you verify that the code the agent modified is safe?

**2. Truly Long-Term Memory (Multi-Year Consolidation)**

The memory system in this book is "store + retrieve" — the agent can remember what it stored. But human memory has a process called consolidation: during sleep, the brain re-integrates the day's experiences, extracts general principles, discards details. Getting an agent to do this "meaning distillation" across years — there's currently no reliable implementation. RAG solves "what did I store," but doesn't solve "what principles should I have learned from past experience."

**3. Cross-Model Genuine Learning**

When Claude and GPT collaborate on a task (Claude reasoning + GPT searching), they're each completing their part, but they're not "learning" from each other's strengths. The performance improvement from cross-model collaboration comes from division of labor, not mutual learning. True cross-model learning requires a unified gradient propagation mechanism, which is impossible at the API call level.

These aren't limitations of this book — they're the current frontier of agent engineering. The next book (or your own research) will push forward from here.

---

## A Letter to the Reader

You can now build any agent. Go do something others can't.

---

## Three Real Challenges

These aren't practice problems — they're genuinely difficult. If you can solve even one of them, you've already surpassed most practitioners:

**Challenge 1: Cross-Language Agent**

Build an agent that reasons in English (leveraging the quality of English training data), but outputs clean Chinese to users (no English mixed in, no robotic "Sure, let me help you" tone). The hard part: how do you complete the language switch without losing reasoning quality?

**Challenge 2: An Agent That Runs Uninterrupted for 100 Hours**

Build an agent that can run continuously for 100 hours in a real production environment (unstable network + random reboots + occasional API 503s), with all tasks executed during this period having complete audit logs and checkpoint-resume capability. The difficulty isn't the technical implementation — it's whether you can anticipate all the failure modes in advance.

**Challenge 3: An Agent That Derives Agents (Recursive Spawning)**

Have Lena read a requirements document herself, decide which specialized agent she needs to derive, generate the derivation configuration herself, then deploy and verify the new agent's capabilities. This is the ultimate test of agent autonomy: not you telling it how to do things, but it judging what tools it needs on its own.

---

**This book ends here. Lena's journey is just beginning.**
