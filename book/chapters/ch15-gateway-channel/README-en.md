# Ch 15 — Gateway and Channel: Moving Your Agent into Telegram

---

## Beat 1 — Roadmap

```
Ch 13 Input Safety → Ch 14 Execution Safety → [Ch 15 you are here] → Ch 16 MessageBus → Ch 17 Heartbeat
```

This chapter starts from a **CLI Lena that dies after every run** (the product of v0.14) and works through the Gateway's dual-entry design and the BaseChannel abstraction, arriving at **Lena v0.15** — she runs in the background continuously, Telegram and Console are two hot-swappable channels, and she auto-reconnects with exponential backoff when the connection drops.

Along the way there's an intuition trap: you may assume a channel is part of the agent and should be compiled into the core code. But the right answer is **channels are plugins; the core doesn't know channels exist**. That inversion is the single most valuable mental model to take away from this chapter.

What needs to be built here isn't much — about 200 lines of new code — but the architectural leap is the largest in the whole book: Lena goes from a command-line utility to a genuine always-on process, capable of receiving Telegram messages while you sleep, responding to HTTP calls, or waiting for cron to trigger her at 2 a.m. to do something.

**What Lena gains this chapter**: from v0.14 (CLI exits after execution) → v0.15 (persistent background, Telegram + Console dual-channel hot-swappable, exponential backoff on disconnect).

> **🧠 Intelligence Increment (v0.14 → v0.15)**: Lena runs across interfaces for the first time — Gateway + BaseChannel abstraction transforms her from a "run-and-die" CLI tool into a persistent background process; Telegram and Console are hot-swappable; core code has no knowledge of channels. This chapter teaches readers how to grow multi-interface adaptability into their own agent.

![Gateway / Channel message routing](diagrams/gateway-channel.svg)

---

## Beat 2 — Motivation

Run this command:

```bash
python3 lena-v0.14/main.py
```

You type a question, Lena answers, and then — the process exits. Close the terminal, and Lena is gone.

This isn't merely "inconvenient." It's a class of things that are fundamentally impossible to accomplish:

- You open Telegram on your phone; there's no way to send Lena a message
- You want Lena to monitor some data every hour; she has no way to stay alive
- Your cron job triggers at 2 a.m.; you're asleep — nobody can start the process

**Two obvious solution directions, both dead ends:**

First direction: write an infinite `while True` loop in the script. The problem: this can only handle one input source — you've hard-coded reading from `stdin`. Want to handle Telegram and Discord simultaneously? You need to handle two protocols inside the same `while True`, and the code quickly turns into a mess. The more fundamental problem: Telegram's polling is asynchronous; Discord's gateway protocol requires a heartbeat to maintain a long connection. The lifecycles of these two protocols are completely different. Stuffing them into one loop produces masses of platform-specific `if/elif` branches that are a maintenance nightmare.

Second direction: run a separate process for each channel. A Telegram process and a Discord process, independent. The problem: they share the same Lena conversation history and tool execution context — there's no way to synchronize that state across two processes. You could use Redis or a database as a middle layer, but that turns an application-level problem into an infrastructure problem, dramatically raising complexity.

**The real answer**: a persistent Gateway process that centrally manages all connection entry points and routes messages to a single AgentLoop. Each channel registers as a plugin, responsible only for "how to receive messages and how to send messages," with no knowledge of the AgentLoop. That's what this chapter builds.

---

## Beat 3 — Theory

> This section is pure theory, divided into four subsections.

Anthropic's Managed Agents architecture (2026-04) frames this problem at the abstraction level of an operating system:

> "Operating systems solved the 'programs as yet unthought of' problem by virtualizing hardware into abstractions—process, file—general enough for programs that didn't exist yet. Managed Agents does the same for AI agents: session, harness, sandbox."
> (Source: Anthropic, *Scaling Managed Agents*, 2026-04-08)

This chapter's Gateway + Channel corresponds to exactly the **middle layer** of those three: it virtualizes the "where the user comes from" variable — Lena's AgentLoop doesn't need to know whether a message came from Discord, CLI, or email; the Gateway handles the translation.

### 3.1 What Is a Gateway, Really?

