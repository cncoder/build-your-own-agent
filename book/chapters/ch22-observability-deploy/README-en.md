# Chapter 22: Observability and Deployment — Running Lena 24/7 in Production

> **[Pillars: Long-horizon Execution / Transparency / Safety]**

---

## Beat 1 — Roadmap

```
Ch1  Ch3  Ch6  Ch8  Ch11  Ch15  Ch17  Ch18  Ch21  ▶ Ch22 ← You are here
Base Tool Safe Mem  Plan  Gate  Cron  Budg  Eval   Observability+Deploy
                                                              ↓
                                                          Lena v0.22
                                                     (production-ready)
```

In the first 21 chapters, Lena learned tool use, task decomposition, scheduled jobs, and safety guardrails. But she still lives on a dev machine — close the terminal and she disappears. You don't know if she quietly crashed. You don't know how much money she spent this week.

This chapter starts from three concrete symptoms, moves through structured logging + OpenTelemetry + a Budget state machine, and arrives at three deployment options — systemd, launchd, and Docker — with a counterintuitive design decision along the way: **why cost monitoring must be a pre-call circuit breaker, not a post-hoc alert**.

By the end, Lena upgrades from v0.21 to v0.22 with four new production capabilities:
1. Every LLM call has structured logs and OTel spans — replay any historical decision with `jq` or Jaeger
2. A four-state daily budget machine auto-throttles before the bill explodes
3. Three deploy files — one command to resurrect Lena after a reboot
4. Two Hook examples — wire ruff lint and Stop notifications into Claude Code's automation pipeline

> **Intelligence increment (v0.21 → v0.22)**: Lena becomes observable for the first time — structured logs + OTel spans + a four-state daily budget machine make every LLM call traceable, and a pre-call cost circuit breaker prevents infinite-loop billing disasters. systemd/launchd deployment means she auto-recovers after a machine restart. This chapter teaches you how to build production-grade observability directly into your own agent.

---

## Beat 2 — Motivation

Deploying an agent without observability is like sending a blind person to fly a plane.

Here are the concrete symptoms.

**Symptom 1: Three days later, you have no idea what happened.**

```python
# Lena's current logging (BAD)
print(f"LLM reply: {reply[:50]}...")
print(f"Tool executed: {tool_name}")
```

These two lines are tolerable while you're watching the terminal. Three days later you want to diagnose "why did that Friday night task fail" — you open the log file and find an unstructured wall of plain text. `grep` can't find correlations, `jq` doesn't recognize it, you have to read with your eyes, and ten minutes later you still haven't localized the issue.

Compare that to structured logging: `jq 'select(.event=="tool_fail" and .timestamp>"2026-05-09")' lena.log` — result in 0.3 seconds.

**Symptom 2: You don't know how much Lena spent.**

A dead-loop bug (say, a loop variable that never clears, causing the agent to retry the same failing action forever) can generate $40–$80 in Bedrock charges within 24 hours with no budget circuit breaker — all for the same error message, repeated endlessly. A post-hoc billing alert is already too late.

The reality is: **by the time you see the alert, the money is already gone.** Budget enforcement must happen *before* the LLM call, not after the bill arrives.

**Symptom 3: Close the terminal and Lena dies.**

Running `python3 main.py` is fine for development. It isn't acceptable for production. You need Lena to keep executing scheduled tasks while you sleep, to auto-recover after a machine reboot, and to restart herself after a crash — that requires a process supervisor, not a shell-attached process.

---

## Beat 3 — Theory

### 3.1 Why Agent Observability Differs from Traditional Services

A traditional web service's request-response cycle is deterministic: same input, same output. Logs exist mainly for debugging.

Agents are fundamentally different in three ways:

**Long-tail latency**: A single agent session might involve 3 LLM calls and 12 tool calls, with total duration ranging from 2 seconds to 20 minutes. Traditional P99 latency metrics are meaningless for agents. What you need to trace is the **decision chain** — which LLM call number, which tools were used, how long each took, how many tokens each consumed.

**Non-deterministic output**: The same system prompt + user input, due to model stochasticity, might lead Lena to choose tool A today, tool B tomorrow, and both the day after. You can't use "expected output" to assess correctness the way you do with traditional services — you need to track **consistency between intent and behavior**, not exact output matches.

**Cost is a variable**: A web request costs microseconds of compute, effectively zero. An agent task's LLM calls cost anywhere from $0.001 to $0.5 depending on task complexity. This makes cost monitoring a first-class citizen of agent observability, not an afterthought.

Convention: **Trace** = one complete user request with a unique `trace_id`; **Span** = one specific operation (e.g., one LLM call) with start/end timestamps and a parent-child relationship, attached to a Trace; **Log** = a snapshot of an event at a single point in time, linked to a Trace via `trace_id`/`span_id`.

These three are not interchangeable alternatives: Logs tell you *what happened*, Spans tell you *how long it took*, Traces tell you *what the full call chain looked like*. A production agent needs all three simultaneously.

### 3.2 Why Cost Circuit Breaking Must Be Pre-Call

This is a design pattern with no real equivalent in traditional web services.

The post-hoc alert logic: spend money → billing push → receive alert → manually stop. This chain has two fundamental flaws:

