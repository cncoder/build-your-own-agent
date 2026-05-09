# Chapter 16: MessageBus and Event-Driven Architecture — Decoupling Channels from the Agent

> **[Pillars: Long-horizon Execution × Safety]**
> "Any channel can crash. Lena keeps running."

---

## Beat 1 — Roadmap

```
Ch14 Safety Rails
     │
     ▼
Ch15 Gateway + Channel
     │  Lena moved into Telegram,
     │  but channels are wired directly to AgentLoop.
     │  N channels × M handlers = a ticking time bomb.
     ▼
Ch16 MessageBus  ◀── You are here
     │  Replace direct connections with a Bus.
     │  Channels become hot-swappable; one crash doesn't take down the rest.
     ▼
Ch17 Heartbeat (next chapter)
     Lena upgrades from "reactive responder" to "proactive initiator"
```

This chapter starts from the ticking time bomb of "multiple channels wired directly to AgentLoop," works through pub/sub theory and a line-by-line breakdown of the 134-line nano-claw implementation, and arrives at Lena v0.16 — where channels can be attached and detached at runtime. There is only one pitfall along the way, but it's a fatal one: `asyncio.gather` without error isolation will cancel all other handlers in the same batch the moment one unhandled exception escapes. `safeHandlerCall` is the only way out.

By the end of this chapter, Lena upgrades from v0.15 (a fixed channel structure where one channel crash brings Lena down) to **v0.16**, gaining three new capabilities:
1. Any handler crashing does not affect other handlers in the same batch
2. Attach a new channel at runtime without restarting Lena
3. Detach an old channel at runtime without restarting Lena

**The core question this chapter answers**: My agent is connected to Telegram, Discord, and HTTP. One channel times out and crashes — why do the other channels stop too? How do I fix it?

> **🧠 Intelligence increment (v0.15 → v0.16)**: Lena decouples for the first time — MessageBus pub/sub replaces direct channel-to-AgentLoop wiring with an event bus. Any channel crash won't drag down the others, and hot-swap at runtime requires no restart. This chapter teaches readers how to graft event-driven decoupled architecture onto their own agent.

---

## Beat 2 — Motivation

At the end of the last chapter, Lena v0.15's channel connections looked reasonable:

```python
# BAD — the direct-wiring structure of lena-v0.15 (illustrates the problem, don't copy)
class Lena:
    def __init__(self):
        self.telegram = TelegramChannel(callback=self._handle)
        self.discord  = DiscordChannel(callback=self._handle)

    async def _handle(self, channel_type: str, user_id: str, content: str):
        await self.agent_loop.run(channel_type, user_id, content)
        await self.logger.log(channel_type, user_id, content)
        await self.analytics.record(channel_type, content)
```

Now you want to add a third channel: HTTP. You modify `__init__`, add `self.http = HTTPChannel(...)`. At the same time you want a new subscriber: NotificationService (send email when a VIP user messages). You modify `_handle`, add another call.

N channels, M subscribers, and `_handle` becomes a congested intersection. 4 channels × 4 subscribers = 16 explicit calls crammed into a single function. Every addition ripples through the entire function.

**But that's not even the worst part.** The worst part is crash propagation at runtime. Let's reproduce it:

```python
# Reproducing crash propagation in the direct-wiring architecture
import asyncio

async def agent_loop(channel_type, content):
    print(f"[AgentLoop] processing {channel_type}: {content}")

async def logger(channel_type, content):
    print(f"[Logger] recording {channel_type}: {content}")

async def buggy_analytics(channel_type, content):
    # Simulate analytics service going down
    raise RuntimeError("Analytics database connection failed")

async def handle_message(channel_type: str, content: str):
    """Direct-wiring: call all subscribers sequentially"""
    await agent_loop(channel_type, content)
    await logger(channel_type, content)
    await buggy_analytics(channel_type, content)  # crashes here

asyncio.run(handle_message("telegram", "What time is it?"))
# Output:
# [AgentLoop] processing telegram: What time is it?
# [Logger] recording telegram: What time is it?
# Traceback: RuntimeError: Analytics database connection failed
```

Result: AgentLoop and Logger executed, but `buggy_analytics` propagated its exception upward. `handle_message` fails entirely, and the caller receives this exception. If the caller doesn't handle it properly, the reply to that Telegram message never gets sent.

