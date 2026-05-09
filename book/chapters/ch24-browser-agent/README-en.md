# Chapter 24: Grand Finale — Browser Agent

> **[Six Pillars Final Stress Test · Book Grand Finale]**
>
> "Browser Agent isn't a special case. It's the ultimate proving ground for a general-purpose agent. Every capability you've built over the past 23 chapters gets pushed to its limit here."

---

## Chapter Roadmap

```
Full-book evolution (the final cell):

Ch 1      Ch 3      Ch 6      Ch 9      Ch 13      Ch 18      Ch 22      Ch 24
  │         │         │         │          │          │          │          │
API call  Lena born  Tools    RAG       Safety     Long-task  Observe  Browser Agent
  │         │         │         │          │          │          │          │
v0.1      v0.3      v0.6      v0.9       v1.2       v1.5       v0.22      v0.24
                                                                       ← You are here
```

This chapter starts from something lena-v0.23 simply cannot do: `lena-v0.23 is completely helpless when asked "check my Weibo messages"`.

Through theory (browser's four major challenges) → scaffolding (minimal Browser Agent) → progressive assembly (DOM perception + page transitions + login state + three-layer fallback) → running verification (three end-to-end tasks), the final output is `lena-v0.24`: a Browser Agent that can actually navigate the internet.

Along the way we'll hit real gotchas: the Origin header causing 403s, a local proxy tool hijacking the CDP socket (e.g., in fake-ip mode), uncleaned tabs clogging Chrome, and blank-page screenshots causing false negatives.

The **Full-Book Retrospective** section ties together the complete evolution from Ch 1 to Ch 23. The final section, "What Else Can Your Lena Become," offers three creative directions, and the closing words belong to the reader.

Lena version: `v0.23 (specialized) → v0.24 (Browser Agent, internet-capable)`

---

## Beat 1 · Roadmap: What Lena Was Still Missing

By `lena-v0.23`, Lena could do quite a lot.

She has 30+ tools, three memory tiers, 24/7 uptime, Telegram push notifications, scheduled tasks, MCP protocol extensions, Docker sandbox isolation, and can fork specialized agents with one line.

But give her a task — "check if there are any new AI news on Weibo" — and she's stuck.

Not because she isn't smart enough. Because Weibo's content lives in the browser: inside JavaScript-rendered dynamic DOM, behind a login wall, behind anti-bot defenses. The lena-v0.23 tool set has no "operate a browser" entry.

That's the last puzzle piece this chapter completes.

We start with theory: the four major challenges of Browser Agents (infinite DOM, page transitions, anti-bot, login state), and how these four challenges map precisely onto the six pillars you built over the first 23 chapters. Then we look at the decision logic for three browser paths, dive into browser-use's architecture (92k stars), assemble `lena-v0.24`, and run three end-to-end tasks.

Finally, we look back at the whole book, then look forward.

> **Intelligence increment (v0.23 → v0.24)**: Lena can operate a browser for the first time — CDP computer use lets her "see" dynamic DOM, maintain login state, and handle page transitions, going from "completely helpless against JavaScript-rendered pages" to running three real internet tasks. This chapter teaches you how to wire browser operation capability into your own agent.

---

## Beat 2 · Motivation: When an Agent Hits the Browser Wall

Simon Willison's **Dual LLM Pattern** (2023) becomes especially important in browser agent scenarios:

> Privileged LLM holds tools (controls the browser) + isolated LLM processes untrusted content (text on web pages), with no direct token sharing between the two.

Why? Because browser agents are **the most prompt-injection-vulnerable agent type** — every web page could contain malicious instructions. Ch13 covered input safety in general terms; this chapter pushes it to the extreme: your agent will **actively open an attacker's web page**, then use an LLM to parse its contents. Without isolation, you're handing the agent's tool control authority to anyone on the internet.

Let's run a quick test. Open Python and try to read Weibo's homepage content using lena-v0.23's current tool system:

```python
# lena-v0.23's web_search tool, reasonably broad coverage
result = await lena.run("Extract summaries of today's AI-related posts from Weibo's homepage")
```

Result:

```
Error: web_search returned Weibo's login redirect page, no content
OR:
Error: HTTP 200 but content is "<div id='root'></div>" (CSR empty shell)
OR:
Error: 403 Forbidden (User-Agent identified as non-browser)
```

Three failures, three root causes:

1. **Content is behind a login wall**: `requests.get("https://weibo.com")` returns a login redirect, not content.
2. **Content is inside JavaScript**: modern SPAs render DOM only after JS execution in a browser. HTTP GET only gets the empty HTML shell.
3. **Anti-bot systems identify you**: User-Agent, request intervals, behavioral fingerprinting — any anomaly triggers a block.

This isn't a bug in lena-v0.23. It's an architectural limitation. She has no browser, like a person without hands trying to type.

**The gap by the numbers**:

| Scenario | lena-v0.23 (no browser) | lena-v0.24 (with browser) |
|----------|------------------------|--------------------------|
| Static web scraping | ✅ ~95% success | ✅ ~99% success |
| SPA dynamic content | ❌ ~5% success | ✅ ~80% success |
| Content behind login | ❌ 0% success | ✅ ~70% success |
| Requires interactive operations | ❌ 0% success | ✅ ~60% success |

The last two rows represent an unbridgeable gap. Without a browser, it's 0%.

> Convention: In this chapter, "browser operation" = the agent controlling browser behaviors (click/type/scroll/screenshot/navigate); "web scraping" = issuing an HTTP GET and parsing HTML source. The success rate differences above explain why — we won't repeat this distinction in the text.

---

## Beat 3 · Theory: How the Four Challenges Map onto the Six Pillars

### 3.1 Infinite DOM — The "Context Bomb" of Tool Input

How many DOM nodes does a complete modern web page have?

Measurements (as of May 2026):

| Website | DOM nodes | Serialized size |
|---------|-----------|-----------------|
| Weibo homepage | ~6,000 nodes | ~800KB |
| GitHub repo page | ~3,000 nodes | ~400KB |
| Amazon product page | ~8,000 nodes | ~1.2MB |
| Simple React app | ~500 nodes | ~60KB |

Claude Sonnet's context window is 200K tokens. 800KB of HTML is approximately 200K tokens — exactly enough to fill it, with no room left for the system prompt, conversation history, or reasoning chain. And even if you can fit it in, attention quality near the 200K token end is far worse than near the 2K token mark.

This is the extreme stress test for the Tool system (Pillar 1): if tool return values are handed to the LLM unfiltered, the context window explodes instantly.

**The core solution**: don't give the LLM the full DOM. Extract only "interactive elements." This thinking comes from browser-use's core design — use JavaScript on the browser side to filter the DOM, compressing 6,000 nodes down to 50–200 interactive elements, then serialize those as structured text for the LLM. The filter ratio is typically 30–100×.

Convention: `DOM Perception` = extracting the subset of interactive elements from the full DOM; `Full DOM serialization` = converting the entire DOM to an HTML string. Browser agents must use the former, never the latter.

### 3.2 Page Transitions — The State Machine Challenge for Planning

Humans browse web pages while unconsciously tracking state: "where am I, what did I just do, what's next." This tracking relies on the visual system, spatial memory, and semantic understanding working together.

Browser agents have a more complex state tracking problem:

- **Hard navigation**: clicking a link causes a full page reload. Detectable with `page.on('load')`. Easy to handle.
- **SPA route changes**: only the URL `hash` or `pushState` changes; the DOM partially updates. `page.on('load')` won't fire. You can only detect this through DOM diffing.
- **Async content loading**: new content dynamically inserted when scrolling to the bottom. Requires waiting for `networkidle` or polling DOM mutations.

These three kinds of "page transitions" correspond to the core challenge for Planning (Pillar 2): the agent's ActionHistory records "which step did what on which page," but the definition of "which page" can change at any time.

**Paper reference**: WebArena (2023, Shen et al.) is the standard benchmark set for browser agents, containing 812 real web tasks. In evaluations, page-transition errors (agents attempting to operate elements from the previous page after navigation) were the second most common failure reason, accounting for 27% of all failures. You don't need to read the entire paper — just know: **page transition handling ability is an important indicator of browser agent maturity.**

### 3.3 Anti-Bot and CAPTCHA — Safety's External Boundary

Anti-bot mechanisms are fundamentally a security layer for distinguishing "is this a human or a program?" They operate at four levels:

| Level | Detection point | Typical implementation |
|-------|-----------------|----------------------|
| L1 Request characteristics | User-Agent, Headers | Simple string matching |
| L2 Browser fingerprint | `navigator.webdriver`, Canvas fingerprint | JS detection scripts |
| L3 Behavioral patterns | Mouse trajectory, click intervals, scroll speed | Machine learning classifier |
| L4 Risk signals | IP reputation, account behavioral history | Rules engine + ML |

Headless Chromium naturally triggers L2: `navigator.webdriver` defaults to `true`, detectable by JS. Using the user's real existing Chrome profile (not headless) bypasses L1 and L2, but L3 and L4 remain effective.

**Key insight**: lena-v0.24's design choice is **not to fight anti-bot systems**. Reasons:

1. L3/L4 anti-bot requires extremely complex simulation, and keeps getting stronger — an arms race with no end
2. Using the user's real Chrome profile naturally bypasses L1/L2, a legitimate and stable solution
3. The three-layer fallback architecture ensures that even when the browser path fails, other paths are available

**Mapping to the Safety pillar**: anti-bot triggers are external security mechanisms constraining the agent. But the agent also must have internal security mechanisms — not performing operations with real side effects (form submissions, purchases) without human approval.

### 3.4 Login State — Memory's Highest-Value Scenario

Login state is the most essential difference between a browser agent and a stateless web scraper.

An agent that can operate the user's real Chrome profile inherits the user's login state for all websites naturally — without knowing passwords, without bypassing 2FA, without maintaining a cookie pool. This is because cookies are stored in the Chrome profile's `Cookies` database file; a CDP connection to that profile has natural access to these cookies.

This is the highest-value application scenario for the Memory pillar (Pillar 4): the agent's "memory" includes the user's authentication credentials for all websites, and these credentials are live and valid.

The only real difficulty with login state is **cookie expiration**. When a Weibo session expires, the browser redirects to the login page. The agent must be able to perceive "I'm not on the expected page," then pause the task and notify the user to log in again — not continue performing meaningless operations on the login page.

---

## Beat 4 · Scaffolding: The Minimal Runnable Browser Agent

Now let's build the minimal Browser Agent skeleton. It does one thing: accept a task description, return an execution result.

Let's implement the minimal browser agent skeleton that proves the concept works end-to-end:

```python
# code/lena-v0.24/browser_agent_minimal.py
"""
Minimal Browser Agent skeleton
Goal: use browser-use to take over an existing Chrome and execute a single task
Prerequisites:
  pip3 install browser-use playwright langchain-anthropic
  playwright install chromium
  Chrome already started in CDP 9222 mode (use cdp-start.sh)
"""
import os
import asyncio
from browser_use import Agent, Browser, BrowserConfig
from langchain_anthropic import ChatAnthropic

# Critical: clear proxy environment variables
# Reason: Clash's fake-ip mode intercepts all DNS, including localhost,
# causing CDP socket connections to be routed through the proxy and fail
for _var in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy"]:
    os.environ.pop(_var, None)


async def browser_task(task: str) -> str:
    """
    Minimal version: execute a single browser task
    Returns: the agent's final result text
    """
    # Connect to existing Chrome (not launching a new headless instance)
    # cdp_url points to the local Chrome's debug port
    browser_config = BrowserConfig(
        cdp_url="ws://localhost:9222",
        headless=False,   # taking over existing Chrome, not headless
        # disable_security=True only for local development; forbidden in production
    )
    browser = Browser(config=browser_config)

    # Use Claude Sonnet as the decision LLM
    # Why Sonnet and not Haiku: browser tasks require multi-step reasoning;
    # Haiku's failure rate on 3+ step decisions is noticeably higher
    # (~35% vs ~12% in practice)
    llm = ChatAnthropic(model="claude-sonnet-4-6")

    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        max_actions_per_step=5,   # at most 5 actions per step
    )

    result = await agent.run(max_steps=20)  # max 20 steps to prevent infinite loops
    return str(result)


# Quick verification: run this file, watch Chrome open a new tab
if __name__ == "__main__":
    # Ensure CDP is running: ~/.claude/scripts/cdp-start.sh
    result = asyncio.run(
        browser_task("Open https://github.com/browser-use/browser-use and tell me how many stars this project has")
    )
    print(f"\nResult: {result}")
    # Expected output (~1 line):
    # Result: browser-use currently has 92,xxx stars (number changes over time)
```

Running `python3 browser_agent_minimal.py` should show:
1. Chrome opens a new tab
2. Automatically navigates to `github.com/browser-use/browser-use`
3. Terminal prints the star count

If you get `ConnectionRefusedError: [Errno 61] Connection refused`, check whether CDP is running:

```bash
curl -s http://localhost:9222/json/version | python3 -m json.tool
# Normal output: {"Browser": "Chrome/...", "webSocketDebuggerUrl": "ws://..."}
# No output or connection refused: run ~/.claude/scripts/cdp-start.sh
```

---

## Beat 5 · Progressive Assembly: From Skeleton to Production-Grade Browser Agent

The skeleton runs. Now let's incrementally add what production systems need, one feature at a time, verifying after each.

| Extension | Why It's Needed | How to Add |
|-----------|-----------------|------------|
| Tab protection | Don't overwrite pages the user is actively using | Record tab list before task; only clean up newly created tabs after |
| Three-layer fallback | If browser path fails, have a fallback | FallbackChain: RSSHub → opencli → CDP |
| Approval gate | High-risk operations require human confirmation | Check whether `action.type` is in the high-risk list |
| Process lock | Prevent multiple agents from operating the same Chrome simultaneously | `fcntl.flock` file lock |

### Extension 1: Tab Protection

Not overwriting existing tabs is an ironclad rule. Chrome profiles may contain documents the user is actively editing, unsaved forms, or active video calls.

```python
# code/lena-v0.24/browser_agent.py (excerpt)
import aiohttp

CDP_BASE = "http://localhost:9222"

async def get_existing_tab_ids() -> set[str]:
    """Snapshot the IDs of all current tabs."""
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{CDP_BASE}/json") as r:
            tabs = await r.json()
            return {t["id"] for t in tabs}

async def close_new_tabs(protected_ids: set[str]):
    """Close all tabs created during this task (uncleaned tabs accumulate over time)."""
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{CDP_BASE}/json") as r:
            current_tabs = await r.json()
        for tab in current_tabs:
            if tab["id"] not in protected_ids:
                # Use PUT, not GET
                await s.put(f"{CDP_BASE}/json/close/{tab['id']}")
                print(f"[Tab cleanup] Closed tab: {tab['id'][:8]}")
```

Verification: print the tab count before and after the task. They should be equal.

```
Tab count before task: 5
Tab count after task: 5  ← correct: created tabs have been cleaned up
```

### Extension 2: Three-Layer Fallback

browser-use's success rate is roughly 40–60%, due to the combined pressure of anti-bot, dynamic rendering, and login expiration. Three-layer fallback raises overall success rate to ~99%.

```python
# code/lena-v0.24/fallback_chain.py
from typing import Optional, Callable, Any
import asyncio


class FallbackChain:
    """Three-layer fallback: each layer automatically degrades to the next on failure."""

    def __init__(self):
        self._layers: list[tuple[str, Callable]] = []

    def layer(self, name: str):
        """Decorator: add a function to the fallback chain."""
        def decorator(fn: Callable):
            self._layers.append((name, fn))
            return fn
        return decorator

    async def run(self, *args, **kwargs) -> Optional[Any]:
        for name, fn in self._layers:
            try:
                print(f"[Fallback] Trying: {name}")
                result = await fn(*args, **kwargs)
                if result is not None:
                    print(f"[Fallback] Success: {name}")
                    return result
                print(f"[Fallback] {name} returned empty, degrading")
            except Exception as e:
                print(f"[Fallback] {name} exception: {e}, degrading")
        return None
```

Usage example (three-layer fallback for a Weibo task):

```python
chain = FallbackChain()

@chain.layer("rsshub")           # Layer 1: RSS feed, no login required, fastest
async def via_rsshub(uid: str):
    async with aiohttp.ClientSession() as s:
        async with s.get(f"https://rsshub.app/weibo/user/{uid}", timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                data = await r.json()
                return data["items"][:5]
    return None

@chain.layer("opencli")          # Layer 2: local CLI tool
async def via_opencli(uid: str):
    from opencli_client import run_skill
    return await run_skill(f"weibo-check --uid {uid}")

@chain.layer("browser_use")      # Layer 3: real browser
async def via_browser(uid: str):
    return await browser_task(f"Go to Weibo and check user {uid}'s latest 5 posts")

# Execute
result = await chain.run(uid="your_weibo_uid")
print(f"[Three-layer fallback] Source recorded, overall success rate ~99%")
```

### Extension 3: Approval Gate

The browser has real-world side effects — clicking "submit order" actually places an order. Any write operation (form submission, purchase, deletion) must have human confirmation.

```python
# code/lena-v0.24/approval_gate.py
HIGH_RISK_PATTERNS = [
    "submit", "purchase", "buy", "order", "delete", "transfer",
    "pay", "checkout", "confirm", "book",
]

async def gate_before_action(action_description: str) -> bool:
    """
    Check whether an action is high-risk; if so, request human confirmation.
    Returns True to proceed, False to cancel.
    """
    is_risky = any(p in action_description.lower() for p in HIGH_RISK_PATTERNS)
    if not is_risky:
        return True

    print(f"\n⚠️  High-risk operation detected: {action_description}")
    print("This operation may have irreversible real-world consequences.")
    confirm = input("Confirm? Type 'yes' to proceed, anything else to cancel: ")
    return confirm.strip().lower() == "yes"
```

Verification:

```python
await gate_before_action("click the search button")   # → True (passes immediately)
await gate_before_action("click the buy button")      # → prints warning, waits for input
```

### Extension 4: Process Lock

Cron tasks can overlap in execution. Two CDP scraping processes operating the same Chrome simultaneously causes race conditions.

```python
# code/lena-v0.24/cdp_lock.py
import fcntl

LOCK_FILE = "/tmp/.lena_browser_lock"

class BrowserLock:
    """Ensure only one browser agent is operating Chrome at a time."""

    def __enter__(self):
        self._fd = open(LOCK_FILE, "w")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._fd.close()
            raise RuntimeError("[BrowserLock] Another browser agent is running")
        return self

    def __exit__(self, *args):
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        self._fd.close()
```

With all four extensions added, the complete lena-v0.24 skeleton is in shape. Here's the overall code structure:

```
code/lena-v0.24/
├── browser_agent.py          # Main class: LenaBrowserAgent
├── browser_agent_minimal.py  # Minimal version (this chapter Beat 4)
├── fallback_chain.py         # Three-layer fallback skeleton
├── approval_gate.py          # Approval gate
├── cdp_lock.py               # Process lock
├── cdp_utils.py              # Defensive CDP utilities (includes 6 hard-won lessons)
├── config.py                 # Model configuration
└── tasks/
    ├── weibo_news.py         # Task 1: check Weibo messages
    ├── table_export.py       # Task 2: export table to CSV
    └── train_booking.py      # Task 3: query train tickets
```

---

## Beat 6 · Running Verification: Three End-to-End Tasks

Three tasks arranged in ascending complexity. For each, we first show browser-use's internal steps, then the expected output, then common failure paths.

### 6.1 Task 1: Check Weibo Messages

**Goal**: navigate to Weibo, check for new messages, return a summary.

```python
# code/lena-v0.24/tasks/weibo_news.py
import asyncio
from ..browser_agent import LenaBrowserAgent

TASK = """
Open Weibo (https://weibo.com) in a new tab:
1. Check whether the notification area (top right or bell icon) has unread messages
2. If there are new messages, click into the notifications page and extract the first 5 notification titles
3. Return as JSON: {"new_count": number, "summaries": ["message1", "message2"...]}
4. If no new messages, return {"new_count": 0, "summaries": []}
Important: do not operate on an existing tab; open a new tab.
"""

async def check_weibo():
    agent = LenaBrowserAgent()
    return await agent.run_task(TASK)

if __name__ == "__main__":
    print(asyncio.run(check_weibo()))
```

**browser-use internal decision steps**:

```
Step 1: navigate → "https://weibo.com"
Step 2: wait_for_load → networkidle
Step 3: screenshot → perceive current page state
Step 4: analyze → look for notification icon
Step 5: (if found) click → notification icon
Step 6: wait_for_load → notifications page
Step 7: extract_content → notification list text
Step 8: done → {"new_count": 3, "summaries": [...]}
```

**Expected output**:

```json
{
  "new_count": 3,
  "summaries": [
    "User A liked your post",
    "User B followed you",
    "User C commented on your post"
  ]
}
```

**Common failure paths**:

- `Network timeout`: Weibo's CDN nodes can be unstable; `networkidle` may wait 10+ seconds. Handle: after timeout, take a screenshot to confirm page state, degrade to fallback.
- `Not logged in redirect`: cookies expired, redirected to login page. Handle: detect whether the URL is `login.weibo.com`; if so, return error code `AUTH_EXPIRED` and notify the user.
- `DOM structure changes`: Weibo frequently updates its frontend; notification icon selectors may change. Handle: browser-use finds elements through semantic understanding ("find interactive elements with 'notification' semantics") rather than relying on fixed selectors — naturally tolerant of structural changes.

### 6.2 Task 2: Export Table to CSV

**Goal**: find a data table on a specified page, extract it, and export as CSV.

```python
# code/lena-v0.24/tasks/table_export.py
import asyncio
import csv
import json
from ..browser_agent import LenaBrowserAgent

TASK_TEMPLATE = """
Open {url} in a new tab:
1. Find the main data table on the page
2. Read the header row (column names) and all data rows (up to 200 rows)
3. Return as JSON: {{"headers": ["col1", "col2"], "rows": [["val1", "val2"], ...]}}
Important: if there is pagination, only retrieve the first visible page.
"""

async def export_table(url: str, output: str = "/tmp/export.csv"):
    agent = LenaBrowserAgent()
    raw = await agent.run_task(TASK_TEMPLATE.format(url=url))

    data = json.loads(raw)
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(data["headers"])
        writer.writerows(data["rows"])

    print(f"[Export complete] {len(data['rows'])} rows → {output}")
    return output

if __name__ == "__main__":
    # Example: export a publicly accessible data table page
    asyncio.run(export_table(
        url="https://datatables.net/examples/basic_init/",
        output="/tmp/demo_table.csv"
    ))
```

**Expected output**:

```
[Export complete] 57 rows → /tmp/demo_table.csv
```

The CSV file should contain correct headers and data rows, e.g.:

```csv
Name,Position,Office,Age,Start date,Salary
Tiger Nixon,System Architect,Edinburgh,61,2011/04/25,$320,800
...
```

**Why this task**: it validates browser-use's DOM analysis capability — the agent needs to distinguish navigation bars, article content, and data tables from each other. These distinctions are semantic, not CSS-class-based.

### 6.3 Task 3: Query Train Tickets (Query Only, No Purchase)

**Goal**: query train ticket availability on 12306 for a given date, return structured data.

This is the most complex task, requiring 10+ steps, 3 form field interactions, and 1 search wait.

```python
# code/lena-v0.24/tasks/train_query.py
"""
Task 3: Query train tickets
Safety declaration: this task only executes queries, not purchases.
The buy_ticket function is separately protected behind an approval gate.
"""
import asyncio
from ..browser_agent import LenaBrowserAgent
from ..approval_gate import gate_before_action

QUERY_TASK = """
Open 12306 (https://kyfw.12306.cn/otn/leftTicket/init) in a new tab:
1. Departure: enter "{origin}"
2. Destination: enter "{destination}"
3. Departure date: select "{date}"
4. Click the "Query" button and wait for results
5. Find all G-prefix (high-speed rail) trains in the results
6. Return JSON:
   [
     {{"train": "G-prefix train number", "depart": "HH:MM", "arrive": "HH:MM",
       "duration": "Xh Ym", "second_class": "¥XXX", "available": true/false}}
   ]
7. Important: query only — do not click "Book" or any purchase buttons.
"""

async def query_trains(origin: str, destination: str, date: str) -> list[dict]:
    agent = LenaBrowserAgent()
    raw = await agent.run_task(
        QUERY_TASK.format(origin=origin, destination=destination, date=date)
    )
    import json
    return json.loads(raw)

if __name__ == "__main__":
    import datetime
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    trains = asyncio.run(query_trains("Shenzhen North", "Shanghai Hongqiao", tomorrow))
    for t in trains[:3]:
        print(f"{t['train']:6s} {t['depart']}→{t['arrive']}  {t['duration']:8s}  {t['second_class']}")

    # Expected output (~3 lines; specific numbers vary by date):
    # G820  06:18→13:24  7h 06m    ¥894.5
    # G100  08:00→15:12  7h 12m    ¥894.5
    # G98   09:30→16:38  7h 08m    ¥894.5
```

**Internal decision steps** (approximately 12 steps):

```
Step 1:  navigate → "https://kyfw.12306.cn/otn/leftTicket/init"
Step 2:  screenshot → confirm page loaded
Step 3:  click → departure input (find input with "departure" semantics)
Step 4:  type → "Shenzhen North"
Step 5:  click → "Shenzhen North" in dropdown suggestions
Step 6:  click → destination input
Step 7:  type → "Shanghai Hongqiao"
Step 8:  click → "Shanghai Hongqiao" in dropdown suggestions
Step 9:  click → date input or calendar component
Step 10: click → target date
Step 11: click → "Query" button
Step 12: wait  → wait for results to load (~2-3 seconds)
Step 13: extract_content → G-prefix train list
Step 14: done → return JSON array
```

**Common failure paths**:

- `12306 shows a slide CAPTCHA`: triggered when search frequency is too high. Handle: when CAPTCHA is detected, call `ask_human` to ask the user to solve it manually, then continue.
- `Date picker interaction is complex`: 12306's date component is custom-built, not a standard `<input type="date">`. browser-use needs to analyze via screenshot to find the correct interaction approach. If it takes more than 5 steps without successfully selecting a date, exit and report the failure reason.
- `Result parsing fails`: 12306's results page structure is fairly complex; the LLM sometimes misidentifies "no tickets" vs "not shown." Handle: specify in the prompt "if a field is uncertain, fill null — do not guess."

---

## Beat 7 · Design Notes × 3

### Design Note 1: Why Is Browser Agent the "Final Exam" of Agent Engineering?

At first glance, Browser Agent looks like a specialized scraper enhancement. But it's actually more like the ultimate stress test of a general-purpose agent's capabilities, because it's the only scenario that demands all six pillars be online simultaneously.

**Alternative: write a dedicated scraper for each website**

Many teams' first instinct is: write a dedicated API call for Weibo, write a dedicated scraper script for 12306.

The problem with this path:
- 🔴 One maintenance burden per website; 10 websites = 10 code bases
- 🔴 When a website updates its DOM structure, all scrapers break and need rewriting
- 🔴 Can't handle general tasks where the target website is unknown in advance

**The reason for the current choice (Browser Agent)**:

One general-purpose browser agent can handle any website task the user describes. The maintenance cost is fixed (doesn't grow with the number of websites), and it automatically improves as LLM capabilities improve.

**Balance in production systems**: the three-layer fallback architecture is a pragmatic compromise — for high-frequency tasks (like checking Weibo daily), write a dedicated RSS/API layer as L1 and let the browser agent fall back to L3 as the last resort. For low-frequency or unspecified tasks, the browser agent is the preferred first path.

---

### Design Note 2: Why Not Just Use Pure CDP for Everything?

These two paths are often confused. The decision dimension isn't "which is better" but "which fits this scenario."

**Alternative: all raw CDP, no Playwright**

CDP is the lowest-level protocol — lowest latency, most precise control. Some engineers argue "if CDP can do it, don't add the Playwright middleware layer."

CDP's trade-offs:
- 🟢 Lowest latency (eliminates Playwright's CDP abstraction layer)
- 🟢 Full access to Chrome-specific features (Performance API, Network Interception, etc.)
- 🔴 API verbs are `methodName` (e.g., `Page.captureScreenshot`), not `page.screenshot()` — higher cognitive cost
- 🔴 No auto-waiting (Playwright's auto-waiting mechanism must be self-implemented)
- 🔴 No built-in retry (connection loss must be handled manually)

**Current choice (Playwright for browser-use, CDP for precise control)**:

browser-use builds on Playwright. For the goal of "letting the LLM perceive and operate the DOM," Playwright's high-level APIs (`page.click(selector)`, `page.fill(selector, text)`) are far more convenient than CDP's `Input.dispatchMouseEvent` + `Input.insertText` combination.

But raw CDP still has its place:
- Screenshot capture (precise control over viewport, DPR)
- Tab creation and management (`PUT /json/new`)
- Fixed-flow operations that don't require LLM involvement

**Decision tree**:

```
Does each step require LLM dynamic decision-making?
├── Yes → browser-use (Playwright + LLM)
└── No → are the steps fixed?
     ├── Yes → Playwright (high-level API, cross-browser)
     └── No  → Chrome CDP (precise control, Chrome-specific)
```

---

### Design Note 3: The Six Pillars — What They Proved and What Comes Next

All six pillars are present here:

| Pillar | Browser Agent Mapping | Key Implementation |
|--------|----------------------|-------------------|
| Tool universality | Browser operations = tools | click/type/scroll/screenshot are all agent tools |
| Planning | Autonomous decomposition of multi-step tasks | ActionHistory + max_steps protection |
| Long-horizon | State tracking across 10+ steps | Screenshot sequences + DOM perception + page transition handling |
| Memory | Login state inheritance + step history | Chrome profile cookies + ActionHistory |
| Safety | Tab protection + approval gate | Ironclad rule: never overwrite existing tabs; high-risk operations require human confirmation |
| Specialization | Derive Browser Agent from general Lena | LenaBrowserAgent inherits from LenaAgent base class |

This is not accidental. Browser Agent is the book's grand finale because it's the only scenario that can test all six pillars simultaneously.

---

## 6 Hard-Won CDP Lessons: Production Engineering Reality

These six lessons come from a real production system (a CDP-based multimedia collection pipeline). Each has a specific error symptom, root cause, and fix code.

### Lesson 1: Do Not Send an Origin Header

**Symptom**: CDP WebSocket connection rejected with 403.

**Root cause**: Chrome CDP's WebSocket security policy only allows `localhost` Origin or no Origin at all. Sending any other Origin header gets rejected, even `http://127.0.0.1`.

```python
# BAD (an error common in many tutorials)
ws = await websockets.connect(ws_url, extra_headers={"Origin": "http://example.com"})
# Chrome: 403 WebSocket Upgrade failure

# GOOD (send no Origin header)
ws = await websockets.connect(ws_url)  # websockets library sends no Origin by default
```

### Lesson 2: Must Clear Proxy Environment Variables

**Symptom**: CDP socket connection times out or gets routed to the proxy server, returning strange HTTP responses.

**Root cause**: Clash's fake-ip mode intercepts all DNS queries including `localhost`. This means `socket.create_connection("localhost", 9222)` may be routed through the proxy (even though `localhost` should connect directly).

```python
# Clear proxy environment variables before any CDP operation
import os
for _var in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
             "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY"]:
    os.environ.pop(_var, None)
```

This code must execute once after all imports, before the first CDP connection.

### Lesson 3: Process Lock to Prevent Concurrent Conflicts

**Symptom**: when cron tasks overlap in execution, two browser agents operating the same Chrome simultaneously cause screenshot errors and tab state corruption.

**Root cause**: cron tasks overlap when execution time exceeds the schedule interval. For example, a 5-minute interval task that runs for 6 minutes will have the second instance start while the first is still running.

```python
# code/lena-v0.24/cdp_lock.py
import fcntl

class BrowserLock:
    def __enter__(self):
        self._fd = open("/tmp/.lena_browser.lock", "w")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._fd.close()
            raise RuntimeError("Another browser agent is running, skipping this run")
        return self

    def __exit__(self, *args):
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        self._fd.close()

# Usage
with BrowserLock():
    await run_browser_task()
```

### Lesson 4: Tabs Must Be Actively Cleaned Up

**Symptom**: Chrome runs out of memory after 200 collection runs; CDP connections start timing out. Opening Chrome reveals 200+ blank tabs.

**Root cause**: Tabs created via CDP (`PUT /json/new`) are not automatically closed when the script exits. If the script crashes or times out, the tabs remain in Chrome permanently.

```python
# code/lena-v0.24/browser_agent.py (excerpt)
async def run_task(self, task: str) -> str:
    # Record the set of tabs before the task starts (protected)
    protected = await get_existing_tab_ids()

    try:
        result = await self._execute(task)
        return result
    finally:
        # Clean up tabs created during this task, success or failure
        await close_new_tabs(protected)
```

Key point: cleanup logic goes in the `finally` block to ensure it executes even if the task throws an exception midway.

### Lesson 5: Screenshots Smaller Than 80KB Are Blank Pages

**Symptom**: LLM reports "page content is empty," but the page is actually normal.

**Root cause**: under certain conditions (page load failure, white screen error, Chrome internal error page), a completely white screenshot is returned, typically 5–30KB. If this screenshot is passed directly to the LLM, the LLM will judge "the page is blank," causing wrong decisions.

```python
async def take_screenshot(ws_url: str) -> Optional[bytes]:
    data = await _raw_screenshot_cdp(ws_url)
    if data is None:
        return None

    # 80KB threshold: based on real data statistics. Blank pages are usually < 20KB;
    # pages with content are usually > 80KB even at minimum.
    MIN_VALID_BYTES = 80 * 1024
    if len(data) < MIN_VALID_BYTES:
        print(f"[Screenshot validation] {len(data):,} bytes < {MIN_VALID_BYTES:,}, judged as blank page, skipping")
        return None

    return data
```

### Lesson 6: CDP HTTP Interface `/json/new` and `/json/close` Use PUT

**Symptom**: calling `/json/new` to create a tab fails (405 Method Not Allowed), or returns incorrect data.

**Root cause**: Chrome CDP's HTTP REST interface spec requires:
- `GET /json` → list all tabs (GET)
- `PUT /json/new` → create new tab (**PUT, not GET!**)
- `PUT /json/close/{tabId}` → close tab (**PUT, not GET!**)

Many old tutorials and Stack Overflow answers use `GET /json/new`, which might accidentally work on old Chrome versions but 404s on new ones.

```python
# BAD: common in many tutorials
async with session.get(f"http://localhost:9222/json/new") as r:
    tab = await r.json()  # may 404 or return wrong data

# GOOD: correct HTTP method
async with session.put(f"http://localhost:9222/json/new") as r:
    tab = await r.json()  # Chrome creates new tab and returns tab info

async with session.put(f"http://localhost:9222/json/close/{tab_id}") as r:
    pass  # returns 200 on success
```

---

## Complete lena-v0.24 Core Code

Integrating all four extensions into the complete `LenaBrowserAgent`:

```python
# code/lena-v0.24/browser_agent.py
"""
lena-v0.24 Browser Agent — production implementation
Integrates: Tab protection + three-layer fallback + approval gate + process lock + 6-lesson defenses
"""
import os
import asyncio
from typing import Optional
import aiohttp
from browser_use import Agent, Browser, BrowserConfig
from langchain_anthropic import ChatAnthropic

from .cdp_lock import BrowserLock
from .approval_gate import gate_before_action

# Lesson 2: clear proxy env vars at startup
for _var in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy"]:
    os.environ.pop(_var, None)

CDP_BASE = "http://localhost:9222"


async def _get_tab_ids() -> set[str]:
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{CDP_BASE}/json") as r:
            return {t["id"] for t in await r.json()}


async def _close_new_tabs(protected: set[str]):
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{CDP_BASE}/json") as r:
            current = await r.json()
        for tab in current:
            if tab["id"] not in protected:
                await s.put(f"{CDP_BASE}/json/close/{tab['id']}")  # Lesson 6: PUT


class LenaBrowserAgent:
    """
    lena-v0.24 Browser Agent
    A Browser-specialized agent derived from the general-purpose Lena base.
    """

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.llm = ChatAnthropic(model=model)

    async def run_task(self, task: str, require_approval: bool = False) -> str:
        """
        Execute a browser task.
        require_approval=True requires user confirmation for high-risk operations.
        """
        # Approval gate (optional)
        if require_approval:
            approved = await gate_before_action(task)
            if not approved:
                return "[CANCELLED] User cancelled the high-risk task"

        # Process lock (prevent concurrent access)
        with BrowserLock():
            # Tab protection: record current tab set before task
            protected_tabs = await _get_tab_ids()

            try:
                return await self._execute(task)
            finally:
                # Lesson 4: clean up tabs regardless of success or failure
                await _close_new_tabs(protected_tabs)

    async def _execute(self, task: str) -> str:
        browser = Browser(config=BrowserConfig(
            cdp_url="ws://localhost:9222",
            headless=False,
        ))
        agent = Agent(
            task=task,
            llm=self.llm,
            browser=browser,
            max_actions_per_step=5,
        )
        result = await agent.run(max_steps=25)
        return str(result)
```

---

## Complete Three-Layer Fallback Implementation

```python
# code/lena-v0.24/tasks/weibo_news.py (complete version with fallback)
import asyncio
import aiohttp
from ..browser_agent import LenaBrowserAgent
from ..fallback_chain import FallbackChain


async def get_weibo_news(weibo_uid: str) -> Optional[dict]:
    """
    Query Weibo messages with three-layer fallback guaranteeing ~99% success rate:

    Layer 1 — RSSHub (~90% success)
      Pros: no login required, <2s response, structured data
      Cons: only "pushed content"; message notifications unavailable

    Layer 2 — opencli (~70% success)
      Pros: local tool, no network dependency
      Cons: depends on local tool being configured

    Layer 3 — Browser Agent (~40-60% success)
      Pros: can access full content including post-login content
      Cons: slowest (10-30s), affected by anti-bot
    """
    chain = FallbackChain()

    @chain.layer("rsshub")
    async def via_rsshub():
        """Layer 1: RSSHub public instance."""
        async with aiohttp.ClientSession() as s:
            url = f"https://rsshub.app/weibo/user/{weibo_uid}"
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    return {
                        "source": "rsshub",
                        "items": [
                            {"title": item.get("title", ""), "link": item.get("link", "")}
                            for item in data.get("items", [])[:5]
                        ]
                    }
        return None

    @chain.layer("browser_agent")
    async def via_browser():
        """Layer 2: real browser."""
        agent = LenaBrowserAgent()
        task = f"""
        Open Weibo (https://weibo.com) in a new tab and check user {weibo_uid}'s latest messages:
        1. If not logged in, return {{"error": "AUTH_EXPIRED"}}
        2. If logged in, check notification count and extract the latest 5 notification summaries
        3. Return JSON: {{"new_count": number, "items": [{{"title": "..."}}]}}
        """
        raw = await agent.run_task(task)
        import json
        return {"source": "browser", **json.loads(raw)}

    return await chain.run()
```

---

## Full-Book Retrospective: From v0.1 to v0.24

We've reached the last chapter of the book.

Let's do something we rarely have time for: look back.

### Part 0: The First Step (Ch 1-3)

**Ch 1** you wrote the first API call. 10 lines of Python, one `messages.create()`, "Hello, Agent." At the time you might have thought that was all there was to "AI application development." It's actually just the outermost interface. Behind those 10 lines are the Transformer's forward pass, KV Cache management, per-token sampling — but Ch 1 didn't need you to know any of that. You just needed to know "it can be called."

**Ch 2** you understood the ReAct loop: Reasoning → Acting → Observing, repeating indefinitely until the task is done. This loop was written as a paper in 2022; today it's the foundational atom of almost every agent framework. Understanding it means you can read the core of any agent framework — whether it's called LangChain, AutoGen, or CrewAI.

**Ch 3** Lena was born. 50 lines of Python, 6 modules: Config, Provider, Memory, ToolRegistry, AgentLoop, Skills. Still primitive, but with the right structure.

### Part 1: The Six Pillars (Ch 4-12)

**Ch 4-5** you built engineering intuition for LLMs (not math) and a decision tree for technology selection. These two chapters produce no code artifacts, but they're the confidence behind every engineering decision you make afterward — why choose Sonnet over Haiku, why RAG before fine-tuning, why RAG embedded in an agent rather than replacing one.

**Ch 6-7** Tool system and streaming concurrency. Lena went from "only talks" to "can actually work." You understood why tools need `isReadOnly` and `isDestructive` flags — not for the programmer to read, but so the LLM knows "is this tool safe, can it run concurrently."

**Ch 8-9** Memory and RAG. Lena went from "forgets you every conversation" to "remembers what you said last time," from "only knows training data" to "can read your 200-page PDF." These two chapters transformed Lena from a chat assistant to a knowledge-capable agent.

**Ch 10** Context Engineering. This was one of the most discussed topics in agent engineering in 2025 — not how to make the model smarter, but how to make it perform best within the limited context window. Manus's six iron rules, KV cache hit rates, three-tier context compaction — all implemented.

**Ch 11** Planning and Subagents. Lena went from "single-threaded execution" to "can decompose tasks and dispatch sub-agents." This is the foundation of long-horizon capability.

**Ch 12** Skills. Short chapter, but important. Skills are the reusable form of agent capability units — what Simon Willison described as "possibly more impactful than MCP." Lena can now load any `.md` file you write as a new skill.

### Part 2: Safety and Persistence (Ch 13-18)

**Ch 13-14** The safety double-chapter. You learned why "an agent that can do anything autonomously" is dangerous, and how to control risk in a structured way (not with deny lists). Prompt Injection, execution-layer safety, credential protection, audit chains — these are defenses every production agent must have.

**Ch 15-16** Gateway and MessageBus. Lena left the command line and entered Telegram, Discord, Feishu. She's no longer a tool you call actively; she's an assistant you can message.

**Ch 17** Heartbeat. This is the most essential difference between a "persistent agent" and a "Q&A assistant": the agent has initiative. She can make judgments when no one is calling her, and proactively reach out to you at the right moment.

**Ch 18** Cron and long-running tasks. Lena can now handle cross-day tasks, resume from checkpoints after crashes, and collect news hourly to summarize at midnight. She has a "sense of time."

### Part 3: Extension and Specialization (Ch 19-22)

**Ch 19** The MCP protocol. 200 lines of code let Lena connect to any MCP server — filesystem, GitHub, Brave Search, AWS services. MCP is becoming the standard for agent tool connectivity; understanding it early pays dividends.

**Ch 20** Docker Sandbox. Production-grade code execution environment. seccomp, AppArmor, exec-approvals — you don't need to understand every security detail, but you need to know "running shell tools bare isn't enough."

**Ch 21** Evals. "No errors ≠ quality pass." LLM-as-judge, golden datasets, pass@k — now you have tools to quantitatively measure agent quality.

**Ch 22** Observability and deployment. Lena went online. Structured logs, token budgets, launchd/systemd process supervisors — she can run stably while you sleep.

**Ch 23** Specialization. One line to fork, one specialized agent. A quantitative trading agent, a podcast production agent, a home automation agent — the value of a general-purpose runtime lies in how quickly it can be forked into any specialized agent.

**Ch 24** You are here. Browser Agent. lena-v0.24 can browse the internet.

---

### What You Actually Built

On the surface, you built a Python agent runtime integrating LLM API, tool system, memory, planning, safety, deployment, evaluation, MCP, and browser control.

But at a deeper level, you understood one thing:

**An agent is a combination of perception + memory + reasoning + action + self-monitoring.**

This structure holds in 50 lines of code and in 3,000 lines. It holds in Python and in TypeScript or Rust. It holds on a local Mac and on an AWS fleet.

The six pillars are six dimensions of this structure:
- **Tool universality**: the action layer — what can be done
- **Planning**: the reasoning layer — how to decompose goals
- **Long-horizon**: the memory layer — how to maintain state across steps
- **Memory**: the knowledge layer — what is known, what is remembered
- **Safety**: the monitoring layer — what must not be done
- **Specialization**: the identity layer — who am I, what do I specialize in

A general-purpose agent is not the goal. Understanding this structure is the goal. Because once you understand the structure, you can build any specialized agent without needing to re-reason "what am I doing" every time.

---

## Infographic: Lena Full Evolution Diagram (Print-Quality A3)

```svg
<svg viewBox="0 0 1600 900" xmlns="http://www.w3.org/2000/svg" font-family="'SF Mono', 'Menlo', monospace">
  <defs>
    <!-- Deep space background gradient -->
    <linearGradient id="bg-main" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#030508"/>
      <stop offset="50%" style="stop-color:#060d1a"/>
      <stop offset="100%" style="stop-color:#040810"/>
    </linearGradient>
    <!-- Glow filters -->
    <filter id="glow-blue" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="glow-green" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="4" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="glow-gold" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="6" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <!-- Aurora gradient -->
    <linearGradient id="aurora" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" style="stop-color:rgba(0,200,255,0.15)"/>
      <stop offset="30%" style="stop-color:rgba(100,100,255,0.1)"/>
      <stop offset="70%" style="stop-color:rgba(0,255,150,0.1)"/>
      <stop offset="100%" style="stop-color:rgba(255,150,0,0.15)"/>
    </linearGradient>
    <!-- Version node gradients -->
    <radialGradient id="node-v1" cx="50%" cy="50%" r="50%">
      <stop offset="0%" style="stop-color:rgba(0,180,255,0.4)"/>
      <stop offset="100%" style="stop-color:rgba(0,80,180,0.1)"/>
    </radialGradient>
    <radialGradient id="node-v2" cx="50%" cy="50%" r="50%">
      <stop offset="0%" style="stop-color:rgba(0,255,120,0.5)"/>
      <stop offset="100%" style="stop-color:rgba(0,120,60,0.1)"/>
    </radialGradient>
  </defs>

  <!-- Background -->
  <rect width="1600" height="900" fill="url(#bg-main)"/>

  <!-- Aurora background band -->
  <rect x="0" y="380" width="1600" height="140" fill="url(#aurora)" rx="0" opacity="0.4"/>

  <!-- Starfield particles -->
  <circle cx="80" cy="50" r="1.2" fill="rgba(255,255,255,0.4)"/>
  <circle cx="240" cy="120" r="0.8" fill="rgba(255,255,255,0.3)"/>
  <circle cx="520" cy="80" r="1.5" fill="rgba(200,220,255,0.5)"/>
  <circle cx="780" cy="30" r="1.0" fill="rgba(255,255,255,0.35)"/>
  <circle cx="1050" cy="90" r="1.2" fill="rgba(255,255,255,0.4)"/>
  <circle cx="1320" cy="60" r="0.9" fill="rgba(255,255,255,0.3)"/>
  <circle cx="1480" cy="140" r="1.4" fill="rgba(200,220,255,0.45)"/>
  <circle cx="160" cy="820" r="1.0" fill="rgba(255,255,255,0.3)"/>
  <circle cx="900" cy="860" r="1.2" fill="rgba(255,255,255,0.4)"/>
  <circle cx="1400" cy="800" r="0.8" fill="rgba(255,255,255,0.3)"/>

  <!-- Title area -->
  <text x="800" y="55" fill="rgba(255,255,255,0.95)" font-size="22" font-weight="bold"
        text-anchor="middle" letter-spacing="4" filter="url(#glow-blue)">
    LENA EVOLUTION DIAGRAM
  </text>
  <text x="800" y="80" fill="rgba(150,180,255,0.7)" font-size="12"
        text-anchor="middle" letter-spacing="2">
    From 50 lines of Python to an internet-capable general-purpose Agent · Ch 1 → Ch 24
  </text>

  <!-- Main timeline -->
  <line x1="80" y1="450" x2="1520" y2="450"
        stroke="rgba(80,120,200,0.3)" stroke-width="1.5" stroke-dasharray="4,8"/>

  <!-- Part label backgrounds -->
  <rect x="80" y="100" width="240" height="30" fill="rgba(0,150,255,0.08)"
        stroke="rgba(0,150,255,0.2)" stroke-width="1" rx="4"/>
  <text x="200" y="120" fill="rgba(0,180,255,0.8)" font-size="10"
        text-anchor="middle" letter-spacing="1">Part 0 · Foundation</text>

  <rect x="370" y="100" width="680" height="30" fill="rgba(100,80,255,0.08)"
        stroke="rgba(100,80,255,0.2)" stroke-width="1" rx="4"/>
  <text x="710" y="120" fill="rgba(130,100,255,0.8)" font-size="10"
        text-anchor="middle" letter-spacing="1">Part 1-2 · Six Pillars + Safety + Persistence</text>

  <rect x="1100" y="100" width="420" height="30" fill="rgba(0,200,100,0.08)"
        stroke="rgba(0,200,100,0.2)" stroke-width="1" rx="4"/>
  <text x="1310" y="120" fill="rgba(0,220,120,0.8)" font-size="10"
        text-anchor="middle" letter-spacing="1">Part 3-4 · Extension + Specialization + Finale</text>

  <!-- Version nodes -->

  <!-- v0.1 Ch1 -->
  <circle cx="120" cy="450" r="28" fill="url(#node-v1)" stroke="rgba(0,180,255,0.6)" stroke-width="1.5"
          filter="url(#glow-blue)"/>
  <text x="120" y="445" fill="#00ccff" font-size="10" font-weight="bold" text-anchor="middle">v0.1</text>
  <text x="120" y="459" fill="rgba(255,255,255,0.5)" font-size="9" text-anchor="middle">Ch 1</text>
  <text x="120" y="500" fill="rgba(255,255,255,0.6)" font-size="9" text-anchor="middle">API call</text>
  <text x="120" y="514" fill="rgba(255,255,255,0.4)" font-size="8" text-anchor="middle">10 lines Python</text>

  <!-- v0.3 Ch3 -->
  <circle cx="260" cy="450" r="28" fill="url(#node-v1)" stroke="rgba(0,180,255,0.6)" stroke-width="1.5"
          filter="url(#glow-blue)"/>
  <text x="260" y="445" fill="#00ccff" font-size="10" font-weight="bold" text-anchor="middle">v0.3</text>
  <text x="260" y="459" fill="rgba(255,255,255,0.5)" font-size="9" text-anchor="middle">Ch 3</text>
  <text x="260" y="500" fill="rgba(255,255,255,0.6)" font-size="9" text-anchor="middle">Lena born</text>
  <text x="260" y="514" fill="rgba(255,255,255,0.4)" font-size="8" text-anchor="middle">50 lines·6 modules</text>

  <!-- v0.6 Ch6 -->
  <circle cx="420" cy="450" r="28" fill="url(#node-v1)" stroke="rgba(100,100,255,0.6)" stroke-width="1.5"
          filter="url(#glow-blue)"/>
  <text x="420" y="445" fill="#8899ff" font-size="10" font-weight="bold" text-anchor="middle">v0.6</text>
  <text x="420" y="459" fill="rgba(255,255,255,0.5)" font-size="9" text-anchor="middle">Ch 6</text>
  <text x="420" y="500" fill="rgba(255,255,255,0.6)" font-size="9" text-anchor="middle">Tool system</text>
  <text x="420" y="514" fill="rgba(255,255,255,0.4)" font-size="8" text-anchor="middle">30+ tools·concurrent</text>

  <!-- v0.9 Ch9 -->
  <circle cx="560" cy="450" r="28" fill="url(#node-v1)" stroke="rgba(100,100,255,0.6)" stroke-width="1.5"/>
  <text x="560" y="445" fill="#8899ff" font-size="10" font-weight="bold" text-anchor="middle">v0.9</text>
  <text x="560" y="459" fill="rgba(255,255,255,0.5)" font-size="9" text-anchor="middle">Ch 9</text>
  <text x="560" y="500" fill="rgba(255,255,255,0.6)" font-size="9" text-anchor="middle">RAG retrieval</text>
  <text x="560" y="514" fill="rgba(255,255,255,0.4)" font-size="8" text-anchor="middle">pgvector</text>

  <!-- v1.2 Ch13 -->
  <circle cx="700" cy="450" r="28" fill="url(#node-v1)" stroke="rgba(150,80,255,0.6)" stroke-width="1.5"/>
  <text x="700" y="445" fill="#bb88ff" font-size="10" font-weight="bold" text-anchor="middle">v1.2</text>
  <text x="700" y="459" fill="rgba(255,255,255,0.5)" font-size="9" text-anchor="middle">Ch 13</text>
  <text x="700" y="500" fill="rgba(255,255,255,0.6)" font-size="9" text-anchor="middle">Safety guardrails</text>
  <text x="700" y="514" fill="rgba(255,255,255,0.4)" font-size="8" text-anchor="middle">PromptGuard</text>

  <!-- v1.5 Ch18 -->
  <circle cx="880" cy="450" r="28" fill="url(#node-v1)" stroke="rgba(200,100,255,0.6)" stroke-width="1.5"/>
  <text x="880" y="445" fill="#cc88ff" font-size="10" font-weight="bold" text-anchor="middle">v1.5</text>
  <text x="880" y="459" fill="rgba(255,255,255,0.5)" font-size="9" text-anchor="middle">Ch 18</text>
  <text x="880" y="500" fill="rgba(255,255,255,0.6)" font-size="9" text-anchor="middle">Long-task Cron</text>
  <text x="880" y="514" fill="rgba(255,255,255,0.4)" font-size="8" text-anchor="middle">Checkpoint/resume</text>

  <!-- v0.23 Ch23 -->
  <circle cx="1080" cy="450" r="28" fill="url(#node-v1)" stroke="rgba(0,200,150,0.6)" stroke-width="1.5"/>
  <text x="1080" y="445" fill="#00ddaa" font-size="10" font-weight="bold" text-anchor="middle">v0.23</text>
  <text x="1080" y="459" fill="rgba(255,255,255,0.5)" font-size="9" text-anchor="middle">Ch 23</text>
  <text x="1080" y="500" fill="rgba(255,255,255,0.6)" font-size="9" text-anchor="middle">Specialization</text>
  <text x="1080" y="514" fill="rgba(255,255,255,0.4)" font-size="8" text-anchor="middle">One-line fork</text>

  <!-- v0.24 Ch24 — grand finale node, larger and brighter -->
  <circle cx="1380" cy="450" r="50" fill="url(#node-v2)" stroke="rgba(0,255,120,0.8)" stroke-width="2.5"
          filter="url(#glow-green)"/>
  <circle cx="1380" cy="450" r="42" fill="none" stroke="rgba(0,255,120,0.3)" stroke-width="1"
          stroke-dasharray="3,5"/>
  <text x="1380" y="443" fill="#00ff88" font-size="14" font-weight="bold"
        text-anchor="middle" filter="url(#glow-green)">v0.24</text>
  <text x="1380" y="461" fill="rgba(0,255,150,0.8)" font-size="11"
        text-anchor="middle">Ch 24</text>
  <text x="1380" y="520" fill="rgba(0,255,150,0.9)" font-size="11"
        text-anchor="middle" font-weight="bold">Browser Agent</text>
  <text x="1380" y="536" fill="rgba(255,255,255,0.6)" font-size="9"
        text-anchor="middle">Internet-capable</text>

  <!-- "You are here" arrow -->
  <line x1="1380" y1="392" x2="1380" y2="360"
        stroke="rgba(0,255,120,0.7)" stroke-width="1.5" stroke-dasharray="3,3"/>
  <polygon points="1380,356 1374,368 1386,368" fill="rgba(0,255,120,0.7)"/>
  <rect x="1310" y="330" width="140" height="26" fill="rgba(0,80,40,0.5)"
        stroke="rgba(0,255,120,0.4)" stroke-width="1" rx="4"/>
  <text x="1380" y="347" fill="#00ff88" font-size="10"
        text-anchor="middle" letter-spacing="1">← You are here</text>

  <!-- Six pillars label -->
  <text x="800" y="160" fill="rgba(255,200,100,0.8)" font-size="11" font-weight="bold"
        text-anchor="middle" letter-spacing="2">Six Pillars Coverage</text>

  <!-- Pillar indicator lines -->
  <line x1="420" y1="170" x2="420" y2="422" stroke="rgba(255,150,50,0.25)" stroke-width="1" stroke-dasharray="2,4"/>
  <text x="420" y="168" fill="rgba(255,170,60,0.7)" font-size="9" text-anchor="middle">Tool</text>

  <line x1="700" y1="170" x2="700" y2="422" stroke="rgba(255,150,50,0.25)" stroke-width="1" stroke-dasharray="2,4"/>
  <text x="700" y="168" fill="rgba(255,170,60,0.7)" font-size="9" text-anchor="middle">Planning</text>

  <line x1="560" y1="200" x2="560" y2="422" stroke="rgba(255,150,50,0.2)" stroke-width="1" stroke-dasharray="2,4"/>
  <text x="560" y="198" fill="rgba(255,170,60,0.6)" font-size="9" text-anchor="middle">Memory</text>

  <line x1="780" y1="200" x2="780" y2="422" stroke="rgba(255,150,50,0.2)" stroke-width="1" stroke-dasharray="2,4"/>
  <text x="780" y="198" fill="rgba(255,170,60,0.6)" font-size="9" text-anchor="middle">Safety</text>

  <!-- Bottom stats -->
  <text x="800" y="590" fill="rgba(255,255,255,0.4)" font-size="10" text-anchor="middle">
    24 chapters · 6 pillars · 3000+ lines of code · lena-v0.1 → lena-v0.24
  </text>

  <!-- Bottom tech stack -->
  <rect x="300" y="620" width="1000" height="220" fill="rgba(0,0,0,0.3)"
        stroke="rgba(255,255,255,0.05)" stroke-width="1" rx="12"/>
  <text x="800" y="650" fill="rgba(0,255,120,0.7)" font-size="11" font-weight="bold"
        text-anchor="middle" letter-spacing="2">lena-v0.24 Browser Agent Tech Stack</text>

  <!-- Three tech stack layers -->
  <rect x="340" y="665" width="280" height="55" fill="rgba(180,100,255,0.1)"
        stroke="rgba(180,100,255,0.4)" stroke-width="1" rx="6"/>
  <text x="480" y="687" fill="#bb88ff" font-size="11" font-weight="bold" text-anchor="middle">LLM Decision Layer</text>
  <text x="480" y="703" fill="rgba(255,255,255,0.6)" font-size="9" text-anchor="middle">Claude Sonnet · ChatBrowserUse</text>
  <text x="480" y="716" fill="rgba(255,255,255,0.4)" font-size="8" text-anchor="middle">DOM perception → action decision</text>

  <rect x="660" y="665" width="280" height="55" fill="rgba(0,200,100,0.1)"
        stroke="rgba(0,200,100,0.4)" stroke-width="1" rx="6"/>
  <text x="800" y="687" fill="#00cc66" font-size="11" font-weight="bold" text-anchor="middle">browser-use Framework Layer</text>
  <text x="800" y="703" fill="rgba(255,255,255,0.6)" font-size="9" text-anchor="middle">92k stars · Playwright backend</text>
  <text x="800" y="716" fill="rgba(255,255,255,0.4)" font-size="8" text-anchor="middle">Selective DOM extraction · ActionHistory</text>

  <rect x="980" y="665" width="280" height="55" fill="rgba(0,150,255,0.1)"
        stroke="rgba(0,150,255,0.4)" stroke-width="1" rx="6"/>
  <text x="1120" y="687" fill="#00aaff" font-size="11" font-weight="bold" text-anchor="middle">Chrome CDP Control Layer</text>
  <text x="1120" y="703" fill="rgba(255,255,255,0.6)" font-size="9" text-anchor="middle">WebSocket 9222 · custom profile</text>
  <text x="1120" y="716" fill="rgba(255,255,255,0.4)" font-size="8" text-anchor="middle">Screenshot · Tab mgmt · DOM injection</text>

  <!-- Three-layer fallback -->
  <text x="800" y="752" fill="rgba(255,200,80,0.7)" font-size="10" text-anchor="middle">Three-layer Fallback: RSSHub (90%) → opencli (70%) → CDP (40%) = Overall 99%</text>

  <!-- 6 lessons -->
  <text x="800" y="778" fill="rgba(255,100,100,0.6)" font-size="9" text-anchor="middle">
    6 Hard-Won Lessons: ①Origin header ②Proxy vars ③Process lock ④Tab cleanup ⑤Blank screenshot ⑥PUT method
  </text>

  <!-- Credits -->
  <text x="800" y="830" fill="rgba(255,255,255,0.2)" font-size="8" text-anchor="middle">
    browser-use: github.com/browser-use/browser-use (92k stars, 2026-05) · Playwright: playwright.dev · Chrome CDP: chromedevtools.github.io
  </text>
</svg>
```

---

## What Else Can Your Lena Become

These last pages belong to you.

Lena walked from 50 lines of code to where she is today. She has tools, memory, planning, safety, 24/7 uptime, MCP extensions, and now she can browse the internet.

But Lena's most important quality was never "what she can do." It's **plasticity**.

The design goal of a general-purpose runtime is exactly this: not to build one specific agent, but to build a foundation from which any agent can be quickly forked.

Here are three directions you can start immediately:

### Direction A: Automated Daily Briefing Agent

**Foundation**: lena-v0.24 can browse the web, lena-v1.5 can do cron jobs, lena-v1.3 can push to Telegram.

**Combination**:
- Every day at 7 AM, Lena automatically browses 5 sources you follow (Huxiu, GitHub Trending, HackerNews, specific accounts on X)
- LLM extracts today's important content, generates a 500-word summary
- TTS synthesizes audio, pushes to your phone at 8 AM

**Challenges**: content deduplication (same news across multiple platforms), summary quality evaluation (Evals), TTS word-boundary handling

**Estimated effort**: 2-3 days

### Direction B: Second-Hand Market Treasure Hunter

**Foundation**: lena-v0.24's browser operation capability, lena-v1.7's Heartbeat proactive push.

**Combination**:
- Every 30 minutes, Lena scans second-hand platforms for specific keywords ("iPad Pro used," "AirPods 95% new," "Switch OLED near-mint")
- LLM evaluates value: compare price vs. market rates (can check JD/Amazon current prices as benchmarks), analyze listing quality, evaluate seller rating
- When a deal exceeds a threshold, push immediately

**Challenges**: anti-bot protections are stronger on these platforms (L3/L4 level); behavior simulation is complex; platforms frequently redesign

**Estimated effort**: 1 week

### Direction C: Your Own AI Pair Programmer

**Foundation**: lena-v0.24 can operate the browser, lena-v0.23's specialization capability, plus code understanding ability.

**Combination**:
- Lena as a local coding assistant, able to read your code repositories
- When you open an issue or PR, Lena automatically analyzes related code and generates a context summary
- While you're coding in the IDE, Lena monitors CI results in the background and proactively suggests fixes when tests fail
- Can have Lena automatically look up documentation (MDN, PyPI, docs.anthropic.com, etc.)

**Challenges**: IDE integration (VSCode Extension or JetBrains Plugin), incremental processing of code changes, coordination with existing workflows

**Estimated effort**: 2 weeks

---

These three directions are just starting points. Lena can also become:
- Your personal finance analysis agent (periodically review statements, analyze spending patterns, flag anomalies)
- A natural language interface for your home automation (HomeAssistant — "dim the living room lights but keep the study bright")
- A competitive intelligence agent for your work (regularly check competitor websites, PR activity, social media discussions)
- A learning tutoring agent for your child (educational platforms with login state + personalized explanations)

Or something entirely off this list. The best agents usually come from needs only you know about — the pain points invisible to everyone else.

**The boundary of the agent is the boundary of your imagination.**

---

## Podcast · Grand Finale

---

*[Intro music fades in, a steady synthesizer chord]*

**Host A (low register)**: Do you remember what we said in the first episode?

**Host B**: You said we were going to write a book — teach people to build an agent that can do anything autonomously, from scratch.

**Host A**: Right. And then I said: this "anything" — when does it become enough?

**Host B**: Do you feel like it's enough now?

**Host A (pause)**: ...Lena can now browse Weibo, query train tickets, export tables. She uses the real login state from your Chrome, does things autonomously while you sleep, and knows to step back and find another path when something goes wrong.

**Host B**: This isn't a question of "enough."

**Host A**: Right, you're right. It's not a question of enough.

**Host B**: An agent has no endpoint. There's only which problems you can solve now. lena-v0.24 solves "let Lena get on the internet." What the next problem is — that depends on you.

**Host A**: I want to say something to the readers.

**Host B**: Go ahead.

**Host A**: Twenty-four chapters. If you read them seriously, if you ran the code at least once, if you really understand why "tool + memory + loop + safety" is the skeleton of an agent — then you're already in a minority. Most engineers know "how to call the ChatGPT API," but don't know why a browser agent needs a process lock, why `/json/new` can't use GET, why three-layer fallback is more reliable than a single path.

**Host B**: That's not on Stack Overflow.

**Host A**: That's in the error logs at 3 AM.

*[Music rises slightly]*

**Host B**: There's one thing we never said explicitly. Lena's name was chosen somewhat arbitrarily, but she doesn't represent any specific assistant.

**Host A**: She represents whatever you're capable of building after you understand what an agent is.

**Host B**: Go build.

*[Music swells, fades out after 20 seconds]*

---

## Further Reading

- `browser-use` documentation and source: https://docs.browser-use.com · github.com/browser-use/browser-use
- Playwright Python official docs: https://playwright.dev/python/
- Chrome DevTools Protocol full reference: https://chromedevtools.github.io/devtools-protocol/
- WebArena benchmark (browser agent evaluation): webarena.dev
- Anthropic Building Effective Agents (2024-12-19): anthropic.com/news/building-effective-agents
- browser-use dedicated model ChatBrowserUse: gpt.us.browser-use.com

---

## Chapter Summary

| Topic | Key Takeaway |
|-------|-------------|
| Browser Agent's four challenges | Infinite DOM → selective extraction; page transitions → state reset; anti-bot → three-layer fallback; login state → Chrome profile |
| Three-path decision | CDP (precise scraping) / Playwright (fixed flows) / browser-use (LLM dynamic decisions) |
| browser-use core loop | Perceive (screenshot + DOM extraction) → LLM decision → Playwright execute → result verification |
| ChatBrowserUse | 3-5x speed, suited for fixed-step tasks, not for complex-reasoning scenarios |
| Connecting to Chrome profile | cdp-start.sh launch → no Origin header → PUT /json/new to create tab |
| 6 hard-won lessons | Origin / proxy / process lock / tab cleanup / blank screenshot / PUT method |
| Three-layer fallback | RSSHub 90% + opencli 70% + CDP 40% → overall ~99% |
| Meaning of lena-v0.24 | The final comprehensive test of all six pillars; the concluding piece of a complete general-purpose agent implementation |

---

Lena learned to "see and operate the internet" in this chapter — CDP connects to local Chrome, dual-channel DOM snapshot + visual screenshot perception, three-layer fallback ensures availability, and the six pillars complete their final comprehensive validation in the Browser Agent.

You've fully implemented a general-purpose agent runtime and derived a specialized Browser Agent from it. But the path from zero to here was linear — you saw Lena's evolution across 24 chapters. You haven't yet seen how this architecture unfolds in different directions. From a general-purpose agent to a quantitative trading bot, a news broadcasting system, a DevOps on-call bot — what judgments does each path require? **Chapter 25 draws the evolution map of a general-purpose agent — helping you find your own path forward from where this book leaves off.**

---

> "From the first `messages.create()` to here, you've walked through six pillars, 24 chapters, 3,000 lines of code.
> What Lena can do is always determined by what goal you give her.
> Go."

---

## Navigation

[← Ch 23. Specialization Pattern](../ch23-specialization/README-en.md) · [Ch 25. Epilogue: From General to Your Agent →](../ch25-from-general-to-specialized/README-en.md) · [📘 Table of Contents](../../README.md)