1. **Time lag**: Cloud billing alert delays are typically measured in hours. A dead-loop agent can spend $20+ in an hour — by the time the alert reaches you, the damage is done.
2. **Requires human intervention**: Alerts notify humans, and humans take time to respond. An alert that fires at 3 AM may not be acknowledged until 8 AM, five hours later. The design goal of an agent system is autonomous operation — "requires human intervention to stop" is a fundamental contradiction.

The pre-call circuit breaker design: check budget state *before* each LLM call. If the threshold has been crossed, reject the call on the spot; the agent auto-stops or auto-throttles. This is part of agent autonomy: it needs to know not just "what can I do" but "how much can I spend right now."

nanoClaw (`nanoclaw/security/budget.py`) uses a dual-dimension circuit breaker based on iteration count and token count. Lena v0.22 adds a third dimension — daily USD budget — and introduces a four-state machine (OK → WARN → THROTTLE → STOP), making the shutdown behavior gradual rather than abrupt.

> Reference: nanoClaw `budget.py` (`SessionBudget.check_iteration()`, line 84) uses a static threshold hard-stop. Lena v0.22's improvement is introducing the THROTTLE state — the agent slows down at 90% budget instead of stopping immediately — reducing disruption to in-progress tasks. This isn't the ideal solution; it's a pragmatic trade-off between "availability" and "cost control." If your use case is experimental tasks, a hard-stop is actually simpler and fine.

### 3.3 Three Ways to Supervise a Process

Convention: **launchd** = macOS's native process manager, configured via plist XML, starts on user login; **systemd** = Linux's standard process manager, configured via .service INI files, starts at system boot; **Docker** = a container runtime using a Dockerfile to describe the environment and `docker-compose.yml` to describe service dependencies.

These aren't competitors — they suit different scenarios: launchd for a personal Mac dev machine, systemd for a Linux server, Docker Compose for multi-service deployments.

A common trap for all three is the **restart storm**: if a process crashes immediately on start, the supervisor will attempt to restart it at very high frequency, triggering platform rate-limiting mechanisms that permanently stop the process with no alert. launchd uses `ThrottleInterval` to control this; systemd uses `StartLimitBurst`. Both must be explicitly configured.

---

## Beat 4 — Scaffolding

Let's build the minimal observable skeleton by adding structured logging to Lena's core loop first:

```python
# code/lena-v0.22/src/observability/logger.py
"""Structured logging configuration.

Convention:
  - Development mode: ConsoleRenderer (colorized, human-readable)
  - Production mode: JSONRenderer (one JSON object per line,
    directly parseable by jq / CloudWatch / ELK)
"""
import logging
import sys

import structlog  # pip install structlog>=24.0


def setup_logging(
    level: str = "INFO",
    json_output: bool = False,  # development mode by default; pass True for production
) -> None:
    """Initialize structured logging. Call once; takes effect globally."""
    shared_processors = [
        structlog.stdlib.add_log_level,           # inject level field
        structlog.stdlib.add_logger_name,         # inject logger field
        structlog.processors.TimeStamper(fmt="iso"),  # ISO 8601 timestamp
        structlog.processors.StackInfoRenderer(), # exception stack traces
        structlog.processors.format_exc_info,
    ]

    if json_output:
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
    )


# Usage: any module can import and use directly
# logger = structlog.get_logger(__name__)
# logger.info("llm_call", model="claude-sonnet-4-6", input_tokens=4230)
```

After running `setup_logging(json_output=True)`, each log line looks like:

```json
{"event": "llm_call", "model": "claude-sonnet-4-6", "input_tokens": 4230,
 "level": "info", "timestamp": "2026-05-22T03:12:04Z", "logger": "lena.core"}
```

Now let's layer OTel spans and Budget gating on top of this skeleton.

---

## Beat 5 — Progressive Assembly

### Extension Table

| Extension | Why It's Needed | How to Add |
|-----------|-----------------|------------|
| OTel span wrapping LLM calls | See full call chain latency, identify bottlenecks | `with tracer.start_as_current_span("llm_call") as span` |
| Budget state machine | Pre-call circuit breaker, prevent runaway billing | `await budget.check_and_wait()` before calling LLM |
| Stop Hook notification | Notify via Discord when Lena stops | `hooks/notify_stop.py` reads stdin JSON |
| PostToolUse Hook lint | Auto-run ruff every time a Python file is written | `hooks/lint_on_write.py` |

### Extension 1: OTel Span Tracing

Let's verify the full call chain by wrapping the LLM call in an OpenTelemetry span:

```python
# code/lena-v0.22/src/observability/tracing.py
"""OpenTelemetry integration.

Design note: The OTLP exporter supports Jaeger/Tempo/Honeycomb/X-Ray.
Switching backends requires changing one line (the endpoint),
not the business code.
"""
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource


def setup_tracing(
    service_name: str = "lena",
    otlp_endpoint: str = "http://localhost:4317",  # local Jaeger
) -> trace.Tracer:
    """Initialize tracer, export to OTLP.

    Local dev: docker run -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one
    Production migration: change endpoint to AWS X-Ray ADOT collector (nothing else changes)
    """
    resource = Resource.create({
        "service.name": service_name,
        "service.version": "0.22.0",
    })
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)
```