At first glance, a Gateway looks like "a server that listens for messages." But it's more accurately described as **a message traffic hub** — it doesn't produce messages, doesn't consume them, just uniformly formats messages from different entry points and delivers them to the AgentLoop; and sends AgentLoop's outputs back to the corresponding exit.

This definition has two key consequences.

**Consequence 1: The Gateway is transparent to channels.** It doesn't know whether a message came from Telegram or Discord; it only knows "there's a message to process, from user ID=xxx, content=yyy." Conversely, the AgentLoop doesn't know which platform its reply will ultimately be delivered to. The Gateway carries the adaptation responsibility between these two layers.

**Consequence 2: The Gateway's core state is a connection table, not conversation history.** The connection table records "what state each channel is currently in"; conversation history is the AgentLoop's internal state, which the Gateway never touches. This division of responsibility keeps both parts simple: the Gateway can crash and restart without losing conversation context (because context lives in the AgentLoop); the AgentLoop can be indifferent to where messages came from (because formatting has already been completed at the Gateway layer).

Convention: **Gateway** = the process that manages connection lifecycles + message routing; **Channel** = a specific message entry/exit plugin (Telegram / Discord / Console, etc.); **AgentLoop** = the core logic that processes messages, calls tools, and generates replies. The three responsibilities don't overlap — they're the three independent concerns of this chapter's architecture.

### 3.2 The Channel-as-Plugin Design Philosophy

Why make channels plugins rather than writing them directly into the AgentLoop?

Imagine two implementation approaches.

**Approach A (compile-time integration)**: AgentLoop directly imports `TelegramBot`, handles Telegram webhook format, Discord gateway protocol, and other message push formats in its own message loop. Every time you add a platform, you change AgentLoop's core code. With 10 platforms, AgentLoop imports 10 SDKs and handles 10 format differences.

**Approach B (channel as plugin)**: AgentLoop only knows one abstract interface — "send message" and "receive message." Each platform implements this interface, registers during configuration, and loads on demand at runtime. Adding a new channel requires zero changes to AgentLoop.

Approach A's problem isn't just "inelegant." It couples two completely different **causes of change** together: "message routing logic changed" and "connected platform changed" — these two things should evolve independently. In software design this is called the Single Responsibility Principle, but the more intuitive understanding is: **a change to Telegram's API today should not cause a git diff in the AgentLoop file.**

In production systems, the value of this separation is clearest in specific scenarios: switching a daily digest task from Discord delivery to a different messaging platform requires changing only one line in the configuration file — the delivery channel is configuration, the intelligence is code. This separation seems like unnecessary abstraction at the start, but its value becomes immediately apparent the first time you need to switch channels.

> The core conclusion behind channel-as-plugin comes from the "separation of concerns" software design principle (source: *A Philosophy of Software Design* by John Ousterhout, 2018, Chapter 4 "Modules Should Be Deep" — no need to read it fully, just know this conclusion: **put things with different rates of change in different modules**).

Worth noting: this design can be taken to a more extreme form in production. The `src/channels/plugins/catalog.ts` in a production-grade implementation achieves a complete channel discovery mechanism — each channel is an independent npm package, declared as a channel through the `openclaw` field in `package.json`. The gateway process dynamically scans installed packages at startup to discover channels without needing to recompile. This chapter's lena-v0.15 is the educational version, using static registration instead of dynamic discovery, dramatically reducing complexity while preserving the core idea.

There's also an honest difference in code scale between the teaching version and the production version that's worth acknowledging: nano-claw's `gateway/server.ts` is 219 lines, describing the complete message routing skeleton. A production `src/gateway/` directory contains around 230 files, handling authentication, TLS, Tailscale exposure, canvas host, config hot-reload, multi-account management, health checks, metrics... and dozens of other production concerns. This isn't over-engineering — it's the real complexity of production systems. This chapter gets you to the 219-line teaching version to understand the core principles; by the time you need those 230-file production details, you'll have enough context to read and understand them.

### 3.3 The Math Intuition Behind Exponential Backoff