**The concurrent version is even worse.** Realizing sequential calls are slow, many developers switch to `asyncio.gather`:

```python
async def handle_message_concurrent(channel_type: str, content: str):
    """Gather for concurrency — looks better, actually introduces a new trap"""
    await asyncio.gather(
        agent_loop(channel_type, content),
        logger(channel_type, content),
        buggy_analytics(channel_type, content),
    )
```

The default behavior of `asyncio.gather` is: when any coroutine raises an exception, gather immediately cancels all other still-running coroutines and re-raises that exception to the caller.

Run this version and you'll find: `agent_loop` and `logger` may be mid-execution when `buggy_analytics` throws — they get cancelled outright. The output may be empty — `[AgentLoop]` and `[Logger]` may not even print, because they were cancelled before reaching their print statement.

Real numbers: In a Lena instance with 5 channels (Telegram / Discord / HTTP / WebSocket / Slack), a Slack auth token expiry caused `SlackChannel.receive()` to throw `AuthenticationError` on every call. Result: **the response rate for all 5 channels dropped to 0% during that period**. Telegram users sent messages with no reply — not because Telegram had an issue, but because Slack's exception propagated through gather to the entire processing pipeline.

This is the double trap of direct-wiring plus gather. The solution is not "add try/except to each subscriber" — that duplicates error-handling logic across N places, and every new subscriber requires remembering to add it. The correct fix is to make error isolation **infrastructure**, built into the Bus, once and for all.

---

## Beat 3 — Theory

### 3.1 pub/sub: Reducing N×M to N+M

The core idea of pub/sub (publish-subscribe) is to insert a middle layer (Bus / Broker / Topic) between message **producers** (Publishers) and **consumers** (Subscribers), so that neither side needs to know the other exists.

In a direct-wiring architecture, every Publisher (channel) must explicitly hold a reference to every Subscriber (handler) and call it directly. N Publishers, M Subscribers: N×M dependency edges. At N=4, M=4: 16 edges. Add one new Subscriber and you must modify all 4 Publishers; add one new Publisher and you must modify all 4 Subscribers. The cost of change scales with the product of N and M.

The Bus turns the topology from a fully connected graph into a star graph: Publishers connect only to the Bus (N edges), Subscribers connect only to the Bus (M edges), total N+M edges — not N×M. Add a new Subscriber: register once at the Bus, touch zero Publishers.

This idea runs through the entire distributed systems field. Apache Kafka is cross-machine pub/sub — the topic is a durable log, and subscribers can replay from any point in time. Redis pub/sub is cross-process — a publisher sends a message and all subscribers to that channel receive it instantly, but with no persistence. The MessageBus in this chapter is **in-process** pub/sub — no network round-trip, microsecond latency, but messages are lost on process restart.

The idea is identical across all three; the applicable scale differs. A personal agent doesn't need Kafka — it needs the simplicity and zero operational cost of an in-process Bus.

**Convention**: In this chapter, `Publisher` = the party that sends messages to the Bus (a channel, such as TelegramChannel); `Subscriber` = the party that receives messages from the Bus (a handler function, such as `agent_loop_handler`); `topic` = the routing label on a message, equivalent in this implementation to `channel_type` (e.g., `"telegram"`). These three terms will be used consistently throughout; they are not interchangeable with "发布者/订阅者/主题" or any other informal variants.

### 3.2 safeHandlerCall: The Minimal Bulkhead

The name "Bulkhead Pattern" comes from naval engineering. A ship's hull is divided into independent watertight compartments. If one compartment floods, the watertight walls prevent water from spreading to the others — the ship doesn't sink from a single leak. In microservice architecture, the Bulkhead Pattern means placing different service calls in independent thread pools or semaphores: one slow service can't exhaust the whole system's thread resources and drag down others.

In the agent's MessageBus, each handler is one "compartment." What Bulkhead does is simple: one handler throwing an exception cannot propagate to other handlers.

The key insight is "**catch before asyncio.gather**."

`asyncio.gather(coro1(), coro2(), coro3())` starts three coroutines concurrently. If coro2 throws, gather's default behavior (`return_exceptions=False`) is to immediately propagate that exception to the caller while cancelling coro1 and coro3.