Checkpoint: start Jaeger (`docker run -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one`), run Lena and send one message, open `http://localhost:16686`. You should see service `lena` with trace records, each LLM call as a span containing `input_tokens` / `output_tokens` / `latency_ms` attributes.

### Extension 2: Four-State Budget Machine

```python
# code/lena-v0.22/src/budget/budget_controller.py
"""Four-state daily budget machine.

Four states:
  NORMAL   (0-80%)   — normal operation
  WARNING  (80-90%)  — log a warning, but don't slow down
  THROTTLE (90-100%) — sleep 2s before each call, actively throttle
  STOPPED  (≥100%)   — reject calls, return False

Why four states instead of two (normal/stopped)?
  The THROTTLE state gives a long-running task a "graceful slowdown" window
  instead of hard-cutting it midway. It's a pragmatic trade-off between
  cost control and task availability.
  For purely experimental workloads, set throttle_pct = 1.0 to get binary behavior.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Callable

import structlog

log = structlog.get_logger(__name__)


class BudgetState(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    THROTTLE = "throttle"
    STOPPED = "stopped"


@dataclass
class BudgetConfig:
    daily_usd: float = 5.0           # daily budget of $5; adjust as needed
    warn_pct: float = 0.80           # 80% → WARNING
    throttle_pct: float = 0.90       # 90% → THROTTLE
    throttle_delay_sec: float = 2.0  # delay per call when THROTTLEd


@dataclass
class BudgetController:
    config: BudgetConfig = field(default_factory=BudgetConfig)
    _spent_usd: float = 0.0
    _date: date = field(default_factory=date.today)
    _state_change_callbacks: list[Callable[[BudgetState], None]] = field(
        default_factory=list
    )

    def _reset_if_new_day(self) -> None:
        """Auto-reset at midnight — daily budget is a calendar day, not a rolling window."""
        today = date.today()
        if today != self._date:
            log.info("budget_reset", prev_spent=self._spent_usd, prev_date=str(self._date))
            self._spent_usd = 0.0
            self._date = today

    @property
    def state(self) -> BudgetState:
        self._reset_if_new_day()
        pct = self._spent_usd / self.config.daily_usd
        if pct >= 1.0:
            return BudgetState.STOPPED
        if pct >= self.config.throttle_pct:
            return BudgetState.THROTTLE
        if pct >= self.config.warn_pct:
            return BudgetState.WARNING
        return BudgetState.NORMAL

    async def check_and_wait(self) -> bool:
        """Pre-LLM-call budget gate.

        Returns False when the limit is reached; callers should not proceed.
        In THROTTLE state, sleeps then returns True (slows down but doesn't stop).
        """
        s = self.state
        if s == BudgetState.STOPPED:
            log.warning(
                "budget_stopped",
                spent_usd=self._spent_usd,
                limit_usd=self.config.daily_usd,
                msg="Daily budget limit reached, rejecting LLM call",
            )
            return False
        if s == BudgetState.THROTTLE:
            log.info("budget_throttle", delay_sec=self.config.throttle_delay_sec)
            await asyncio.sleep(self.config.throttle_delay_sec)
        return True

    def record_cost(self, usd: float) -> None:
        """Record actual cost after each LLM call; check for state transitions."""
        prev_state = self.state
        self._spent_usd += usd
        new_state = self.state
        if new_state != prev_state:
            log.warning(
                "budget_state_change",
                from_state=prev_state.value,
                to_state=new_state.value,
                spent_usd=round(self._spent_usd, 4),
                daily_limit=self.config.daily_usd,
            )
            for cb in self._state_change_callbacks:
                cb(new_state)

    def on_state_change(self, callback: Callable[[BudgetState], None]) -> None:
        """Register a state-transition callback (e.g., send a Telegram alert)."""
        self._state_change_callbacks.append(callback)

    @property
    def usage_pct(self) -> float:
        self._reset_if_new_day()
        return round(self._spent_usd / self.config.daily_usd, 4)
```

Checkpoint:

```python
import asyncio
from lena.budget.budget_controller import BudgetConfig, BudgetController

cfg = BudgetConfig(daily_usd=1.0, warn_pct=0.5, throttle_pct=0.8)
bc = BudgetController(config=cfg)
bc.record_cost(0.55)  # triggers WARNING
print(bc.state)       # BudgetState.WARNING
bc.record_cost(0.30)  # triggers THROTTLE
print(bc.state)       # BudgetState.THROTTLE
bc.record_cost(0.20)  # triggers STOPPED
print(bc.state)       # BudgetState.STOPPED

# Expected output (via structlog console renderer):
# [warning] budget_state_change from_state=normal to_state=warning spent_usd=0.55 daily_limit=1.0
# [warning] budget_state_change from_state=warning to_state=throttle spent_usd=0.85 daily_limit=1.0
# [warning] budget_state_change from_state=throttle to_state=stopped spent_usd=1.05 daily_limit=1.0
```

### Extension 3: Wire Budget into the Agent Loop