The simplest reconnection strategy after a dropped connection is immediate retry. The problem: if the server is briefly unreachable (network hiccup, server restart, Telegram maintenance), all clients retrying simultaneously create a **Thundering Herd** — the server gets hit by a flood of requests the moment it recovers, potentially overloading it again, forming a positive feedback loop.

Exponential backoff breaks this cycle:

```
Intuition: after the n-th failure, wait min(initial_delay × 2^n, ceiling) milliseconds before retrying
Math: delay(n) = min(d₀ × 2ⁿ, d_max)
```

The parameter choices aren't arbitrary; each has an engineering rationale:

- `d₀ = 5s` (initial delay): network hiccups typically recover within 1–5 seconds; waiting 5 seconds first covers the vast majority of brief disruptions
- `d_max = 300s` (5-minute ceiling): outages longer than 5 minutes typically require human intervention; waiting indefinitely is pointless and makes users think the agent has crashed
- `max_attempts = 10`: the waiting window for 10 attempts is roughly 5s + 10s + 20s + 40s + 80s + 160s + 300s + 300s + 300s + 300s ≈ 1515s ≈ 25 minutes, covering the vast majority of brief outage scenarios

Adding random jitter (±10%) staggers the reconnect times of multiple channels. Without jitter, if you're running 5 bots that all drop at the same moment, they'll all send reconnect requests at exactly the same time; with ±10% randomness, the 5 requests spread across a 4.5s–5.5s window, smoothing the load considerably.

These parameters match the production implementation (`server-channels.ts:12-17`): `initialMs: 5_000, maxMs: 5 * 60_000, factor: 2, jitter: 0.1`, max 10 retries. This is a production-validated parameter set, ready to reuse.

Convention: **backoff** = the delay strategy before each retry, spreading retries across time; **jitter** = adding randomness to the delay to stagger multiple clients' retry times. The two are typically used together.

### 3.4 The Complete Message Flow Path

Before writing code, let's walk through the complete path from "user sends a Telegram message" to "Lena replies," so every piece of code has a clear sense of place:

```
User sends Telegram message
    │
    ▼
[TelegramBot polling] — this is node-telegram-bot-api internally, polls Telegram API every second
    │ bot.on("message") fires
    ▼
[TelegramChannel.onMessage handler]
    │ allowFrom check
    │ passes → calls Gateway-injected handler(userId, content)
    ▼
[GatewayServer]
    │ handler = agent.run(content)
    ▼
[AgentLoop.run()]
    │ LLM inference → possible tool calls → generates reply
    ▼
[GatewayServer handler returns reply string]
    │
    ▼
[TelegramChannel]
    │ bot.sendMessage(chatId, reply)
    ▼
User receives Telegram reply
```

The complete path has five actors, each doing only its own job: TelegramBot handles protocol details, TelegramChannel handles the allowlist and formatting, Gateway handles routing, AgentLoop handles intelligence, Telegram API handles final delivery.

This path is complete in this chapter's code. You can add `console.log` at each layer to trace message flow — this is an effective debugging method.

---

## Beat 4 — Skeleton

Let's build the minimal skeleton of a Gateway that can connect two channels and route a message end-to-end:

```typescript
// lena-v0.15/gateway/server.ts — minimal skeleton (~45 lines)
import { WebSocketServer } from "ws";
import * as http from "http";

// BaseChannel interface: each channel only needs to implement these four things
interface BaseChannel {
  readonly id: string;
  connect():                                            Promise<void>;
  disconnect():                                         Promise<void>;
  // handler is injected by Gateway; called when channel receives a message; returns Lena's reply
  onMessage(handler: (userId: string, content: string) => Promise<string>): void;
  send(userId: string, content: string):                Promise<void>;
}

export class GatewayServer {
  private channels: BaseChannel[] = [];

  // Register a channel: called at runtime, no changes to GatewayServer source code needed
  register(ch: BaseChannel) {
    this.channels.push(ch);
  }

  async start(wsPort = 8765, httpPort = 3000) {
    // 1. WebSocket server (for web clients and internal debugging)
    const wss = new WebSocketServer({ port: wsPort });
    console.log(`[Gateway] WebSocket :${wsPort}`);

    // 2. HTTP server (for webhooks and curl testing)
    const server = http.createServer();
    server.listen(httpPort);
    console.log(`[Gateway] HTTP :${httpPort}`);

    // 3. Connect all registered channels, injecting the message handler
    for (const ch of this.channels) {
      ch.onMessage(async (userId, content) => {
        // Skeleton phase: echo back directly; AgentLoop is wired in during Beat 5
        return `[echo] ${content}`;
      });
      await ch.connect();
      console.log(`[Gateway] Channel [${ch.id}] connected`);
    }
  }
}
```

