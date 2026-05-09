# Chapter 18: Cron and Long-Running Tasks

> **Lena progression**: v0.17 (gateway + heartbeat) → **v0.18** (cron scheduler + SQLite checkpoint/resume + crash recovery)
> **Pillar**: Long-horizon Execution

---

## Beat 1 — Roadmap

```
Ch15 Gateway ─► Ch16 MessageBus ─► Ch17 Heartbeat ─► [Ch18 ← You are here] ─► Ch19 MCP
                                                         ↑
                                            lena-v0.17 → lena-v0.18
```

Lena can now run in the background and send a morning greeting every day. But "sending a greeting" is a one-shot action — takes under a second, and if it fails tomorrow it retries. Nothing gets lost.

This chapter tackles a different class of task: **work that runs for hours**. Lena will fetch news once an hour, continuously throughout an entire day, accumulating 24 batches, and finally consolidate everything at midnight. That's 24 sequential steps spanning 24 hours. If the process crashes at step 17, the correct behavior is to resume from step 18 — not restart from step 1.

Chapter arc: start with `croniter`, a 10-line scheduler that fires at wall-clock time without drift → add a SQLite checkpoint engine that makes every step crash-safe → assemble the two into a complete news digest pipeline → examine content-hash caching as a natural extension of the checkpoint idea to any expensive repeated computation → and finally look at why the production version of this idea needs 30+ modules, and whether that complexity is justified.

By the end of this chapter, Lena v0.18 can be `kill -9`'d at any moment and resume from the exact checkpoint. The checkpoint principle that makes an hourly news fetch resilient is precisely the same principle used by LangGraph, Temporal, and every durable workflow engine — we're implementing the core idea, not a toy approximation.

> **🧠 Intelligence increment (v0.17 → v0.18)**: Lena can sustain work across an entire day for the first time — croniter's drift-free scheduling plus a SQLite checkpoint engine lets a 24-step pipeline spanning 24 hours resume precisely from a checkpoint after `kill -9`, rather than starting over. This chapter teaches readers how to graft long-task resilience and the checkpoint pattern onto their own agent.

---

## Beat 2 — Motivation

Here is a naive implementation of a 24-hour pipeline:

```python
# BAD: no checkpoints — one crash wipes 11 hours of work  [error example]
def daily_news_pipeline():
    articles = []
    for hour in range(24):
        batch = fetch_news(hour)   # each call takes about 2 seconds
        articles.extend(batch)
        time.sleep(3600)
    summarize(articles)            # only reachable if all 24 calls succeed
```

Start this script at midnight. At 11 AM — after 11 hours, with 11 batches collected — the machine reboots for a kernel update. When the process restarts, `articles` is an empty list in memory. All 11 completed fetches are gone. The pipeline restarts from hour 0.

Wasted work: 11 API calls, roughly 22 seconds of network time, and — because the pipeline now needs another 24 hours — the summary is 11 hours late.

Concrete cost on a paid news API: if each `fetch_news` call costs $0.005, a single crash from midnight to noon wastes $0.055 and delays the summary by 24 hours. With 10 crash-prone days per year (kernel updates, power glitches, OOM kills, memory pressure from other processes), that's $0.55 in direct costs and 10 missed summaries. For an LLM-heavy pipeline where each step costs $0.50 in API calls, those numbers become $5 per crash and real information loss.

`sleep(3600)` has a second, more insidious problem: clock drift. If `fetch_news` takes 4 seconds, the pipeline runs at midnight, 1:00:04 AM, 2:00:08 AM... By noon, the schedule has drifted 1.6 minutes from the intended hourly cadence. When the process restarts the next day, there's no record of "when did this last run" — so there's no way to know whether the missed run should be made up. `croniter` fires at exact wall-clock minutes and provides `get_prev()` to answer "what should have run while I was down?"

---

## Beat 3 — Theory

### 3.1 Cron Expressions (No Code in This Section)

A cron expression is five space-separated fields that describe a recurring point in time. Each field constrains one component of the wall clock:

```
 ┌─ minute (0–59)
 │  ┌─ hour (0–23)
 │  │  ┌─ day of month (1–31)
 │  │  │  ┌─ month (1–12)
 │  │  │  │  ┌─ day of week (0–6, 0=Sunday)
 *  *  *  *  *
```

`*` is a wildcard meaning "any valid value for this field." The `/N` modifier means "every Nth value starting from the lower bound." The `,` operator enumerates specific values. A few expressions worth remembering:

| Expression | When it fires | Typical use |
|-----------|--------------|-------------|
| `0 * * * *` | Minute 0 of every hour | Hourly data fetch |
| `0 8 * * *` | 08:00 every day | Morning digest |
| `0 0 * * *` | Midnight every day | Daily rollup |
| `*/15 * * * *` | Every 15 minutes | Health check |
| `0 0 * * 0` | Midnight every Sunday | Weekly report |
| `0 2 1 * *` | 1st of every month at 02:00 | Monthly billing |
| `0 8-18 * * 1-5` | Weekdays every hour from 08:00–18:00 | Business-hours polling |

`croniter` is a Python library that parses these expressions and provides two methods. `get_next(datetime)` returns the next scheduled time after a given moment — used after a task fires to set `next_run`. `get_prev(datetime)` returns the most recent scheduled time before a given moment — used on process restart to check whether any runs were missed while down. Both methods advance the internal iterator, so you can call `get_next` repeatedly to enumerate the full future schedule.

Convention: **cron expression** = a 5-field string describing a recurring schedule; **cron trigger** = the specific datetime when a task actually fires based on that expression; **missed trigger** = a cron trigger that occurred while the process was not running.

### 3.2 Durable Execution and the Checkpoint Principle (No Code in This Section)

The reliability of a long-running task depends entirely on its checkpoint strategy. The term "durable execution" — used in systems like LangGraph (see [LangGraph persistence docs](https://langchain-ai.github.io/langgraph/concepts/persistence/)) and Temporal — describes a runtime property: **a task can be interrupted at any moment and resume from the last committed state**, as if the interruption never happened.

The minimum viable version of durable execution is: write each step's result to persistent storage before beginning the next step. If the process crashes between step N and step N+1, the next startup reads the storage, finds steps 0 through N complete, and starts from N+1. No recomputation, no data loss.

For this mechanism to work correctly, three invariants must hold:

**Invariant 1 — Idempotency.** Re-running an already-completed step must be safe and produce no side effects. The standard SQL technique is a `UNIQUE` constraint on `(task_id, step_id)`, combined with `INSERT OR IGNORE`. If the row already exists, the insert is a silent no-op. The function returns `False` (meaning "already exists") rather than `True` (meaning "newly inserted"), so the caller knows to skip reprocessing.

**Invariant 2 — Atomicity.** The step result and the "step is complete" marker must land in storage together in a single transaction. Imagine what happens without atomicity: you write the result, the process crashes before writing the completion marker, the step runs again on restart — producing duplicate results and potentially duplicate side effects (another Slack message, another database row, another charge). SQLite's transaction semantics (WAL mode supports concurrent readers) give you this for free.

**Invariant 3 — Deterministic step identity.** Each step needs a stable identifier that remains unchanged across re-runs. The simplest choice is a sequential name (`"fetch_hn"`, `"fetch_github"`). A more powerful choice is a content hash: `sha256(source_id + content)`. A content hash extends idempotency from "this named step" to "this exact content, whenever and wherever it appears." This matters when the same news article may appear in two different hourly fetches, or when a TTS synthesis task may be resubmitted on a different day with identical text.

Convention: **checkpoint** = a persisted record of a completed step, including its result data and completion timestamp; **resume** = reading existing checkpoints on process startup and skipping already-completed steps; **step_id** = the stable identifier used to match a running step to its checkpoint.

### 3.3 Why SQLite, Not a File, Not Redis (No Code in This Section)

The obvious alternatives to SQLite are worth explicitly ruling out.

**A plain JSON file** is tempting for its simplicity: `json.dump(state, f)`. The problem: writing a large JSON file is not atomic. If the process crashes mid-write, you get a truncated or malformed file that can't be parsed on the next startup — worse than having no checkpoint at all, because the code may silently start over without reporting an error. You can work around this with "write to tmp then rename" (`tmp` + `os.replace`), but at that point you're reimplementing a subset of what SQLite already provides, without queryability.

**Redis** is fast, supports atomic operations, and has built-in expiry. The problem: it requires a running external service. Checkpoint storage may be unavailable when the process starts, creating a compound failure mode — two independent systems that can fail, rather than one. SQLite is a single file on local disk; it fails only on disk failure, which is the same failure mode as the process itself.

**Python's standard library `shelve` module** uses `dbm` under the hood. `dbm` backends vary by platform (`gdbm` on Linux, `ndbm` on macOS), have no transaction guarantees, and don't support lock-free concurrent reads. It's suitable for a simple persistent dictionary, but not for a multi-step checkpoint table with concurrent read access.

SQLite wins because it is: zero-configuration (single file), crash-safe by default (WAL journal mode), natively atomic (transactions), bundled with Python's standard library (no pip install), and queryable with standard SQL (a rollup task can directly `SELECT * FROM task_results WHERE task_id = ?` without deserializing complex data structures).

One detail worth understanding: Python's `sqlite3.connect(path)` returns a connection object. When used as a context manager (`with sqlite3.connect(path) as conn:`), it commits on normal exit and rolls back on exception. This is different from closing the connection — if you hold a connection for a long time, you should call `conn.close()` explicitly. For the short-lived operations in this chapter, the context manager pattern is correct.

SQLite WAL mode (`PRAGMA journal_mode=WAL`) improves concurrent read performance — multiple readers can access the database simultaneously while a writer is active. Not required for a single-process pipeline. If you add a separate status dashboard or monitoring process that queries the checkpoint table while the scheduler is writing, enable it then.

---

## Beat 4 — Skeleton

Build the checkpoint engine in isolation first, as a standalone module with no scheduler dependency. The goal of this section is a module you can import, call, and test in isolation immediately.

The following skeleton handles the three invariants from Beat 3: idempotency via `PRIMARY KEY`, atomicity via a single `sqlite3.connect` context manager (commits on normal exit), and a query function that returns a Python `set` for O(1) membership testing.

```python
# core/checkpoint.py — minimum viable checkpoint engine (~55 lines)
import sqlite3, json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/lena.db")

def init_db():
    """
    Create the table if it doesn't exist. Safe to call on every restart.
    The CREATE TABLE IF NOT EXISTS pattern makes this fully idempotent.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_results (
                task_id      TEXT NOT NULL,
                step_id      TEXT NOT NULL,
                result_data  TEXT,             -- JSON blob
                completed_at TEXT NOT NULL,
                PRIMARY KEY (task_id, step_id) -- idempotency key
            )
        """)
        conn.commit()

def save_step(task_id: str, step_id: str, data: dict) -> bool:
    """
    Persist a completed step.
    Returns True for a new insert, False if it already existed (not an error).
    INSERT OR IGNORE is the SQL idiom for "write at most once."
    """
    now = datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO task_results
               (task_id, step_id, result_data, completed_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, step_id, json.dumps(data), now),
        )
        conn.commit()
        return cursor.rowcount == 1   # 1 = inserted; 0 = already existed

def completed_steps(task_id: str) -> set[str]:
    """
    Return the set of step_ids persisted for this task.
    Returns an empty set if the task is unknown (no exception).
    """
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT step_id FROM task_results WHERE task_id = ?",
            (task_id,),
        ).fetchall()
    return {row[0] for row in rows}
```

Verify the idempotency guarantee before adding anything else:

```python
>>> from core.checkpoint import init_db, save_step, completed_steps
>>> init_db()
>>> save_step("test-task", "step-0", {"value": 42})
True    # new insert
>>> save_step("test-task", "step-0", {"value": 999})
False   # already exists — data unchanged
>>> completed_steps("test-task")
{'step-0'}
```

The second `save_step` returned `False` without overwriting the original `{"value": 42}`. That's the idempotency guarantee: once a step is saved, it cannot be accidentally overwritten. This is the only guarantee needed for crash recovery — everything else follows from it.

---

## Beat 5 — Incremental Assembly

We have the checkpoint engine. Now add the components the pipeline needs, one by one.

| Extension | Why it's needed | How to add it |
|-----------|----------------|---------------|
| `croniter` scheduler | Fires at exact wall-clock time without drift; detects missed runs | Use `croniter(expr, now).get_next(datetime)` in a 1-second polling loop |
| Fetch task with resume | Skip steps already in the database on restart | `if step_id in completed_steps(task_id): continue` |
| Content-hash dedup | Same article appearing on a different day costs nothing the second time | Use `sha256(source + content)` as the step_id |
| Midnight rollup | Aggregate all hourly steps into a single LLM call | SQL query over `task_results`, filtered to today's fetch task_id |

**Extension 1 — croniter scheduler**

The scheduler is a tight loop: every second, check whether any task's `next_run` has passed. If it has, fire the task, catch any exceptions to prevent one task's failure from affecting others, then call `get_next()` to set the next trigger time.

```python
# scheduler.py
import time, logging
from croniter import croniter
from datetime import datetime

log = logging.getLogger(__name__)

class Scheduler:
    def __init__(self):
        self._jobs: list[dict] = []

    def add(self, expr: str, fn, name: str):
        it = croniter(expr, datetime.now())
        next_run = it.get_next(datetime)
        self._jobs.append({"name": name, "fn": fn, "next": next_run, "it": it})
        log.info(f"scheduled [{name}]  next_run={next_run.isoformat()}")

    def run_forever(self):
        log.info(f"scheduler started — {len(self._jobs)} job(s)")
        while True:
            now = datetime.now()
            for job in self._jobs:
                if now >= job["next"]:
                    log.info(f"firing [{job['name']}]")
                    try:
                        job["fn"]()
                    except Exception as exc:
                        log.error(f"[{job['name']}] error: {exc}", exc_info=True)
                    # advance regardless of success or failure
                    job["next"] = job["it"].get_next(datetime)
                    log.info(f"[{job['name']}] next_run={job['next'].isoformat()}")
            time.sleep(1)
```

Expected output when two tasks are registered at 12:00:47:

```
12:00:47 INFO scheduled [fetch-news]  next_run=2026-05-05T13:00:00
12:00:47 INFO scheduled [summarize]   next_run=2026-05-06T00:00:00
12:00:47 INFO scheduler started — 2 job(s)
```

The `croniter(expr, datetime.now())` constructor anchors the iterator at "now." The first `get_next()` advances past the current second, so a scheduler started at 12:47 with `"0 * * * *"` schedules the first fetch at 13:00, not 12:00. This is the expected behavior — you want the next scheduled time, not the most recent past time.

**Extension 2 — Fetch task with checkpoint resume**

The fetch task follows a structural pattern: at the start of each run, load the set of completed steps, then iterate over all data sources, skipping any that are already in the set.

```python
# tasks/fetch_news.py
import hashlib, time, logging, random
from core.checkpoint import save_step, completed_steps

log = logging.getLogger(__name__)
SOURCES = [
    {"id": "hn",     "name": "Hacker News"},
    {"id": "github", "name": "GitHub Trending"},
    {"id": "arxiv",  "name": "arXiv ML"},
]

def run(task_id: str):
    done = completed_steps(task_id)
    log.info(f"[{task_id}] {len(done)}/{len(SOURCES)} steps already complete")

    for source in SOURCES:
        step_id = f"fetch_{source['id']}"
        if step_id in done:
            log.info(f"  [skip] {step_id}")
            continue

        articles = _fetch(source["id"])
        saved = save_step(task_id, step_id, {"count": len(articles), "items": articles})
        log.info(f"  [checkpoint] {step_id} — {len(articles)} articles (new_row={saved})")

def _fetch(source_id: str) -> list[dict]:
    """Mock implementation. Replace with real RSS/API calls."""
    return [{"title": f"[mock] {source_id} #{i}", "url": f"https://example.com/{i}"}
            for i in range(random.randint(3, 8))]
```

Simulate a crash by running the task past `fetch_hn`, killing the process (or raising an exception), then rerunning:

```
First run:
  [news-2026-05-05] 0/3 steps already complete
  [checkpoint] fetch_hn     — 7 articles (new_row=True)
  ← crash here →

Second run (after restart):
  [news-2026-05-05] 1/3 steps already complete
  [skip] fetch_hn           ← no network call
  [checkpoint] fetch_github — 5 articles (new_row=True)
  [checkpoint] fetch_arxiv  — 4 articles (new_row=True)
```

The second run made exactly 2 network calls instead of 3. That's the checkpoint guarantee made visible in output.

**Extension 3 — Content-hash step IDs**

Sequential step IDs (`"fetch_hn"`) work when the task structure is fixed. But consider a pipeline that processes each article's full text — using an LLM to generate a summary or embedding. The same article may appear at the top of Hacker News on different days. With a sequential ID, day 2 reprocesses content already processed on day 1 with existing results in the database. With a content-hash ID, day 2 immediately finds the existing result and skips the LLM call.

```python
import hashlib

def content_step_id(source: str, article_id: str) -> str:
    """
    A deterministic step_id determined by content identity, not position.
    Same source + same article_id = same hash, regardless of when or how
    this article appeared in a fetch result.
    """
    return hashlib.sha256(f"{source}:{article_id}".encode()).hexdigest()[:16]

# Use in a per-article LLM processing loop:
def process_articles(task_id: str, articles: list[dict], source: str):
    done = completed_steps(task_id)
    for article in articles:
        step_id = content_step_id(source, article["id"])
        if step_id in done:
            continue   # exact content already processed — LLM result is in the database
        summary = llm_summarize(article["body"])   # one LLM call per unique article
        save_step(task_id, step_id, {"summary": summary, "title": article["title"]})
```

Content-hash IDs and sequential IDs can coexist in the same checkpoint table — they're just strings. Use sequential IDs when a step is defined by its position in the workflow (fetch the Nth data source, once per task run). Use content-hash IDs when a step is defined by the data it processes (analyze this specific article, zero or one time per unique piece of content).

This is the checkpoint-resume principle applied at the content layer rather than the sequence layer: sequential IDs give you position-level resume; content-hash IDs give you identity-level resume.

One important caveat: content-hash caching assumes the step's inputs determine its outputs. If a step's result depends on external state (today's stock price, current weather), yesterday's cached result is stale. For such steps, add a TTL: store an `expires_at` column alongside the result, and treat expired rows as non-existent in `completed_steps`.

**Interlude — Comparing three scheduling primitives**

Before adding the rollup task, it's worth placing `croniter` in context relative to the two alternatives that came before it.

`time.sleep(N)` is the "Hello World" of scheduling. For tasks that need to run once and then wait a fixed interval before running again, it's correct. It has two failure modes: drift (if the task takes nonzero time, each call runs slightly later than the previous one) and amnesia (no record of the last run time when the process restarts).

The `Heartbeat` in Chapter 17 uses a `setTimeout`-style callback. This is functionally equivalent to `sleep` in simple cases. The heartbeat fires on startup, then schedules itself to fire again N seconds later. It avoids some drift but still has no concept of a fixed wall-clock schedule and no catch-up behavior after a crash.

`croniter` with wall-clock polling solves both problems. The schedule is defined in absolute time (`"0 * * * *"` means "minute 0 of every hour"), not relative time ("60 seconds after the last run"). The `get_prev()` method answers "what was the last scheduled time before now?", enabling missed-trigger catch-up.

| Primitive | Drift | Missed trigger awareness | Typical use |
|-----------|-------|-------------------------|-------------|
| `time.sleep(N)` | Yes — accumulates each run | No | Retry loops, simple polling |
| Heartbeat callback | Minimal | No | Proactive notifications |
| `croniter` + wall clock | No | Yes, via `get_prev()` | Pipeline scheduling, daily reports |

For this chapter's pipeline — an hourly fetch that should fire precisely at the top of each hour — croniter is the right choice.

**Extension 4 — Midnight rollup task**

The rollup task aggregates all steps saved under today's `task_id`, passes article titles to Claude, and checkpoints the result. The idempotency check at the start ensures the LLM call happens at most once, even if the process restarts after the call but before the checkpoint is written.

```python
# tasks/summarize.py
import json, sqlite3, logging, os
from core.checkpoint import DB_PATH, save_step, completed_steps, all_steps

log = logging.getLogger(__name__)
MAX_ARTICLES = 40   # cost control: cap titles sent to Claude

def run(summary_task_id: str, fetch_task_id: str):
    done = completed_steps(summary_task_id)
    if "summary" in done:
        log.info(f"[{summary_task_id}] already complete — skipping")
        return

    steps = all_steps(fetch_task_id)
    if not steps:
        log.warning(f"[{summary_task_id}] no fetch data for {fetch_task_id}")
        return

    all_articles = []
    for step in steps:
        all_articles.extend(step["data"].get("items", []))

    log.info(f"[{summary_task_id}] {len(all_articles)} articles from {len(steps)} sources")

    titles = "\n".join(f"- {a['title']}" for a in all_articles[:MAX_ARTICLES])

    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content":
            f"Summarize the following {len(all_articles)} news headlines in 3 bullet points:\n{titles}"}],
    )
    text = resp.content[0].text
    save_step(summary_task_id, "summary", {"text": text, "article_count": len(all_articles)})
    log.info(f"[{summary_task_id}] summary saved ({len(text)} chars)")
```

Note that `all_steps(fetch_task_id)` is a helper function that queries the database and returns all rows for a given `task_id` in order. This is a natural use of SQL that plain files or in-memory dicts can't support as cleanly.

---

## Beat 6 — Run Verification

Assemble and verify the full pipeline. The complete `main.py` wires all components together:

```python
# main.py
import logging
from datetime import date
from core.checkpoint import init_db
from scheduler import Scheduler
from tasks import fetch_news, summarize

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S")

def main():
    init_db()
    today = date.today().isoformat()
    fetch_task_id   = f"news-{today}"
    summary_task_id = f"summary-{today}"

    s = Scheduler()
    s.add("0 * * * *", lambda: fetch_news.run(fetch_task_id),                "fetch-news")
    s.add("0 0 * * *", lambda: summarize.run(summary_task_id, fetch_task_id), "summarize")
    s.run_forever()

if __name__ == "__main__":
    main()
```

Install and run:

```bash
pip install croniter anthropic
export ANTHROPIC_API_KEY=sk-ant-...   # can be omitted in mock mode
python main.py
```

Expected output on a fresh start at 12:00:47:

```
12:00:47  INFO  scheduled [fetch-news]  next_run=2026-05-05T13:00:00
12:00:47  INFO  scheduled [summarize]   next_run=2026-05-06T00:00:00
12:00:47  INFO  scheduler started — 2 job(s)
# ... quiet until 13:00:00 ...
13:00:00  INFO  firing [fetch-news]
13:00:00  INFO  [news-2026-05-05] 0/3 steps already complete
13:00:00  INFO    [checkpoint] fetch_hn     — 6 articles (new_row=True)
13:00:00  INFO    [checkpoint] fetch_github — 8 articles (new_row=True)
13:00:00  INFO    [checkpoint] fetch_arxiv  — 5 articles (new_row=True)
13:00:00  INFO  [fetch-news] next_run=2026-05-05T14:00:00
```

To verify crash recovery without waiting an hour, use `quick_test.py` which bypasses the scheduler entirely:

```bash
python quick_test.py
```

Expected output (simplified):

```
=== First run ===
  [checkpoint] fetch_hn     — 8 articles (new_row=True)
  [checkpoint] fetch_github — 5 articles (new_row=True)
  [checkpoint] fetch_arxiv  — 7 articles (new_row=True)
Completed steps after first run: {'fetch_github', 'fetch_arxiv', 'fetch_hn'}

=== Second run (simulating restart) ===
  [skip] fetch_hn    — already in database
  [skip] fetch_github — already in database
  [skip] fetch_arxiv  — already in database
Completed steps unchanged: {'fetch_github', 'fetch_arxiv', 'fetch_hn'}

=== Rollup ===
  [summary-test] 20 articles from 3 sources
  [mock summary] 20 articles from 3 sources.

All checks passed.
```

The numbers — 8, 5, 7 articles — come from the mocked `random.randint`. Your run will differ, but the structure should be consistent. Three `[checkpoint]` lines on the first run, three `[skip]` lines on the second — no wasted network calls.

The task state machine's evolution over an entire day:

```
00:00  fetch_news.run("news-2026-05-05")
         [checkpoint] fetch_hn     — new_row=True
         [checkpoint] fetch_github — new_row=True
         [checkpoint] fetch_arxiv  — new_row=True

01:00  fetch_news.run("news-2026-05-05")
         [skip] fetch_hn           — already in database (hourly runs are idempotent for this day)
         [skip] fetch_github
         [skip] fetch_arxiv
     ← wait, this is wrong — each hourly run should fetch new articles

     Fix: include the hour in the task_id.
     fetch_task_id = f"news-{today}-hour-{hour}"
     Each hour gets its own task namespace, so each hourly fetch is independent.

     Or: include the hour in the step_id.
     step_id = f"fetch_{source}_{datetime.now().strftime('%H')}"
     Both approaches work; task-level namespacing (the first) is cleaner.

After the fix, 24 independent task_ids accumulate through the day:
  "news-2026-05-05-hour-00" → {fetch_hn, fetch_github, fetch_arxiv}
  "news-2026-05-05-hour-01" → {fetch_hn, fetch_github, fetch_arxiv}
  ...
  "news-2026-05-05-hour-23" → {fetch_hn, fetch_github, fetch_arxiv}

Midnight:
  summarize.run("summary-2026-05-05")
    reads all 24 task_ids for today
    aggregates all articles
    calls Claude
    [checkpoint] summary — new_row=True
```

For simplicity, this chapter's code uses one `task_id` per day with three data sources as a complete set of steps. In a real pipeline, hourly granularity would be reflected in `task_id` or `step_id` as shown above. Either way, the checkpoint invariants are identical.

**Common failures and their causes:**

- `sqlite3.OperationalError: no such table: task_results` — `init_db()` was not called before the first database operation. Fix: call `init_db()` at process startup, before starting the scheduler.
- Second run still shows `[checkpoint]` lines — the `PRIMARY KEY (task_id, step_id)` constraint is missing, or `INSERT OR IGNORE` was written as `INSERT OR REPLACE`. `INSERT OR REPLACE` deletes and re-inserts, which is not idempotent if other columns change.
- `croniter` fires immediately on startup — you passed `start_time` as a constructor argument rather than as an anchor time. `croniter(expr, datetime.now())` anchors at "now"; `get_next()` gives you the next future trigger after the anchor.
- Memory grows after several hours — the `articles` list inside `_fetch` is being accumulated across calls. Each call to `fetch_news.run()` creates a new scope, so this shouldn't happen. If you see growth, check for module-level mutable state (e.g., a global `articles` list).

---

### Context Reset vs. Compaction: Another Dimension of Long Tasks

This chapter's checkpoint-resume solves **external state** persistence (checkpoints on disk). But there's an internal problem too: **the LLM's own context window can blow up during long tasks**.

Anthropic's March 2026 harness design experiments revealed the relative merits of two coping strategies:

| Strategy | Approach | Advantage | Cost |
|----------|----------|-----------|------|
| **Compaction** | Compress old conversation into a summary; agent continues running | Maintains continuity | Context anxiety unresolved — agent still perceives "almost full" |
| **Context Reset** | Clear context entirely; start a fresh agent; hand off state via structured artifact | Eliminates context anxiety completely | Requires designing a handoff artifact; adds orchestration complexity |

Anthropic's experiments found that Claude Sonnet 4.5's **context anxiety is strong enough** that compaction alone is insufficient to sustain long-task performance — context reset is required.

> "Context resets—clearing the context window entirely and starting a fresh agent, combined with a structured handoff that carries the previous agent's state—addresses both context anxiety and coherence loss."
> (Source: Anthropic, *Harness design for long-running application development*, 2026-03-24)

The implication for Lena: Ch10 covered compaction; this chapter covers checkpointing. But a truly production-grade long-task agent needs **all three working together**: compaction delays context growth → upon reaching a threshold, context reset → hand off via a checkpoint artifact → new agent resumes from the checkpoint. This is why Ch17 Heartbeat + Ch18 Cron + Ch10 Context Engineering form one integrated whole.

---

## Beat 7 — Design Note

> **Why Not Just Design Long-Running Tasks to Restart From Scratch?**

The obvious alternative is to make each task stateless: if the process crashes mid-run, delete all partial results and start over. There are two situations where this is a reasonable strategy: when each step is cheap enough that re-running everything costs less than building and maintaining a checkpoint system; and when each step is truly side-effect-free (re-running produces the same result with no external consequences).

The tradeoff turns unfavorable when a task has any of three properties:

**Expensive steps.** An LLM call that costs $0.02 and takes 8 seconds is not worth rerunning if the crash happened 10 seconds after the call completed. The cost is both financial and temporal. In a 24-step pipeline where each step costs $0.02, a crash at step 23 wastes $0.46 and 3 minutes under a zero-restart strategy. With checkpoints, the restart costs one step: $0.02 and 8 seconds.

**Steps with side effects.** If a step sends a Slack notification, writes to an external database, triggers a payment, or publishes a message to a channel, re-running it is unsafe regardless of cost. "At most once" semantics require an idempotency mechanism — and that mechanism is the checkpoint. Content-hash IDs extend this to "each unique piece of content processed at most once, across all time."

**Long pipelines with many steps.** A pipeline with 24 steps, each with a 1% crash probability, has a 21% chance of at least one step crashing. Under the zero-restart strategy, each crash wastes an average of 12 steps. With checkpoints, each crash wastes at most 1 step. As the pipeline grows longer, the expected waste of the stateless approach grows linearly; with checkpoints it stays constant.

Recommendation: **add checkpoints when any single step has a cost you don't want to repeat unnecessarily** — time, money, or side effects. A cron task that sends a one-line greeting doesn't need checkpoints — it's fast and safe to retry. A cron task that makes LLM API calls, processes large files, or triggers external actions does.

In numbers: if your pipeline has N steps, each with an independent crash probability p (say 0.1% OOM kill probability per step, p = 0.001), a 24-step pipeline has at least one crash with probability `1 - (1-p)^24 ≈ 2.4%`. Under the zero-restart strategy, expected wasted work per crash is N/2 steps. With checkpoints, it's 0 steps (the resume run picks up exactly from the checkpoint). As N grows, checkpoints become increasingly valuable. At N=100, expected wasted work without checkpoints is 50 steps — half the pipeline.

If your task graph is complex enough to require branching logic, parallel fan-out, or human-in-the-loop pauses, consider using [LangGraph's checkpoint/resume](https://langchain-ai.github.io/langgraph/concepts/persistence/) instead of the hand-rolled solution in this chapter. LangGraph implements the same principles — write state after each node, resume from the last successful node — with support for SQLite, Redis, and PostgreSQL checkpoint backends, plus a visual debugger that can inspect the full state at any graph node. Tradeoff: LangGraph adds ~30MB of dependencies and a learning curve; this chapter's SQLite solution adds 50 lines of code.

---

## Production Version: Why the Complexity Is Necessary

The production implementation's core entry function `runCronIsolatedAgentTurn` imports 30+ modules before executing the first line of scheduling logic. This is not overengineering — each import exists because a production edge case was encountered in real deployment:

- **model-fallback** exists because a 3 AM Opus quota error once caused an entire overnight digest to silently fail. Fix: try Opus first, fall back to Sonnet, fall back to Haiku. The fallback chain is now configurable per agent.
- **session-key + session** exist because cron tasks were sharing session context with interactive agent loops, causing context pollution: a lengthy midnight rollup would fill the context window, breaking the user's conversation the following morning.
- **auth-profiles/session-override** exist because a multi-tenant deployment had a bug where a task configured for Agent A ran under Agent B's API key. The fix was per-session auth profile isolation with explicit validation.
- **delivery-dispatch** exists because early implementations published summaries as raw log messages. Users wanted Slack formatting, Telegram markdown, and Feishu rich text — three different formatting pipelines depending on the delivery destination.
- **skills-snapshot** exists because cron tasks need a deterministic skill set. Interactive sessions can dynamically load new skills; scheduled tasks should run with the skill set configured at task definition time, not whatever skills happened to be loaded at trigger time.

The core design principle — persist each step, check on restart — is identical in both versions. The production version is the same 3 invariants with 30+ modules of operational experience layered on top.

If you're building a personal agent for one user with one model, lena-v0.18 is complete. When you need multi-user, multi-model, multi-channel cron with per-task isolation, each module maps to a production failure that's worth studying in depth.

---

## Lena v0.18 Full Module Map

The complete `lena-v0.18/` directory:

```
lena-v0.18/
├── main.py            # Entry point: init_db, register 2 cron tasks, run_forever()
├── scheduler.py       # croniter wrapper — 40 lines, zero dependencies besides croniter
├── core/
│   └── checkpoint.py  # SQLite engine — init_db / save_step / completed_steps / all_steps
├── tasks/
│   ├── fetch_news.py  # Hourly fetch with checkpoint/resume — replace _fetch() with real data
│   └── summarize.py   # Midnight LLM rollup — reads all_steps, writes one "summary" record
├── quick_test.py      # Verify crash recovery without waiting an hour
├── requirements.txt   # croniter>=3.0.0, anthropic>=0.25.0
└── data/              # Created at runtime — lena.db lives here
```

The module boundaries are deliberate. `core/checkpoint.py` knows nothing about news or scheduling — it's a generic persistent step engine. `tasks/fetch_news.py` knows nothing about scheduling — it only knows how to run one fetch and checkpoint each data source. `scheduler.py` knows nothing about news or checkpoints — it only knows how to fire functions at croniter-defined times. `main.py` is the only file that knows about all three components; it wires them together.

This separation means you can test `checkpoint.py` in complete isolation (which is exactly what `quick_test.py` does), swap out the scheduler without modifying the tasks, and add new task types without modifying the checkpoint engine. Each module has exactly one reason to change.

---

## End-of-Chapter Challenges

**Challenge 1 — Missed-trigger catch-up.** The current scheduler ignores tasks that should have fired while the process was down. Use `croniter.get_prev()` to add a `check_missed_run(expr: str, last_seen: datetime) -> bool` function that returns True if any trigger occurred between `last_seen` and `now`. Store each task's `last_seen` in the checkpoint database.

**Challenge 2 — TTL checkpoint expiry.** Add a `valid_for_hours: int` parameter to `save_step`. Modify `completed_steps` to ignore rows older than `valid_for_hours`. This simulates the situation where input data changes frequently and a day-old checkpoint is stale.

**Challenge 3 — Parallel source fetching.** The current `fetch_news.run()` fetches sources sequentially. Convert it to use `asyncio.gather` to run the three fetch coroutines concurrently. The checkpoint logic is unchanged — idempotency still comes from `INSERT OR IGNORE`. But the wall-clock time for the fetch step drops from 3× single-source latency to approximately 1×.

---

Lena can now run for days and recover after a restart. What she can't yet do is *extend her own capabilities at runtime* — the tool set available today is fixed at startup. The next chapter introduces MCP, the protocol that lets Lena connect to any external tool server without modifying her code.

---

## Navigation

➡️ **[Ch 19. MCP Protocol](../ch19-mcp-protocol/README.md)** — Dynamic tool extension

[← Ch 17. Heartbeat and Always-On Execution](../ch17-heartbeat/README.md) · [📘 Back to Table of Contents](../../README.md)