```python
# code/lena-v0.22/src/core/agent_loop.py (key changes only, not the full file)
import structlog
from opentelemetry import trace
from lena.budget.budget_controller import BudgetController
from lena.observability.logger import setup_logging
from lena.observability.tracing import setup_tracing

log = structlog.get_logger(__name__)
tracer = setup_tracing()


class AgentLoop:
    def __init__(self, client, system_prompt: str, budget: BudgetController):
        self.client = client
        self.messages = []
        self.system = system_prompt
        self.budget = budget

    async def step(self, user_input: str) -> str | None:
        # Budget gate: check before calling LLM
        allowed = await self.budget.check_and_wait()
        if not allowed:
            log.warning("step_blocked_by_budget")
            return None  # caller decides whether to retry or stop

        self.messages.append({"role": "user", "content": user_input})

        with tracer.start_as_current_span("llm_call") as span:
            span.set_attribute("input_messages", len(self.messages))
            resp = await self._call_llm()
            span.set_attribute("input_tokens", resp.usage.input_tokens)
            span.set_attribute("output_tokens", resp.usage.output_tokens)

        # Record actual cost (Sonnet 4.6: $3/1M input + $15/1M output)
        cost_usd = (
            resp.usage.input_tokens * 3e-6
            + resp.usage.output_tokens * 15e-6
        )
        self.budget.record_cost(cost_usd)

        log.info(
            "llm_step_complete",
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cost_usd=round(cost_usd, 6),
            budget_pct=self.budget.usage_pct,
        )

        reply = resp.content[0].text
        self.messages.append({"role": "assistant", "content": reply})
        return reply
```

Checkpoint: run one conversation, then `jq '.cost_usd' lena.log | paste -sd+ | bc` should produce the day's cumulative cost.

### Extension 4: Claude Code Hooks

Claude Code's Hook mechanism (`utils/hooks.ts:85`) inserts external commands at 14 lifecycle points. Mechanism: `child_process.spawn()` launches the command, JSON is passed via stdin, and stdout returns `{"decision": "approve"|"block", "reason": "..."}` or `{"blockingErrors": [...]}` to control agent behavior.

The 14 event types grouped by trigger timing:

```
Tool lifecycle     PreToolUse / PostToolUse / PostToolUseFailure
Session lifecycle  SessionStart / Setup / Stop / StopFailure
Subagent lifecycle SubagentStart / SubagentStop
User interaction   UserPromptSubmit / Notification
Environment        InstructionsLoaded / FileChanged / CwdChanged
```

Convention: **PreToolUse** = fires before tool execution; can return `"block"` to prevent it. **PostToolUse** = fires after successful execution; can trigger side effects (lint, metrics) but cannot undo execution. **Stop** = fires when the agent loop exits normally; returning `{"blockingErrors": [...]}` can keep the loop running instead of exiting.

Two most useful hook examples:

**Hook A: PostToolUse — auto-lint with ruff**

```json
// .claude/settings.json (project-level)
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/hooks/lint_on_write.py"
          }
        ]
      }
    ]
  }
}
```

```python
# code/lena-v0.22/hooks/lint_on_write.py
"""PostToolUse hook: auto-run ruff check after every Write to a .py file.

If ruff reports errors, return block + error reason so the agent
can fix and retry. This isn't a hard gate; it's a feedback loop
that gives the agent an automatic self-correction opportunity.
"""
import json
import subprocess
import sys


def main() -> None:
    data = json.loads(sys.stdin.read())
    file_path = data.get("tool_input", {}).get("file_path", "")

    if not file_path.endswith(".py"):
        # Not a Python file, pass through
        print(json.dumps({"decision": "approve"}))
        return

    result = subprocess.run(
        ["ruff", "check", "--fix", file_path],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(json.dumps({
            "decision": "block",
            "reason": f"Ruff lint failed, please fix before proceeding:\n{result.stdout[:500]}",
        }))
    else:
        print(json.dumps({"decision": "approve"}))


if __name__ == "__main__":
    main()
```

**Hook B: Stop — Discord notification**

```python
# code/lena-v0.22/hooks/notify_stop.py
"""Stop hook: send a Discord webhook notification when the agent stops normally.

The Stop hook can return {"blockingErrors": [...]} to prevent the agent from
exiting (keeping the loop alive). Here we only notify and don't block,
so we return {}.

Limitation: the Stop hook does NOT fire on StopFailure (abnormal exits).
Add a separate StopFailure hook for crash alerting.
"""
import json
import os
import sys

import httpx


def main() -> None:
    data = json.loads(sys.stdin.read())
    session_id = data.get("session_id", "unknown")
    stop_reason = data.get("stop_reason", "unknown")

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook_url:
        msg = f"✅ Lena session `{session_id[:8]}` completed | reason: {stop_reason}"
        try:
            httpx.post(webhook_url, json={"content": msg}, timeout=5)
        except Exception:
            pass  # notification failure must not block the agent from exiting

    print(json.dumps({}))  # empty response = allow normal exit


if __name__ == "__main__":
    main()
```

---

## Beat 6 — Running and Verification

### Final Output Structure

```
code/lena-v0.22/
├── src/
│   ├── observability/
│   │   ├── logger.py          # structlog configuration
│   │   └── tracing.py         # OTel + Jaeger/X-Ray integration
│   ├── budget/
│   │   └── budget_controller.py  # four-state machine
│   └── core/
│       └── agent_loop.py      # integrated logging + OTel + budget
├── deploy/
│   ├── lena.service           # systemd (Linux)
│   ├── ai.lena.agent.plist    # launchd (macOS)
│   └── docker-compose.yml     # Docker Compose (multi-service)
├── hooks/
│   ├── lint_on_write.py       # PostToolUse → ruff
│   └── notify_stop.py         # Stop → Discord
├── Dockerfile
└── requirements.txt
```