Running this skeleton, you should see (all three lines within ~0.5 seconds):

```
[Gateway] WebSocket :8765
[Gateway] HTTP :3000
[Gateway] Channel [console] connected
```

The Console prompt appears; type anything and you get `[echo] your input`. This proves the message flow path is live — user input → channel receives → handler called → return value → channel sends back to user. The handler is still just an echo; AgentLoop isn't wired in yet.

Notice the design of the `register()` method: it's called at runtime, not hard-coded into `GatewayServer` at compile time. This means you can register channels as needed in `main.ts`, and `GatewayServer`'s code never needs to know which channels exist. This is "channel as plugin" at the code level.

---

## Beat 5 — Incremental Assembly

Starting from the skeleton, we add four features that a real system needs:

| Extension | Why It's Needed | How to Add |
|-----------|----------------|------------|
| Wire in AgentLoop | Echo has no intelligence; need LLM to process messages | Replace `onMessage` handler with `agentLoop.run()` |
| Exponential backoff reconnection | Should not give up on Telegram after a network hiccup | Wrap a retry loop + `ExponentialBackoff` inside channel's `connect()` |
| `allowFrom` whitelist | Prevent strangers from consuming LLM resources; channel-layer filtering is earlier and cleaner than AgentLoop-layer | Channel checks `allowFrom` on message receipt; silently drops if not in list |
| `GET /status` runtime snapshot | Monitor channel connection state and retry count; prepares for future monitoring dashboard | Add `/status` endpoint to Gateway HTTP service returning per-channel snapshot |

**Extension 1: Wire in AgentLoop**

Replace the `onMessage` handler with a real AgentLoop — only changes to `GatewayServer`'s constructor and `start` method:

```typescript
// lena-v0.15/gateway/server.ts (with AgentLoop wired in)
import { AgentLoop } from "../agent/loop";

export class GatewayServer {
  constructor(private readonly agent: AgentLoop) {}  // inject AgentLoop

  async start(wsPort = 8765, httpPort = 3000) {
    // ... WS/HTTP server startup same as skeleton, omitted

    for (const ch of this.channels) {
      ch.onMessage(async (userId, content) => {
        // Replace echo with real AgentLoop
        const reply = await this.agent.run(content);
        return reply;
      });
      await ch.connect();
    }
  }
}
```

After starting, type "What time is it?" in the Console. Lena should call the `get_time` tool and reply. Terminal prints:

```
[Gateway] Channel [console] connected
You: What time is it?
[Lena] It's 2026-05-05 14:23:07 CST
```

Once AgentLoop is wired in, Gateway and channel retreat to the "pipe" role — they only carry messages; no LLM inference logic involved.

**Extension 2: ExponentialBackoff Class**

Backoff strategy as an independent module rather than buried inside the channel — multiple channels may share the same backoff logic, and it's easier to test in isolation:

```typescript
// lena-v0.15/backoff.ts
export class ExponentialBackoff {
  private attempt = 0;

  constructor(
    private readonly initialMs  = 5_000,   // first wait 5s
    private readonly maxMs      = 300_000, // ceiling 5min (openclaw server-channels.ts:12-17 params)
    private readonly maxRetries = 10,
    private readonly jitter     = 0.1,    // ±10% random jitter
  ) {}

  nextDelay(): number {
    const base     = Math.min(this.initialMs * 2 ** this.attempt, this.maxMs);
    const jitterMs = base * this.jitter * (Math.random() * 2 - 1);
    this.attempt++;
    return Math.round(base + jitterMs);
  }

  reset()     { this.attempt = 0; }
  exhausted() { return this.attempt >= this.maxRetries; }
  get count() { return this.attempt; }
}
```