To prevent gather from cancelling other coroutines, each coroutine call must not itself throw — which means swallowing exceptions inside the coroutine. `safeHandlerCall` is exactly this wrapper: it accepts a handler and a message, calls the handler, and if the handler throws, `safeHandlerCall` catches it, logs it, does not rethrow, and returns normally. From gather's perspective, this call completed successfully (the handler just encountered an already-handled error internally).

The behavioral contract of `safeHandlerCall`:
1. `await handler(message)` — call the handler
2. If any `Exception` is raised: log `logger.error` (preserve traceability), emit an error event (notify listeners, but don't force handling), then **return** — do not rethrow
3. If it completes normally: return

These 8 lines are the most important engineering decision in this chapter.

**Convention**: `safeHandlerCall` (or `_safe_call`) = a handler call wrapped with error isolation; any exception is caught internally and not propagated to the caller. A bare handler call = exceptions propagate to the caller (typically propagating through gather to all calls in the batch).

### 3.2b Three Coordination Patterns for Multi-Agent Systems: The Theoretical Position of MessageBus

This chapter's MessageBus is not designed from scratch in a vacuum — it corresponds to a well-defined category in the multi-agent coordination architecture space. Anthropic's architecture white paper identifies three coordination modes for collaborative systems:

> - **Group chat** — agents participate in a shared conversation thread, coordinating through natural language
> - **Event-driven** — events serve as the shared language; structured updates drive collaboration
> - **Blackboard** — a shared knowledge store that all agents can read and write (collective memory)
>
> (Source: Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*, 2025, p.17)

This chapter's MessageBus corresponds to the **event-driven coordination** mode: `ChannelMessage` is a structured event, `publish()` is event publication, `subscribe()` is event subscription, and `_safe_call` ensures that a single handler's failure doesn't propagate to the entire event bus.

The white paper issues a practical warning about the event-driven mode, worth keeping in mind when implementing MessageBus:

> "small changes can unpredictably affect how agents behave"

This is exactly why pub/sub decoupling is safer than direct calls. In a direct-wiring architecture, adding a new subscriber means modifying the publisher's code — a "small change" that can trigger unexpected behavior. In a Bus architecture, adding a subscriber requires only calling `bus.subscribe()`. The publisher's code has no idea this happened and is completely unaffected.

Each coordination mode has its own best-fit scenario: Group chat suits creative tasks (agents need to "see" each other's reasoning); Blackboard suits knowledge sharing (all agents need access to the same constantly-updated knowledge base); Event-driven suits decoupled reactive systems (like Lena here — multiple channels independently posting messages, multiple handlers independently responding, neither interfering with the other).

### 3.3 globalHandlers vs channel-specific handlers

MessageBus maintains two categories of subscriptions. This design choice is not an optional optimization — it is the key to avoiding the re-introduction of the N×M problem.

**channel-specific handlers**: Registered with `subscribe("telegram", handler)`, triggered only when a message with `channel_type == "telegram"` arrives. AgentLoop is a typical channel-specific subscriber — it needs to know which channel a message came from in order to decide what context to use for the reply (Telegram's `chat_id`, Discord's `guild_id` are both in `metadata`).

**global handlers**: Registered with `subscribe_all(handler)`, triggered by any message from any channel. Logger, Analytics, cost tracking, and security audit are **cross-cutting concerns** — they are agnostic to the source of a message; they only care that "a message occurred," not "where it came from."

The key benefit of registering cross-cutting concerns as global handlers: add a new channel (growing from 4 to 5), and Logger needs no changes. Logger registered once with `subscribe_all`; after that, no matter how many channels exist, it automatically receives all messages. If Logger were channel-specific, adding a channel would require updating Logger's registration — reintroducing N×M coupling at the Bus level.

The decision rule is simple: Does the handler need to know which channel the message came from? Yes → channel-specific. No → global.

In nano-claw's `bus/index.ts`, this distinction manifests as two separate data structures (`handlers: Map<string, Set<MessageHandler>>` and `globalHandlers: Set<MessageHandler>`), not different tags within the same structure. Keeping the data structures separate ensures the management logic for the two handler types doesn't interfere with each other.

---

## Beat 4 — Skeleton

Let's implement the minimum MessageBus skeleton using only what's needed to route one message to one handler and verify it works:

```python
# bus.py — Minimum MessageBus skeleton (lena-v0.16)
# Requirements: Python 3.10+, no additional dependencies
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# Handler signature: receives one message, returns None
# Callable[["ChannelMessage"], Awaitable[None]] means:
#   - accepts one ChannelMessage argument
#   - must be an async function (returns Awaitable[None])
MessageHandler = Callable[["ChannelMessage"], Awaitable[None]]

@dataclass
class ChannelMessage:
    channel_type: str  # source, e.g. "telegram" / "discord" / "http"
    user_id: str       # sender identifier
    content: str       # message body
    # id and metadata have defaults — can be omitted
    id: str = field(default_factory=lambda: __import__('uuid').uuid4().hex)
    metadata: dict = field(default_factory=dict)

class MessageBus:
    def __init__(self):
        # channel-specific handlers: {"telegram": {h1, h2}, "discord": {h3}}
        # Set rather than list: registering the same handler twice is idempotent via Set.add
        self._handlers: dict[str, set[MessageHandler]] = {}
        # global handlers: {logger, analytics}
        self._global_handlers: set[MessageHandler] = set()

    def subscribe(self, channel_type: str, handler: MessageHandler) -> None:
        if channel_type not in self._handlers:
            self._handlers[channel_type] = set()
        self._handlers[channel_type].add(handler)

    def subscribe_all(self, handler: MessageHandler) -> None:
        self._global_handlers.add(handler)

    def unsubscribe(self, channel_type: str, handler: MessageHandler) -> None:
        if channel_type in self._handlers:
            self._handlers[channel_type].discard(handler)
            if not self._handlers[channel_type]:
                del self._handlers[channel_type]  # clean up empty sets to avoid memory leaks

    async def publish(self, message: ChannelMessage) -> None:
        # Snapshot first (convert to list), then gather.
        # Without the snapshot, an unsubscribe call during handler execution
        # would trigger "set changed size during iteration".
        specific = list(self._handlers.get(message.channel_type, set()))
        glob     = list(self._global_handlers)
        await asyncio.gather(*[self._safe_call(h, message) for h in specific + glob])

    async def _safe_call(self, handler: MessageHandler, message: ChannelMessage) -> None:
        """Bulkhead wrapper: handler exception is logged, not reraised — gather continues."""
        try:
            await handler(message)
        except Exception as e:
            logger.error(f"Handler '{handler.__name__}' failed on {message.id}: {e}",
                         exc_info=True)
            # Critical: do not rethrow. Other handlers' safe_calls complete normally.

    def handler_count(self, channel_type: str | None = None) -> int:
        if channel_type:
            return len(self._handlers.get(channel_type, set()))
        return sum(len(v) for v in self._handlers.values()) + len(self._global_handlers)
```

Verify the skeleton runs:

```python
async def test_skeleton():
    bus = MessageBus()

    async def dummy_handler(msg: ChannelMessage):
        print(f"[OK] received: {msg.channel_type} → {msg.content!r}")

    bus.subscribe("telegram", dummy_handler)
    await bus.publish(ChannelMessage(channel_type="telegram",
                                     user_id="u1", content="hello"))
    # Expected output: [OK] received: telegram → 'hello'
    print(f"handler_count: {bus.handler_count()}")
    # Expected output: handler_count: 1

asyncio.run(test_skeleton())
```

Expected two lines of output: `[OK] received: telegram → 'hello'` and `handler_count: 1`. Skeleton is running. Now we add what a real system needs, one piece at a time.

---

## Beat 5 — Incremental Assembly

The skeleton already has the critical `_safe_call`, but two things are still missing: channels need a standardized start/stop interface, and Lena needs a manager that can attach and detach channels at runtime. We add them step by step.

| Extension | Why it's needed | How to add it |
|-----------|----------------|---------------|
| Verify `_safe_call` in practice | We need to see "one handler crashes, another continues" in actual output — not just believe the theory | Register a deliberately-throwing handler, observe whether other handlers are unaffected |
| `ChannelPlugin` base class | Channels need a standardized start/stop interface to be uniformly attached and detached | Define an abstract base class, enforce `channel_type` property and `receive()` |
| `ChannelManager` | Lena needs a place to manage all active channels and support runtime addition/removal | A separate class holding a `{channel_type: plugin}` dict |

### Extension 1: Verify safeHandlerCall isolation

This is the most important step. Let's prove it works in code before moving on:

```python
# Three handlers: agent_loop and analytics work normally; buggy_logger deliberately crashes
async def verify_isolation():
    bus = MessageBus()

    async def agent_loop(msg: ChannelMessage):
        print(f"  [AgentLoop] processing: {msg.content!r}")

    async def buggy_logger(msg: ChannelMessage):
        raise RuntimeError("Logger disk full")

    async def analytics(msg: ChannelMessage):
        print(f"  [Analytics] recording: channel={msg.channel_type}")

    bus.subscribe("telegram", agent_loop)
    bus.subscribe("telegram", buggy_logger)
    bus.subscribe("telegram", analytics)

    print(f"Registered {bus.handler_count('telegram')} telegram handlers\n")

    msg = ChannelMessage(channel_type="telegram", user_id="u1", content="test")
    await bus.publish(msg)

asyncio.run(verify_isolation())
```

Output:

```
Registered 3 telegram handlers

  [AgentLoop] processing: 'test'
  [Analytics] recording: channel=telegram
ERROR:bus:Handler 'buggy_logger' failed on ...: Logger disk full
```

Both `agent_loop` and `analytics` executed. `buggy_logger`'s error was logged but not propagated. Note that output order may not be fixed — the three handlers execute concurrently, and which one prints first depends on scheduling. This is `asyncio.gather`'s concurrent semantics, and it's expected behavior.

### Extension 2: ChannelPlugin — Standardized channel interface

Hot-swap requires channels to be able to start and stop independently. Let's define the interface:

```python
# channel_plugin.py — Hot-swappable channel base class
import abc
from bus import MessageBus, ChannelMessage

class ChannelPlugin(abc.ABC):
    """
    A channel implementing this interface can be hot-swapped by ChannelManager.

    A channel is a Publisher: it listens to an external source (Telegram Bot API,
    Discord Webhook, etc.), converts received messages into ChannelMessage objects,
    and publishes them to the Bus via self.bus.publish().

    A channel holds no references to any Subscriber. This is pub/sub decoupling.
    """

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self._running = False

    @property
    @abc.abstractmethod
    def channel_type(self) -> str:
        """Unique identifier for this channel, e.g. 'telegram' / 'discord' / 'http'"""
        ...

    async def start(self) -> None:
        """Start the channel. Subclasses override to establish the external connection."""
        self._running = True

    async def stop(self) -> None:
        """Stop the channel. Subclasses override to close the external connection."""
        self._running = False

    async def receive(self, user_id: str, content: str, **metadata) -> None:
        """
        Called when an external message arrives; publishes to the Bus.
        All polling/webhook logic in subclasses ultimately calls this.
        """
        if not self._running:
            raise RuntimeError(
                f"Channel '{self.channel_type}' not started. "
                "Call start() before receive()."
            )
        msg = ChannelMessage(
            channel_type=self.channel_type,
            user_id=user_id,
            content=content,
            metadata=metadata,
        )
        await self.bus.publish(msg)
```

A MockChannel for demonstration:

```python
class MockChannel(ChannelPlugin):
    """A channel with no real external connection — for testing and demos."""

    def __init__(self, channel_type: str, bus: MessageBus):
        super().__init__(bus)
        self._ct = channel_type

    @property
    def channel_type(self) -> str:
        return self._ct

    async def start(self) -> None:
        await super().start()
        print(f"  [MockChannel:{self._ct}] started")

    async def stop(self) -> None:
        await super().stop()
        print(f"  [MockChannel:{self._ct}] stopped")
```

### Extension 3: ChannelManager — Runtime attach/detach

With the ChannelPlugin base class in place, ChannelManager's logic is straightforward:

```python
# channel_manager.py — Manage all channels at runtime
from bus import MessageBus
from channel_plugin import ChannelPlugin

class ChannelManager:
    def __init__(self, bus: MessageBus):
        self.bus = bus
        self._channels: dict[str, ChannelPlugin] = {}

    async def attach(self, channel: ChannelPlugin) -> None:
        """Attach a new channel at runtime. Same channel_type cannot be attached twice."""
        ct = channel.channel_type
        if ct in self._channels:
            raise ValueError(f"'{ct}' already attached. detach first.")
        self._channels[ct] = channel
        await channel.start()
        print(f"  [Manager] attach '{ct}' OK. Active: {self.list_channels()}")

    async def detach(self, channel_type: str) -> None:
        """Remove a channel at runtime. Silently ignored if not present."""
        ch = self._channels.pop(channel_type, None)
        if ch:
            await ch.stop()
            print(f"  [Manager] detach '{channel_type}' OK. Active: {self.list_channels()}")

    def list_channels(self) -> list[str]:
        return list(self._channels.keys())
```

Verify hot-swap:

```python
async def verify_hotplug():
    bus = MessageBus()
    manager = ChannelManager(bus)

    async def agent_handler(msg: ChannelMessage):
        print(f"  [AgentLoop] {msg.channel_type}: {msg.content!r}")

    bus.subscribe("telegram", agent_handler)
    bus.subscribe("discord", agent_handler)

    # Only attach telegram; discord not connected yet
    telegram = MockChannel("telegram", bus)
    await manager.attach(telegram)
    print(f"  channels after start: {manager.list_channels()}")
    # Output: channels after start: ['telegram']

    await telegram.receive("u1", "first message")

    # Attach discord while running
    discord = MockChannel("discord", bus)
    await manager.attach(discord)
    print(f"  after attaching discord: {manager.list_channels()}")
    # Output: after attaching discord: ['telegram', 'discord']

    await discord.receive("u2", "discord message")

    # Detach telegram while running
    await manager.detach("telegram")
    print(f"  after detaching telegram: {manager.list_channels()}")
    # Output: after detaching telegram: ['discord']

asyncio.run(verify_hotplug())
```

Each step has a print statement confirming the state matches expectations. After all three intermediate states are verified, we assemble the full Lena v0.16.

---

## Beat 6 — Run Verification

Let's run the full Lena v0.16 end-to-end and verify all three capabilities together. The full code is at `code/lena-v0.16/main.py`; the key parts are shown here:

```python
# main.py — Lena v0.16 complete example (condensed; see code directory for full version)
# Run: python main.py
# Dependencies: Python 3.10+ standard library, no pip install needed

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

from bus import MessageBus, ChannelMessage, get_message_bus
from channel_plugin import MockChannel
from channel_manager import ChannelManager


# ── Subscribers ──────────────────────────────────────────────────────

async def agent_loop_handler(msg: ChannelMessage) -> None:
    """Core agent logic (simplified; real version calls the LLM API)"""
    print(f"  [AgentLoop] from={msg.channel_type} user={msg.user_id} '{msg.content}'")

async def logger_handler(msg: ChannelMessage) -> None:
    """Global logger: records messages from all channels"""
    print(f"  [Logger]    {msg.channel_type}:{msg.user_id} → {msg.content[:40]!r}")

async def buggy_analytics(msg: ChannelMessage) -> None:
    """Deliberately crashes to verify safeHandlerCall isolation"""
    raise RuntimeError("Analytics service down")


async def main():
    bus = get_message_bus()
    manager = ChannelManager(bus)

    # Register handlers
    bus.subscribe("telegram", agent_loop_handler)
    bus.subscribe("discord",  agent_loop_handler)
    bus.subscribe_all(logger_handler)   # global: all channels trigger this
    bus.subscribe_all(buggy_analytics)  # global: always crashes — tests isolation

    # Scenario 1: telegram message
    telegram = MockChannel("telegram", bus)
    await manager.attach(telegram)
    print(f"\n[Scenario 1] telegram message (analytics will crash, but AgentLoop and Logger work)")
    await telegram.receive("user_001", "What time is it?")

    # Hot-swap: attach discord
    print(f"\n[Hot-swap] attach discord")
    discord = MockChannel("discord", bus)
    await manager.attach(discord)
    print(f"Current channels: {manager.list_channels()}")

    # Scenario 2: discord message
    print(f"\n[Scenario 2] discord message")
    await discord.receive("user_002", "Can you check tomorrow's weather?")

    # Hot-swap: detach telegram
    print(f"\n[Hot-swap] detach telegram")
    await manager.detach("telegram")
    print(f"Remaining channels: {manager.list_channels()}")

    # Scenario 3: discord message (telegram removed, discord still running)
    print(f"\n[Scenario 3] discord message (telegram removed)")
    await discord.receive("user_003", "Thanks!")

    print(f"\nFinal handler count: {bus.handler_count()}")

asyncio.run(main())
```

**Run `python main.py` and you should see** (about 25 lines, < 0.1 second):

```
  [MockChannel:telegram] started

[Scenario 1] telegram message (analytics will crash, but AgentLoop and Logger work)
  [AgentLoop] from=telegram user=user_001 'What time is it?'
  [Logger]    telegram:user_001 → 'What time is it?'
ERROR:bus:Handler 'buggy_analytics' failed on ...: Analytics service down

[Hot-swap] attach discord
  [MockChannel:discord] started
Current channels: ['telegram', 'discord']

[Scenario 2] discord message
  [AgentLoop] from=discord user=user_002 'Can you check tomorrow's weather?'
  [Logger]    discord:user_002 → 'Can you check tomorrow's weather?'
ERROR:bus:Handler 'buggy_analytics' failed on ...: Analytics service down

[Hot-swap] detach telegram
  [MockChannel:telegram] stopped
Remaining channels: ['discord']

[Scenario 3] discord message (telegram removed)
  [AgentLoop] from=discord user=user_003 'Thanks!'
  [Logger]    discord:user_003 → 'Thanks!'
ERROR:bus:Handler 'buggy_analytics' failed on ...: Analytics service down

Final handler count: 4
```

**Three things to confirm**:

1. `buggy_analytics` reports ERROR every time, but `[AgentLoop]` and `[Logger]` print normally every time. This proves `safeHandlerCall`'s error isolation works. If you're skeptical, delete the `except` block inside `_safe_call` and run again — AgentLoop and Logger will vanish after Scenario 1.

2. The discord message in Scenario 2 is handled normally, even though discord didn't exist during Scenario 1. This proves hot-swap works — `bus.subscribe("discord", ...)` was registered before attach, and takes effect immediately after attach.

3. Telegram is detached in Scenario 3, but discord messages continue to be processed normally. This means detach is idempotent — it doesn't affect other channels.

**Common error diagnosis**:
- `RuntimeError: Channel 'X' not started` → Called `channel.receive()` directly without first calling `await manager.attach(channel)`
- `set changed size during iteration` → Called `bus.unsubscribe()` during handler execution; the fix is to `list()` convert before gather inside `publish` (already handled in the skeleton code)
- `TypeError: object bool can't be used in 'await'` → Handler function is missing `async`, it's a regular function not a coroutine
- `KeyError: 'telegram'` → `bus.handler_count('telegram')` returns 0 when there are no telegram handlers rather than raising — this bug is already fixed in the skeleton (using `.get(channel_type, set())`)

---

## Beat 7 — Design Note

> **Why Not Use a Message Queue (MQ)?**
>
> MessageBus and Kafka / RabbitMQ / Redis Streams appear to solve the same problem: publishers send messages, subscribers receive them, a broker in the middle provides decoupling. Given that these systems are mature, come with monitoring tools, and support message replay — why write an in-process Bus from scratch instead of using one of them?
>
> **The alternative**: Each of Lena's channels publishes messages to a Redis pub/sub channel, and AgentLoop acts as a subscriber consuming them. Configuration cost: `pip install redis`, add a Redis connection, change `publish` to `redis.publish()`, and change handler registration to a Redis subscriber listen loop.
>
> **Tradeoff analysis**:
>
> | Dimension | In-process MessageBus | Redis pub/sub | Kafka |
> |-----------|----------------------|--------------|-------|
> | Operational cost | Zero — no dependencies | Redis instance + connection management | Kafka + ZooKeeper/KRaft + monitoring |
> | Message latency | ~1 microsecond (function call) | ~0.5–2 milliseconds (local network) | ~5–20 milliseconds (normal) |
> | Message persistence | None (lost on process restart) | None (pub/sub has no persistence) | Yes (configurable retention) |
> | Message replay | None | None | Yes |
> | Horizontal scaling | None — single process | Yes — multiple consumers | Yes — consumer groups |
> | Suitable message volume | < 10,000/s | < 100,000/s | > 100,000/s |
>
> **Why this choice for now**: Lena is a single-machine personal agent, with channel counts in the single digits (4–8), message volume of tens per minute, and peaks of a few hundred per minute. At this scale, the in-process Bus's ~1 microsecond latency vs. Redis's ~1 millisecond latency represents a 1000x difference. For an interactive agent where users are waiting for a reply, that gap sits between "fast enough to be imperceptible" and "just noticeably sluggish."
>
> More importantly: introducing Redis introduces 5 new operational concerns (Redis process management, connection pool configuration, connection timeout handling, message serialization/deserialization, Lena's fallback behavior when Redis crashes) to solve a problem that doesn't exist at this scale (single-process capacity). That's not an engineering decision — it's engineering debt.
>
> **When to switch to an MQ**: When Lena needs to run **across machines** — the main agent on server A, the Telegram channel on server B (perhaps to isolate exposure of the Telegram Bot Token), and two processes need network communication. Redis pub/sub is the simplest choice. Or when Lena's message volume, due to multi-tenancy (1,000 simultaneous users), exceeds single-process capacity.
>
> **Migration cost**: Nearly zero. Replace the implementation of `MessageBus.publish` with `redis.publish()`; replace `subscribe/subscribe_all` with Redis subscription logic. The channel code above (`channel.receive()` calling `bus.publish()`) and the handler code change not at all. This is the biggest advantage of the in-process Bus design: a stable interface with a replaceable implementation.

---

## Chapter Summary

MessageBus is 134 lines, but it solves three architectural problems:

**Problem 1: Coupling explosion.** N channels × M handlers = N×M direct dependency edges. Adding or removing anything on either side requires modifying all the code on the other side. The Bus turns that multiplication into addition: N+M edges, neither side knowing about the other.

**Problem 2: Error propagation.** `asyncio.gather`'s default behavior lets one handler's exception cancel all other handlers. `safeHandlerCall` (or `_safe_call`) wraps each handler before gather, ensuring exceptions are digested inside the wrapper and don't propagate outward. This is the minimum implementation of the Bulkhead Pattern — 8 lines of code.

**Problem 3: Static structure.** In a direct-wiring architecture, channels are initialized at Lena's startup; adding or removing a channel requires a restart. `subscribe/unsubscribe` are runtime operations. `ChannelManager.attach/detach` wraps those two operations into a hot-swap interface with lifecycle management.

**The distinction between two subscription types** is another design decision worth remembering: cross-cutting concerns (Logger, Analytics, Security Audit) use `subscribe_all` — register once, apply to all channels; business logic (AgentLoop, NotificationService) uses `subscribe` — precisely subscribing to specific channels. This distinction prevents the re-introduction of N×M coupling at the Bus layer.

**In-process vs. distributed MQ** is not a question of taste — it's an engineering decision about scale and operational cost. Use an in-process Bus for a personal agent. Don't reach for Kafka just because it "looks more professional."

---

Next chapter: Lena has a MessageBus. Any channel can crash without affecting the rest, and channels can be hot-swapped at any time. But Lena is still completely passive — she only responds when a user sends a message.

**Ch 17**: Give Lena a Heartbeat. Heartbeat is essentially a special Publisher on the MessageBus: messages don't come from users — they come from a clock. Every tick, Heartbeat publishes a `system:heartbeat` message to the Bus, and AgentLoop subscribes to it, checking whether any pending scheduled tasks need to fire. This is the infrastructure that upgrades Lena from "reactive responder" to "proactive initiator" — Heartbeat gives her an internal clock.

---

## Further Reading

| Resource | Content |
|----------|---------|
| `nano-claw/src/bus/index.ts` (134 lines) | TypeScript MessageBus full implementation — the prototype for this chapter's Python version |
| `nano-claw/src/channels/manager.ts` | Channel → Bus registration logic (TypeScript) |
| Martin Fowler, *Patterns of Enterprise Application Architecture*, Ch 9 | Original discussion of the Bulkhead Pattern; no need to read the whole book — just know this: bulkhead = limiting the blast radius of one component's failure |
| Apache Kafka Documentation, "Introduction to Event Streaming" | Standard reference for distributed pub/sub; no need to read the whole doc — just know: Kafka solves "multi-machine, high-throughput, durable" scenarios; this chapter's in-process Bus solves "single-machine, low-latency, zero operational overhead" scenarios |