### Three Deploy Files

**launchd (macOS)**

```xml
<!-- deploy/ai.lena.agent.plist → ~/Library/LaunchAgents/ -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.lena.agent</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-u</string>
        <string>/opt/lena/src/main.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/opt/lena</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <!--
      ThrottleInterval is the key to preventing restart storms.
      Without it: crash → launchd immediately restarts → crashes again →
      5 restarts within 60s → process permanently stopped.
      With it: at least 30s between restarts, giving code time to be fixed
      and logs time to flush.
    -->
    <key>ThrottleInterval</key>
    <integer>30</integer>

    <key>EnvironmentVariables</key>
    <dict>
        <key>AWS_REGION</key>
        <string>us-west-2</string>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
        <key>LOG_LEVEL</key>
        <string>INFO</string>
        <key>LOG_FORMAT</key>
        <string>json</string>
    </dict>

    <key>StandardOutPath</key>
    <string>/var/log/lena/agent.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/lena/agent-err.log</string>
</dict>
</plist>
```

```bash
# First-time load
launchctl load ~/Library/LaunchAgents/ai.lena.agent.plist

# After editing the plist, must unload/load (not SIGUSR1 — that doesn't refresh env vars)
launchctl unload ~/Library/LaunchAgents/ai.lena.agent.plist
launchctl load ~/Library/LaunchAgents/ai.lena.agent.plist

# Check status (0 = running, non-zero = last exit code)
launchctl list | grep lena
```

**systemd (Linux)**

```ini
# deploy/lena.service → /etc/systemd/system/lena.service
[Unit]
Description=Lena AI Agent v0.22
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=lena
Group=lena
WorkingDirectory=/opt/lena
ExecStart=/opt/lena/.venv/bin/python -u -m src.main

Environment=AWS_REGION=us-west-2
Environment=PYTHONUNBUFFERED=1
Environment=LOG_FORMAT=json
EnvironmentFile=/opt/lena/.env  # secrets in a separate file, not in git

Restart=on-failure
RestartSec=15s

# StartLimitBurst: 5 crashes within 300s triggers a stop + alert
# Manual recovery: systemctl reset-failed lena && systemctl start lena
StartLimitIntervalSec=300
StartLimitBurst=5

MemoryMax=1G
CPUQuota=80%

# Security hardening: no privilege escalation, private /tmp,
# read-only outside /opt/lena
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/opt/lena/data /var/log/lena

StandardOutput=journal
StandardError=journal
SyslogIdentifier=lena-agent

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lena

# Live logs
sudo journalctl -u lena -f

# JSON format (pipe to filebeat / fluentd)
sudo journalctl -u lena -o json | jq '.MESSAGE | fromjson? // .'
```

**Docker Compose (multi-service)**

```yaml
# deploy/docker-compose.yml
services:
  lena:
    build: ..
    container_name: lena-agent
    restart: unless-stopped
    env_file: ../.env
    environment:
      - AWS_REGION=us-west-2
      - LOG_FORMAT=json
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317  # Docker Compose internal service name; use localhost:4317 from the host
    volumes:
      - lena-data:/app/data
      - lena-logs:/app/logs
    depends_on:
      jaeger:
        condition: service_started
    networks:
      - lena-net

  jaeger:
    image: jaegertracing/all-in-one:latest
    container_name: lena-jaeger
    restart: unless-stopped
    ports:
      - "16686:16686"  # Jaeger UI (open in browser to view traces)
      - "4317:4317"    # OTLP gRPC (Lena's OTel exporter points here)
    environment:
      - COLLECTOR_OTLP_ENABLED=true
    networks:
      - lena-net

volumes:
  lena-data:
  lena-logs:

networks:
  lena-net:
    driver: bridge
```

```bash
# Start (background)
docker compose -f deploy/docker-compose.yml up -d

# Check Lena is running
docker compose -f deploy/docker-compose.yml ps

# Live logs
docker compose -f deploy/docker-compose.yml logs -f lena

# Expected output: one JSON line per LLM call, budget_pct incrementing with each call
```

### Troubleshooting

**"launchd stopped the process, `launchctl list` shows a non-zero exit code"**: ThrottleInterval was likely triggered — the process crashed multiple times in quick succession. First `launchctl unload` to detach KeepAlive, then run `python3 src/main.py` manually to see the actual error, fix it, then `load` again.

**"systemd `systemctl status lena` shows `(Result: start-limit-hit)`"**: StartLimitBurst triggered. Run `systemctl reset-failed lena` to reset the counter, then `systemctl start lena`. Check `journalctl -u lena -n 50` for the crash cause.

**"No traces visible in Jaeger UI"**: First confirm `docker compose ps` shows jaeger as running, then check that `OTEL_EXPORTER_OTLP_ENDPOINT` is set to `http://jaeger:4317` (the Docker network service name), not `localhost:4317`.

**"`budget_state_change` logs never appear"**: Check whether the `usd` value in `record_cost(usd)` is computed correctly. If you're using Haiku instead of Sonnet, adjust the pricing constants (Haiku: $0.25/1M input + $1.25/1M output — more than 10x cheaper than Sonnet).