Verify the backoff sequence (run a small script):

```typescript
const b = new ExponentialBackoff();
for (let i = 0; i < 5; i++) {
  console.log(`attempt ${i + 1}: ${b.nextDelay()}ms`);
}
```

Should print something like (slightly varying each run due to randomness, but the doubling trend holds):

```
attempt 1: 5123ms
attempt 2: 10234ms
attempt 3: 20198ms
attempt 4: 40087ms
attempt 5: 80312ms
```

**Extension 3: TelegramChannel with Reconnection**

TelegramChannel is the most complex part of this chapter's code, because it handles three things simultaneously: initial connection, disconnect detection, and backoff reconnection. Breaking them apart makes it clear:

```typescript
// lena-v0.15/channels/telegram.ts (key logic; full version in code/)
import TelegramBot from "node-telegram-bot-api";  // npm install node-telegram-bot-api
import { ExponentialBackoff } from "../backoff";

export class TelegramChannel {
  readonly id = "telegram";
  private bot?: TelegramBot;
  private handler?: (userId: string, content: string) => Promise<string>;
  private backoff = new ExponentialBackoff();
  private aborted = false;  // set to true after disconnect(); prevents further reconnection

  constructor(
    private readonly token:     string,
    private readonly allowFrom: string[],  // ["*"] = allow everyone, ["123456"] = specific user only
  ) {}

  onMessage(handler: (userId: string, content: string) => Promise<string>) {
    this.handler = handler;
  }

  // connect() = outer backoff loop
  async connect(): Promise<void> {
    this.aborted = false;
    this.backoff.reset();

    while (!this.aborted) {
      try {
        await this.tryConnect();   // inner: attempt one real connection
        this.backoff.reset();
        return;
      } catch (err) {
        if (this.aborted) return;  // disconnect() was called; stop reconnecting
        if (this.backoff.exhausted()) {
          console.error(`[Telegram] Giving up after ${this.backoff.count} attempts`);
          return;
        }
        const delay = this.backoff.nextDelay();
        console.log(
          `[Telegram] Connection failed; retrying in ${Math.round(delay / 1000)}s` +
          ` (attempt ${this.backoff.count} / max 10): ${String(err)}`
        );
        await new Promise<void>(r => setTimeout(r, delay));
      }
    }
  }

  // tryConnect() = one real connection attempt; throws on failure for outer layer to catch
  private async tryConnect(): Promise<void> {
    this.bot = new TelegramBot(this.token, { polling: true });

    this.bot.on("message", async (msg) => {
      const userId  = msg.from?.id?.toString() ?? "";
      const content = msg.text ?? "";
      if (!content) return;

      // allowFrom check: done at the channel layer, not the AgentLoop layer
      const allowed = this.allowFrom.includes("*") || this.allowFrom.includes(userId);
      if (!allowed) {
        console.log(`[Telegram] Ignoring unauthorized user ${userId}`);
        return;  // silently drop; no reply, no error
      }

      const reply = await this.handler?.(userId, content) ?? "";
      await this.bot!.sendMessage(msg.chat.id, reply);
    });

    console.log("[Telegram] Connected, polling active");

    // Wait for polling_error to fire (= network disconnect, needs reconnection)
    await new Promise<void>((_, reject) => {
      this.bot!.on("polling_error", (err) => {
        console.error(`[Telegram] polling_error: ${err.message}`);
        reject(err);  // throw to outer catch → triggers backoff reconnection
      });
    });
  }

  async disconnect() {
    this.aborted = true;
    await this.bot?.stopPolling();
  }

  snapshot() {
    return {
      id:      this.id,
      status:  this.aborted ? "stopped" as const : "running" as const,
      retries: this.backoff.count,
    };
  }
}
```

Notice that `allowFrom` checking is done at the channel layer, not the AgentLoop layer. This is a deliberate design decision: **the AgentLoop always processes only messages that have passed security checks**; it doesn't need to know "should this message be processed at all."

Why not put `allowFrom` in the AgentLoop layer? Three reasons:

**Reason 1: Prevent allowlist bypass.** If AgentLoop checks the allowlist, the message has already entered AgentLoop's processing queue — even if rejected, it has already consumed resources (parsing, formatting, queueing). Checking at the channel layer means unauthorized messages never enter the AgentLoop at all — earlier and cleaner.

**Reason 2: Different channels have different policies.** Telegram direct messages don't need `requireMention`; bots in group chats typically require `@botname` to trigger — that logic belongs to the channel, not the AgentLoop. Putting it in the AgentLoop means the AgentLoop needs to sense "which channel sent this message in which context," dramatically increasing complexity.

**Reason 3: Fail-safe design.** The earlier the security check, the smaller the impact radius. A channel-layer rejection silently drops a message at most; an AgentLoop-layer rejection means you've already made an LLM call before saying "sorry, I can't reply to you" — wasting tokens and revealing "this agent is running" to unauthorized users.

Placing security checks in an outer layer also has a bonus: different channels can have different `allowFrom` policies without the AgentLoop needing special-case logic for each channel.

**Extension 4: ConsoleChannel + `/status` Endpoint**

ConsoleChannel is a local debugging workhorse: zero dependencies, no token required, talk directly to Lena in the terminal. Its implementation is simple, but its value is this: before connecting a real Telegram, you can test the entire Gateway + AgentLoop flow using Console channel, with no need to apply for a Bot Token or configure a webhook:

```typescript
// lena-v0.15/channels/console.ts
import * as readline from "readline";

export class ConsoleChannel {
  readonly id = "console";
  private handler?: (userId: string, content: string) => Promise<string>;
  private rl?: readline.Interface;
  private running = false;

  onMessage(handler: (userId: string, content: string) => Promise<string>) {
    this.handler = handler;
  }

  async connect() {
    this.running = true;
    this.rl = readline.createInterface({ input: process.stdin, prompt: "You: " });
    this.rl.prompt();
    this.rl.on("line", async (line) => {
      const content = line.trim();
      if (!content || !this.handler) { this.rl?.prompt(); return; }
      const reply = await this.handler("console-user", content);
      console.log(`[Lena] ${reply}`);
      this.rl?.prompt();
    });
    console.log("[Console] Connected; type messages directly");
  }

  async disconnect() { this.running = false; this.rl?.close(); }
  async send(_: string, content: string) { console.log(`[Lena] ${content}`); }
  snapshot() { return { id: this.id, status: "running" as const, retries: 0 }; }
}
```

Add a `/status` endpoint to the Gateway HTTP service:

```typescript
// inside gateway/server.ts, in the handleHttp method
if (req.method === "GET" && req.url === "/status") {
  const snapshot = {
    channels:       this.channels.map((ch) => ch.snapshot()),
    wsConnections:  this.wsConns.size,
    uptime:         process.uptime(),
  };
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(JSON.stringify(snapshot, null, 2));
  return;
}
```

`curl http://localhost:3000/status` should return:

```json
{
  "channels": [
    { "id": "console", "status": "running", "retries": 0 }
  ],
  "wsConnections": 0,
  "uptime": 42.3
}
```

The value of the `uptime` field: if you see an uptime of 5 seconds, the process just restarted — an implicit "did a crash happen?" signal. The `retries` field is equally meaningful: if you see Telegram channel's retries at 3, the connection dropped and reconnected 3 times while you were completely unaware — that's the proof that the backoff mechanism is working correctly.

These four extensions together form the core of lena-v0.15. Their relationship: wiring in AgentLoop gives Lena intelligence; backoff reconnection lets her self-heal during network hiccups; the `allowFrom` whitelist makes her respond only to authorized users; the runtime snapshot lets you know her health state at any moment. Each is independent — you can remove any one without affecting the other three. This orthogonality is a byproduct of the channel-as-plugin architecture: once each concern is cleanly separated, every module can evolve independently.

---

## Beat 6 — Running Verification

Let's put the complete Lena v0.15 together and run it:

```typescript
// lena-v0.15/main.ts
import { GatewayServer } from "./gateway/server";
import { AgentLoop }      from "./agent/loop";
import { ConsoleChannel } from "./channels/console";
import { TelegramChannel } from "./channels/telegram";

async function main() {
  const agent   = new AgentLoop();
  const gateway = new GatewayServer(agent);

  // Console channel: local debugging, zero dependencies, always registered
  gateway.register(new ConsoleChannel());

  // Telegram channel: only register when token is configured
  const token     = process.env.TELEGRAM_BOT_TOKEN;
  const allowFrom = (process.env.TELEGRAM_ALLOW_FROM ?? "*").split(",").map(s => s.trim());
  if (token) {
    gateway.register(new TelegramChannel(token, allowFrom));
    console.log(`[Main] Telegram channel configured, allowFrom: ${allowFrom.join(", ")}`);
  } else {
    console.log("[Main] TELEGRAM_BOT_TOKEN not set; skipping Telegram channel");
  }

  await gateway.start();

  console.log("\n✓ Lena v0.15 started");
  console.log("  WebSocket: ws://localhost:8765");
  console.log("  HTTP POST: http://localhost:3000/message");
  console.log("  Status:    http://localhost:3000/status\n");

  // Graceful shutdown: close all channels on Ctrl+C
  process.on("SIGINT", async () => {
    console.log("\n[Main] Shutting down...");
    await gateway.stop();
    process.exit(0);
  });
}

main().catch((err) => { console.error("Startup failed:", err); process.exit(1); });
```

**Start (Console-only mode, no token needed)**:

```bash
cd code/lena-v0.15
npm install    # first time only, ~30 seconds
npm start
```

Expected output (all content within 1–2 seconds):

```
[Main] TELEGRAM_BOT_TOKEN not set; skipping Telegram channel
[Gateway] WebSocket :8765
[Gateway] HTTP :3000
[Gateway] Channel [console] started
[Console] Connected; type messages directly

✓ Lena v0.15 started
  WebSocket: ws://localhost:8765
  HTTP POST: http://localhost:3000/message
  Status:    http://localhost:3000/status

You:
```

**Verify three paths** (run in another terminal while keeping Lena running):

```bash
# Path 1: Console (type directly in the Lena terminal)
# You: What time is it?
# [Lena] It's 2026-05-05 14:23:07 CST

# Path 2: HTTP POST
curl -s -X POST http://localhost:3000/message \
  -H "Content-Type: application/json" \
  -d '{"content": "Hello"}'
# Expected return (in ~2-3 seconds):
# {"reply":"Hello! I'm Lena, how can I help?"}

# Path 3: Runtime snapshot
curl -s http://localhost:3000/status | python3 -m json.tool
# Expected: channels array has 1 console channel, status = "running", uptime = some seconds
```

**Start with Telegram**:

First, get a Bot Token: open Telegram, search for `@BotFather`, send `/newbot`, follow the prompts, and you'll receive a token like `7xxxxxxxx:AAxxx...`. Then send a message to `@userinfobot` to get your user ID (a string of digits).

```bash
TELEGRAM_BOT_TOKEN=<your-token> \
TELEGRAM_ALLOW_FROM=<your-user-id> \
npm start
```

Open Telegram on your phone and send any message to your bot. Lena should reply within 2–3 seconds.

**Common errors and fixes:**

- `Error: 401 Unauthorized`: Bot token format is wrong or has expired; go back to @BotFather and `/newbot` or `/revoke`.
- `EADDRINUSE :::8765`: Port is occupied; run `lsof -i :8765` to find the process, kill it, then restart.
- Telegram message sent but no reply (no errors): Almost certainly `TELEGRAM_ALLOW_FROM` isn't set to your user ID. Try removing the variable first (defaults to `*`, allowing everyone) to verify it works, then add the whitelist.

**A known limitation worth stating explicitly**: this chapter's TelegramChannel creates a new AgentLoop `run()` call for each incoming message. This means if the same user sends two messages, the second won't remember the content of the first — because the AgentLoop's `messages` array isn't partitioned by user ID. This is an intentional simplification: multi-user session management (maintaining multiple independent conversation histories keyed by userId) is a capability added only after Ch 16's MessageBus. This chapter's lena-v0.15 assumes "only one user is using it at a time," which is perfectly adequate for single-user private use (you and your own Telegram bot).