---

## § Tool Call Spans + Cost Tracking: Agent-Specific Observability

> **[Pillars: Transparency / Long-horizon Execution]**

### Why Agents Need Dedicated Observability

The classic observability trio — Logs, Metrics, Traces — was designed for the request-response model. One request, one response, P99 latency, error rate.

An agent's execution model is fundamentally different. There are four blind spots that traditional observability tools can't see:

**Blind spot 1: Tool call chains.** A single agent task involves N LLM calls and M tool calls, each with its own latency and success/failure status. Traditional APM tools only see "one HTTP request took 45 seconds." They can't see "after the 3rd LLM call, the `filesystem__read_file` tool call failed, triggering a 4th LLM retry."

**Blind spot 2: Token consumption distribution.** Token usage within a task can be extremely uneven — the first three LLM calls use ~500 tokens each, then the 4th call suddenly uses 15,000 tokens because a tool returned a large payload. Without per-call token tracking, you can't optimize context management.

**Blind spot 3: Reasoning trace.** The agent's "thoughts" behind a tool choice live in the LLM's text output — not in any standard APM field. Without reasoning trace tracking, you can't answer "why did Lena choose tool A instead of tool B" after the fact.

**Blind spot 4: Cost.** Traditional service cost is fixed infrastructure overhead, unrelated to request content. Agent cost is a variable: each LLM call costs differently depending on token count, which depends on task complexity. Without per-request cost tracking, you don't know which task types are burning money.

These four blind spots together mean you can't just bolt Datadog or New Relic onto an agent and call it done. You need a dedicated agent observability layer.

### Key Metrics: The Minimum Viable Set for Agent Observability

The minimum set of metrics every production agent should track:

| Metric | Type | Field Name | Notes |
|--------|------|------------|-------|
| Tool call latency | Span | `tool.name`, `tool.duration_ms`, `tool.success` | One span per tool call |
| Input tokens per request | Counter | `gen_ai.usage.input_tokens` | For context optimization |
| Output tokens per request | Counter | `gen_ai.usage.output_tokens` | For cost calculation |
| Cache hit rate | Gauge | `gen_ai.usage.cache_read_input_tokens` | Prompt cache effectiveness |
| Cost per request | Gauge | `gen_ai.request.cost_usd` | Core of cost observability |
| Reasoning trace | Log | `gen_ai.reasoning_trace` | LLM text output, for debugging |
| Hallucination rate | Gauge | `gen_ai.hallucination_rate` | Optional; requires eval pipeline |

### OpenTelemetry Semantic Conventions for GenAI