**Process daemonization (optional)**: if you want Lena to keep running after closing the terminal, use `nohup` or `pm2`:

```bash
# Option 1: nohup (simple; logs written to nohup.out)
nohup npm start &

# Option 2: pm2 (recommended; has a process management interface)
npm install -g pm2
pm2 start "npm start" --name lena
pm2 logs lena          # watch live logs
pm2 stop lena          # stop
```

pm2 auto-restarts on process crash — a manual version of "launchd KeepAlive," suitable for local development and debugging. True production deployment (systemd / launchd daemon + log rotation + health monitoring) is Ch 22 material.

Lena v0.15 is now a genuine persistent process — as long as the terminal isn't closed, she's there and reachable at any time. Next chapter, we solve a new problem: when you have both Telegram and Discord channels simultaneously, and a Cron job needs to push messages to a specific channel, who makes the routing decision? The answer is MessageBus — a decoupling mechanism deeper inside than Gateway, 134 lines of code, fully severing "who sends messages" from "who receives messages."

---

## Beat 7 — Design Note

> **Why Not Compile Channels Into the Agent Core?**

The most obvious alternative: directly `import { TelegramBot }` and `import { DiscordClient }` in AgentLoop, dispatch messages with `if/switch`, and skip the channel abstraction layer. Code volume decreases by about 30%, directory structure is flatter, easier for newcomers to read linearly.

This approach's tradeoffs:

- **Hard to test**: testing AgentLoop requires mocking all channel dependencies (TelegramBot, DiscordClient...) even when you only want to test tool-call logic — a test granularity problem
- **Adding a channel = changing core**: adding a new platform channel requires touching the AgentLoop file; every change risks introducing regressions in other features
- **No runtime dynamic control**: once channels are compiled in, stopping a specific channel without restarting the process, switching accounts, or hot-reloading config requires complex state management logic in the core loop

The plugin approach's cost: adds a `BaseChannel` interface definition (~20 lines); each channel must implement 5 methods (`connect`, `disconnect`, `onMessage`, `send`, `snapshot`) — some boilerplate.

The core reason to choose plugins now: **delivery path changes at a much higher rate than intelligence logic**. Telegram API updates, Discord gateway protocol changes, adding new channel integrations — none of these should touch AgentLoop. Two things change for different reasons, so they shouldn't live in the same module.

If you're building something with a single fixed channel (e.g., pure HTTP API service) and no plans to switch, compiling it in is also reasonable — abstractions earn their keep the moment you need them. But once you have more than two channels, or expect to switch in the future, the maintenance cost advantage of the plugin pattern becomes immediately apparent.

In production systems (`src/channels/plugins/catalog.ts`), this design goes to its logical extreme: each channel is an independent npm package, declaring its `id/label/npmSpec` through the `openclaw.json` channel field; the gateway process scans installed packages at startup to dynamically discover channels, adding new channels without recompilation. This is "channel as plugin" evolving from principle to engineering reality. This chapter's lena-v0.15 is the minimum step on the path to getting there.

---

*Challenges*

1. Write a unit test for `ExponentialBackoff` that verifies the return value of the 10th call to `nextDelay()` does not exceed `maxMs` (hint: replace `Math.random` with a function that always returns `0` to make jitter zero, so the result is deterministic).

2. Add a `stopChannel(id: string)` method to `GatewayServer` so a specific channel can be hot-stopped at runtime without restarting the whole Gateway (hint: find the matching channel, call `disconnect()`, then remove it from `this.channels`).

3. Implement **Webhook mode** for the Telegram channel (replacing polling): when the environment variable `TELEGRAM_WEBHOOK_URL` is set, automatically switch to webhook mode, receiving Telegram's pushes via `POST /telegram-webhook` instead of active polling (hint: `bot.setWebHook(webhookUrl)` + handle that route in the Gateway HTTP service).

---

Lena can now work across interfaces. But what if multiple interfaces send messages simultaneously — or Lena needs to proactively broadcast to all interfaces? Next chapter's MessageBus solves this: pub/sub decoupling, so Lena doesn't need to know who's listening.