The OpenTelemetry community published a GenAI Semantic Conventions specification in 2025 ([opentelemetry.io/docs/specs/semconv/gen-ai/](https://opentelemetry.io/docs/specs/semconv/gen-ai/)), standardizing span attribute names for LLM calls.

This matters: if every agent framework invents its own field names, switching observability backends requires rewriting all dashboards. Following the conventions means your agent data is directly recognized by Grafana / Langfuse / Honeycomb without an adapter layer.

Core fields (from OTel GenAI Semantic Conventions v1.36.0, [opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/)):

```
# Enable the latest experimental spec (v1.36.0+)
# OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental

gen_ai.operation.name      = "chat"                      # required: operation type
gen_ai.provider.name       = "anthropic"                 # required: provider identifier
gen_ai.request.model       = "claude-sonnet-4-6"         # conditionally required: model at request time
gen_ai.response.model      = "claude-sonnet-4-6-20261001" # recommended: actual model version in response
gen_ai.usage.input_tokens  = 4230                        # recommended: total input tokens
gen_ai.usage.output_tokens = 512                         # recommended: total output tokens
gen_ai.usage.cache_read.input_tokens     = 3800          # recommended: tokens read from provider cache
gen_ai.usage.cache_creation.input_tokens = 200           # recommended: tokens written to provider cache
gen_ai.tool.name           = "filesystem__read_file"     # tool call span required: tool name
gen_ai.tool.call.id        = "call_abc123"               # tool call span recommended: unique ID
gen_ai.tool.type           = "function"                  # tool call span recommended: type
```

**Agent-specific span attributes** (from [opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)):

```
gen_ai.operation.name      = "invoke_agent"              # agent invocation operation
gen_ai.agent.name          = "ResearchAgent"             # agent name (conditionally required)
gen_ai.agent.id            = "agent-001"                 # agent unique ID (conditionally required)
gen_ai.agent.version       = "0.11.0"                    # agent version (conditionally required)
gen_ai.conversation.id     = "conv-xyz"                  # conversation ID (conditionally required when available)
```

Span naming conventions:
- Inference span → `chat claude-sonnet-4-6` (`{gen_ai.operation.name} {gen_ai.request.model}`)
- Tool execution span → `execute_tool filesystem__read_file`
- Agent invocation span → `invoke_agent ResearchAgent`

The field `gen_ai.usage.cache_read.input_tokens` corresponds to Anthropic Prompt Cache (released August 2024): cached token reads cost 10% of normal input tokens. Tracking cache hit rate lets you quantify the cost savings from prompt engineering — connecting back to the context engineering work in Ch10.

> Note: instrumentation from before v1.36.0 uses old field names (e.g., `gen_ai.usage.prompt_tokens`). To migrate, set the environment variable `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`.

### Full Code: Adding Spans + Cost Calculation to Lena

```python
# code/lena-v0.22/src/observability/agent_tracer.py
# ~55 lines: OTel Semantic Conventions for GenAI + tool call spans + cost calculation

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import structlog
from opentelemetry import trace
from opentelemetry.trace import Span

log = structlog.get_logger(__name__)

# Claude Sonnet 4.6 pricing (2026, source: https://www.anthropic.com/api#pricing)
COST_PER_INPUT_TOKEN   = 3.0 / 1_000_000   # $3 / 1M tokens
COST_PER_OUTPUT_TOKEN  = 15.0 / 1_000_000  # $15 / 1M tokens
COST_PER_CACHE_READ    = 0.3 / 1_000_000   # $0.30 / 1M tokens (90% discount)
COST_PER_CACHE_WRITE   = 3.75 / 1_000_000  # $3.75 / 1M tokens (25% premium)


@dataclass
class LLMCallMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = field(init=False)

    def __post_init__(self):
        self.cost_usd = (
            self.input_tokens       * COST_PER_INPUT_TOKEN
            + self.output_tokens    * COST_PER_OUTPUT_TOKEN
            + self.cache_read_tokens * COST_PER_CACHE_READ
            + self.cache_write_tokens * COST_PER_CACHE_WRITE
        )


class AgentTracer:
    """Add tool call spans + cost calculation to Lena's agent loop."""

    def __init__(self, tracer: trace.Tracer):
        self._tracer = tracer
        self._session_cost = 0.0

    @contextmanager
    def llm_span(self, model: str):
        """Wrap an LLM call and record GenAI semantic convention fields."""
        with self._tracer.start_as_current_span("gen_ai.completion") as span:
            span.set_attribute("gen_ai.system", "anthropic")
            span.set_attribute("gen_ai.request.model", model)
            t0 = time.monotonic()
            yield span
            span.set_attribute("gen_ai.duration_ms", int((time.monotonic() - t0) * 1000))

    def record_llm_usage(self, span: Span, usage) -> LLMCallMetrics:
        """Extract and record token metrics from the Anthropic SDK usage object."""
        metrics = LLMCallMetrics(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0),
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0),
        )
        # Write to OTel span (following GenAI semantic conventions)
        span.set_attribute("gen_ai.usage.input_tokens",  metrics.input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", metrics.output_tokens)
        span.set_attribute("gen_ai.usage.cache_read_input_tokens",     metrics.cache_read_tokens)
        span.set_attribute("gen_ai.usage.cache_creation_input_tokens", metrics.cache_write_tokens)
        span.set_attribute("gen_ai.request.cost_usd", round(metrics.cost_usd, 6))

        self._session_cost += metrics.cost_usd
        log.info(
            "llm_call_complete",
            input_tokens=metrics.input_tokens,
            output_tokens=metrics.output_tokens,
            cache_read_tokens=metrics.cache_read_tokens,
            cost_usd=round(metrics.cost_usd, 6),
            session_cost_usd=round(self._session_cost, 4),
        )
        return metrics

    @contextmanager
    def tool_span(self, tool_name: str, call_id: str):
        """Wrap a single tool call and record latency and success/failure."""
        with self._tracer.start_as_current_span(f"gen_ai.tool.call") as span:
            span.set_attribute("gen_ai.tool.name", tool_name)
            span.set_attribute("gen_ai.tool.call.id", call_id)
            t0 = time.monotonic()
            try:
                yield span
                span.set_attribute("gen_ai.tool.success", True)
            except Exception as e:
                span.set_attribute("gen_ai.tool.success", False)
                span.set_attribute("gen_ai.tool.error", str(e))
                log.warning("tool_call_failed", tool=tool_name, error=str(e))
                raise
            finally:
                duration_ms = int((time.monotonic() - t0) * 1000)
                span.set_attribute("gen_ai.tool.duration_ms", duration_ms)
                log.debug("tool_call", tool=tool_name, call_id=call_id,
                          duration_ms=duration_ms)
```

Usage inside the agent loop:

```python
# Integration inside AgentLoop.step()
tracer_wrapper = AgentTracer(tracer)

with tracer_wrapper.llm_span(model="claude-sonnet-4-6") as span:
    resp = await self._call_llm()
    metrics = tracer_wrapper.record_llm_usage(span, resp.usage)

# For each tool call
for tool_call in resp.tool_calls:
    with tracer_wrapper.tool_span(tool_call.name, tool_call.id):
        result = await execute_tool(tool_call)
```

After running, the Jaeger UI shows each LLM call with its tool call spans nested underneath. Click any span to see token counts, cost, tool name, and duration. The entire task's call tree is visible at a glance.

### Visualization Tool Comparison: Four Options

| Tool | Category | Deployment | Best For |
|------|----------|------------|----------|
| **Jaeger** | Distributed tracing (native OTel) | Self-hosted Docker | Local dev debugging, trace visualization |
| **Langfuse** | Agent-specific observability | Self-hosted / cloud | Eval + trace in one place, open-source auditable |
| **Helicone** | LLM call proxy + analytics | Cloud SaaS | Fast setup, zero OTel code changes required |
| **Phoenix (Arize)** | LLM/AI observability platform | Self-hosted / cloud | Embedding analysis, hallucination detection |

**Recommended strategy**:

- **Local development**: Jaeger (`docker run -p 16686:16686 jaegertracing/all-in-one`, 5-second startup)
- **Team projects / eval integration needed**: Langfuse (open-source, supports LLM-as-judge and trace linkage, directly compatible with the Ch21 eval pipeline)
- **Fast prototype validation (don't want to change code)**: Helicone (add a proxy in front of the API base URL, zero instrumentation)
- **Embedding drift detection / hallucination rate monitoring**: Phoenix (suited for RAG agents, connecting to Ch9's knowledge base system)

### Data-Driven Optimization Example

Here's a real optimization scenario that occurred in a production agent system: after enabling per-request token tracking, a team discovered that P50 TTFT (Time-to-First-Token) dropped by about 60% after enabling prompt caching. The reason: their system prompt (~4,000 tokens) was being sent from scratch on every request. With caching enabled, those tokens cost 10% of normal and the latency also dropped significantly because the KV cache computation was skipped.

This optimization was only discoverable and measurable because `cache_read_input_tokens` and TTFT were being tracked. Without observability, this opportunity stays buried in the billing console forever.

```python
# Track cache hit rate with structlog (summarize every 100 calls)
class CacheStats:
    def __init__(self):
        self.total_input = 0
        self.cache_read = 0
        self.call_count = 0

    def update(self, metrics: LLMCallMetrics):
        self.total_input += metrics.input_tokens
        self.cache_read += metrics.cache_read_tokens
        self.call_count += 1
        if self.call_count % 100 == 0:
            hit_rate = self.cache_read / self.total_input if self.total_input > 0 else 0
            log.info("cache_stats", hit_rate=f"{hit_rate:.1%}",
                     total_calls=self.call_count,
                     avg_input_tokens=self.total_input // self.call_count)
```

Expected output (after 100 calls):
```
[info] cache_stats hit_rate=78.3% total_calls=100 avg_input_tokens=4230
```

A 78% cache hit rate means 78% × 90% = 70% of your token costs are being billed at the discounted rate. If the hit rate is below 40%, the system prompt structure needs optimization (caching requires a stable prompt prefix).

> **What this section gives you**:
> 1. **Standardize agent traces with OTel Semantic Conventions** — follow the standard field names and plug into any OTel-compatible observability platform without vendor lock-in
> 2. **Track per-tool-call spans and per-request costs** — identify slow tools and expensive tasks, the foundation for agent performance optimization
> 3. **Choose the right observability tool for the context** — know when to use Jaeger / Langfuse / Helicone / Phoenix, and avoid introducing heavyweight platforms when they aren't warranted

---

## Beat 7 — Design Note

> **Why Not Just Alert After the Fact? — Why Cost Monitoring Must Be a Pre-Call Circuit Breaker**

The most straightforward cost monitoring approach: call the cloud billing API, pull spend hourly, send a Slack alert when a threshold is crossed, then handle manually.

This approach has three concrete engineering flaws:

**Flaw 1: Time window problem.** AWS Cost Explorer data has an 8–24 hour lag; Google Cloud Billing has a 1–6 hour lag. A dead-loop agent can generate $30+ in fees within an hour. By the time the alert reaches your phone, the damage has already happened.

**Flaw 2: Depends on human response.** Alerts notify humans, and humans take time to react. An alert that fires at 3 AM may not be acknowledged until 8 AM. An agent system's design goal is autonomous operation — "requires human intervention to stop" is a fundamental contradiction.

**Flaw 3: No graceful degradation.** A hard stop mid-task leaves data in inconsistent state (a half-written file, a half-sent message). The pre-call circuit breaker's THROTTLE state gives the task a "graceful slowdown" window — finishing the current work within budget before stopping.

Current choice: check `BudgetController` before each LLM call in the agent loop. This is a direct extension of nanoClaw's `budget.py` (line 84) design, adding gradual throttle semantics.

Limitation: this design only controls LLM call frequency, not the side-effect frequency of third-party tools (like an email-sending tool or a database write tool). If you need rate control over all tool calls, add an independent rate limiter in the PreToolUse hook layer. This is an open problem: how to uniformly control agent operations that have both cost and side effects — no widely-accepted standard exists today.

> Anthropic's official [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) emphasizes the "Transparency" principle: every step of an agent's behavior should be auditable. This chapter's structured logs + OTel spans are the concrete implementation of that principle: every LLM call is not just recorded but given a traceable `trace_id`, making any historical decision replayable.

---

## Narrative Hook

Lena can now run 24/7 in production, every decision logged, every dollar tracked.

But one dimension remains unsolved: can she generalize into any specialized agent? A Lena for code review, a Lena for market research, a Lena for calendar management — all sharing one runtime but with different tool sets, different system prompts, different skill packages. The next chapter opens that path: from general-purpose runtime to specialized agent.

---

## Navigation

➡️ **[Ch 23. Specialization Pattern](../ch23-specialization/README-en.md)** — Agent Squad vs. CrewAI, derivative framework analysis

[← Ch 21. Evals](../ch21-evals/README.md) · [📘 Table of Contents](../../README.md)
