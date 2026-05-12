# 第 16 章：MessageBus 与事件驱动——解耦 Channel 与 Agent

> **[支柱：Long-horizon 执行 × Safety]**
> "任何 channel 崩溃，Lena 照样跑。"

---

## Beat 1 — 路线图

```
Ch14 安全护栏
     │
     ▼
Ch15 Gateway + Channel
     │  Lena 住进了 Telegram，
     │  但 channel 直连 AgentLoop，N 个 channel × M 个 handler = 定时炸弹
     ▼
Ch16 MessageBus  ◀── 你在这里
     │  把直连线换成 Bus，
     │  channel 热插拔，一个崩了不影响其他
     ▼
Ch17 Heartbeat（下章）
     Lena 从"被动响应"升级为"主动出击"
```

本章从"多 channel 直连 AgentLoop"这个定时炸弹出发，经过 pub/sub 理论、134 行 nano-claw（本书配套的极简 agent runtime 参考实现，TypeScript 版）实现拆解，最终到达"channel 可运行时 attach/detach"的 Lena v0.16。途中踩的坑只有一个，但很致命：`asyncio.gather` 在没有错误隔离时，一个 handler 的未捕获异常会传播到调用方，整批消息处理失败——`safeHandlerCall` 是唯一的出路。

本章结束后，Lena 从 v0.15（固定 channel 结构，channel 崩了 Lena 崩）升级到 **v0.16**，新增三项能力：
1. 任意 handler 崩溃不影响同批其他 handler
2. 运行时动态 attach 新 channel，不重启 Lena
3. 运行时动态 detach 旧 channel，不重启 Lena

**本章回答的核心问题**：我的 agent 连了 Telegram + Discord + HTTP，一个 channel 超时崩溃，其他 channel 为什么也停了？怎么修？

---

## Beat 2 — 动机

上一章结束时，Lena v0.15 的 channel 连接看起来很合理：

```python
# BAD — lena-v0.15 的直连结构（展示问题，不要照写）
class Lena:
    def __init__(self):
        self.telegram = TelegramChannel(callback=self._handle)
        self.discord  = DiscordChannel(callback=self._handle)

    async def _handle(self, channel_type: str, user_id: str, content: str):
        await self.agent_loop.run(channel_type, user_id, content)
        await self.logger.log(channel_type, user_id, content)
        await self.analytics.record(channel_type, content)
```

现在你想加第三个 channel：HTTP。你要改 `__init__`，加一行 `self.http = HTTPChannel(...)`。同时想加一个新的 subscriber：NotificationService（VIP 用户消息时发邮件）。你要改 `_handle`，加一行调用。

N 个 channel，M 个 subscriber，`_handle` 方法变成了一个拥挤的交叉路口。4 个 channel × 4 个 subscriber = 16 次显式调用全部挤在一个函数里。每加一项，改动扩散到整个函数。

**但这还不是最坏的情况。** 最坏的情况是运行时的崩溃传播。让我们复现它：

```python
# 复现直连架构的崩溃传播
import asyncio

async def agent_loop(channel_type, content):
    print(f"[AgentLoop] 处理 {channel_type}: {content}")

async def logger(channel_type, content):
    print(f"[Logger] 记录 {channel_type}: {content}")

async def buggy_analytics(channel_type, content):
    # 模拟 analytics 服务宕机
    raise RuntimeError("Analytics 数据库连接失败")

async def handle_message(channel_type: str, content: str):
    """直连架构：串行调用所有 subscriber"""
    await agent_loop(channel_type, content)
    await logger(channel_type, content)
    await buggy_analytics(channel_type, content)  # 这里崩了

asyncio.run(handle_message("telegram", "现在几点？"))
# 输出：
# [AgentLoop] 处理 telegram: 现在几点？
# [Logger] 记录 telegram: 现在几点？
# Traceback: RuntimeError: Analytics 数据库连接失败
```

结果：AgentLoop 和 Logger 确实执行了，但 `buggy_analytics` 的异常向上传播，`handle_message` 整体失败，调用方捕获到了这个异常。如果调用方没有妥善处理，这条消息的 Telegram 回复就没有发出去。

**更糟糕的并发版本**。很多人意识到串行调用慢，改成 `asyncio.gather`：

```python
async def handle_message_concurrent(channel_type: str, content: str):
    """用 gather 并发，看起来更好——其实引入了新坑"""
    await asyncio.gather(
        agent_loop(channel_type, content),
        logger(channel_type, content),
        buggy_analytics(channel_type, content),
    )
```

`asyncio.gather` 的默认行为（`return_exceptions=False`）是：任意一个 coroutine 抛出异常，gather 把该异常立即重新抛给调用方。其他 coroutine 继续在事件循环中运行直到完成，调用方不再等待它们的结果。

实际效果：调用方收到异常后，如果没有 `try/except`，这一次的消息处理整体失败，Telegram 的回复没有发出。在一个消息处理循环里，下一条消息到来时还会遇到同样的问题——只要 `buggy_analytics` 的根因没解除，每条消息都失败。

实测数字：在一个有 5 个 channel（Telegram / Discord / HTTP / WebSocket / Slack）的 Lena 实例中，Slack 鉴权 token 过期导致 `SlackChannel.receive()` 每次调用都抛 `AuthenticationError`。结果：**所有 5 个 channel 的所有消息在那个时段的响应率都降到了 0%**。Telegram 用户发消息没有回复，不是 Telegram 有问题，是 Slack 的异常通过 gather 传播到了整个处理管道。

这是直连架构加 gather 的双重陷阱。解决方案不是"给每个 subscriber 加 try/except"——那会在 N 个地方重复维护错误处理逻辑，而且每加一个新 subscriber 都要记得加。正确的解法是把错误隔离做成**基础设施**，放在 Bus 里，一劳永逸。

---

## Beat 3 — 理论铺垫

### 3.1 pub/sub：把 N×M 降到 N+M

pub/sub（publish-subscribe）模式的核心思想是：在消息的**生产者**（Publisher）和**消费者**（Subscriber）之间插入一个中间层（Bus / Broker / Topic），让两者互不知晓对方的存在。

直连架构里，每个 Publisher（channel）必须显式持有每个 Subscriber（handler）的引用并直接调用。N 个 Publisher，M 个 Subscriber，就有 N×M 条依赖边。N=4，M=4 时：16 条边。加一个新 Subscriber，要改 4 个 Publisher；加一个新 Publisher，要改 4 个 Subscriber。系统的改动成本随 N 和 M 的乘积增长。

Bus 把拓扑从全连接图变成星形图：Publisher 只连向 Bus（N 条边），Subscriber 只连向 Bus（M 条边），总计 N+M 条边，不是 N×M。加一个新 Subscriber，只需要在 Bus 上注册一次，不改任何 Publisher。

这个思想贯穿了整个分布式系统领域。Apache Kafka 是跨机器的 pub/sub——topic 是持久化的日志，subscriber 可以从任意时间点回放消息。Redis pub/sub 是跨进程的——publisher 发一条消息，所有订阅了该 channel 的进程立刻收到，但不持久化。本章实现的 MessageBus 是**进程内**的 pub/sub——没有网络 round-trip，延迟是微秒级，但进程重启消息丢失。

三者的思想完全一样，适用规模不同。个人 agent 不需要 Kafka，需要的是进程内 Bus 的简洁性和零运维成本。

**Convention**：本章中，`Publisher` = 往 Bus 发消息的一方（channel，如 TelegramChannel）；`Subscriber` = 从 Bus 接收消息的一方（handler 函数，如 `agent_loop_handler`）；`topic` = 消息的路由标签，在本实现中等同于 `channel_type`（如 `"telegram"`）。后文统一用这三个术语，不与"发布者/订阅者/主题"混用。

### 3.2 safeHandlerCall：隔仓设计的最小实现

**Convention**：**Bulkhead Pattern**（隔仓设计）= 把不同的调用单元隔离，一个单元的故障不能传播到其他单元；名字来自造船工程的水密舱（一仓进水不沉船）；在微服务里表现为独立线程池/信号量；在 agent MessageBus 里，每个 handler 是一个"仓"，`_safe_call` 是隔离层。

关键设计决策：一个 handler 抛出异常，不能传播给其他 handler，也不能让整批消息失败。

关键点是"**在 asyncio.gather 之前捕获**"。

`asyncio.gather(coro1(), coro2(), coro3())` 同时启动三个 coroutine。如果 coro2 抛出异常，gather 的默认行为（`return_exceptions=False`）是：立即把该异常重新抛给调用方，coro1 和 coro3 继续在事件循环中运行直到完成——但调用方已经收到异常，不再等待它们的结果。整个这一批消息的处理逻辑失败，该消息的回复没有发出。

要让 gather 始终正常返回，必须让每个 coroutine 调用本身不抛出异常——换句话说，把异常在 coroutine 内部吞掉。`safeHandlerCall` 就是这个包裹层：它接受一个 handler 和一条消息，调用 handler，如果 handler 抛异常，`safeHandlerCall` 捕获它、记录日志、不 rethrow，然后正常返回 None。从 gather 的视角看，这次调用成功完成了（只是 handler 内部遇到了一个已被处理的错误）。其余所有 handler 的 safeHandlerCall 也正常完成，整批处理不中断。

`safeHandlerCall` 的行为规范：
1. `await handler(message)` — 调用 handler
2. 如果抛出任何 `Exception`：记录 `logger.error`（包含 handler 名字、message id、异常信息和 traceback，保留问题可追溯性），然后 **return**，不 rethrow
3. 如果正常完成：直接 return

这几行代码是本章最重要的工程决策。

**Convention**：`safeHandlerCall`（或 `_safe_call`）= 带错误隔离包裹的 handler 调用，任何异常在内部被捕获，不传播给调用方；裸 handler 调用 = 异常会传播给调用方（通常通过 gather 传播给整批调用）。

### 3.2b 多 Agent 协调的三种模式：MessageBus 的理论坐标

safeHandlerCall 解决了崩溃传播，pub/sub 解决了 N×M 耦合——但这两个工具合在一起，在架构分类上属于哪一种模式？把本章的设计放到多 agent 协调框架的全局坐标里定位，有助于理解它在什么场景下是正确选择，在什么场景下不够用。

**Convention**：**event-driven coordination**（事件驱动协调）= 多 agent 或多组件系统中，以结构化事件（而非自然语言对话或共享变量读写）作为协作语言的协调模式。组件之间不直接调用，而是通过发布/订阅事件来传递状态变化。

本章的 MessageBus 在多 agent 系统的协调模式谱系里属于 event-driven coordination：组件之间不互相持有引用，通过发布/订阅结构化事件（`ChannelMessage`）来协作，`_safe_call` 保证单个 handler 的故障不传播给整个总线。

这与 Anthropic 在 *Building effective agents*（2024-12-19）中讨论多 agent 并行化架构时给出的工程警告高度对应：

> "small changes can unpredictably affect how agents behave"

这正是 pub/sub 解耦比直连架构安全的原因。在直连架构里，加一个新的 subscriber 意味着修改 publisher 的代码——这是一次"小改动"，却可能触发意外的行为变化。在 Bus 架构里，加一个 subscriber 只需要调用 `bus.subscribe()`，publisher 的代码完全不知道这件事发生了，也不受影响。

Event-driven 协调模式的典型对比场景：如果 agent 之间需要"相互看见彼此的推理过程"（如多个 LLM agents 讨论同一个问题），共享对话线程或共享知识仓更合适；如果 agent/组件之间需要解耦的响应式协作（如本章的 Lena——多个 channel 独立发消息，多个 handler 独立响应，互不干扰），event-driven 是正确选择。

确定了"这是 event-driven 架构"之后，有一个实现细节需要决策：不是所有的 subscriber 都关心"消息从哪个 channel 来"。这个区别，决定了 MessageBus 需要维护两类不同的订阅。

### 3.3 globalHandlers vs channel-specific handlers

MessageBus 维护两类订阅，这个设计选择不是可选的优化，而是避免重新引入 N×M 问题的关键。

**channel-specific handlers**：用 `subscribe("telegram", handler)` 注册，只在 `channel_type == "telegram"` 的消息到来时触发。AgentLoop 是典型的 channel-specific subscriber——它需要知道消息来自哪个 channel，来决定用什么上下文回复（Telegram 的 chat_id、Discord 的 guild_id 都在 `metadata` 里）。

**global handlers**：用 `subscribe_all(handler)` 注册，任何 channel 的任何消息都触发。Logger、Analytics、成本统计、安全审计这类横切关注点对消息来源无感知——它们只关心"有消息发生了"，不关心"消息从哪里来"。

**Convention**：**横切关注点**（cross-cutting concerns）= 系统中与业务逻辑正交的通用能力，如日志、监控、权限审计、成本计量——它们"横穿"所有业务模块而不属于其中任何一个。在直连架构里，横切关注点会被迫耦合到每一个调用点；在 Bus 架构里，它们通过 `subscribe_all` 集中注册一次，与业务逻辑完全隔离。

把横切关注点注册成 global handler 的关键好处是：加一个新的 channel（从 4 个增加到 5 个），Logger 不需要任何改动。Logger 注册了一次 `subscribe_all`，之后无论有多少个 channel，它都自动收到所有消息。如果 Logger 是 channel-specific，加 channel 就必须同步更新 Logger 的注册，这是在 Bus 层复现 N×M 的耦合。

判断规则：handler 需不需要知道消息来自哪个 channel？需要 → channel-specific（如 AgentLoop 需要 chat_id、guild_id）。不需要 → global（如 Logger、Analytics）。

这个区分在 nano-claw 的 `bus/index.ts` 里表现为两个独立的数据结构（`handlers: Map<string, Set<MessageHandler>>` 和 `globalHandlers: Set<MessageHandler>`），不是同一个结构里的不同标签。数据结构的分离保证了两类 handler 的管理逻辑不互相干扰。

---

## Beat 4 — 脚手架

下面实现最小的 MessageBus 骨架——只包含把一条消息路由到一个 handler 并验证其工作所需的内容：

```python
# bus.py — MessageBus 最小骨架（lena-v0.16）
# 运行要求：Python 3.10+，无额外依赖
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# Handler 签名：接收一条消息，返回 None
# Callable[["ChannelMessage"], Awaitable[None]] 表示：
#   - 接受一个 ChannelMessage 参数
#   - 必须是 async 函数（返回 Awaitable[None]）
MessageHandler = Callable[["ChannelMessage"], Awaitable[None]]

@dataclass
class ChannelMessage:
    channel_type: str  # 来源，如 "telegram" / "discord" / "http"
    user_id: str       # 发送者标识
    content: str       # 消息正文
    # id 和 metadata 有默认值，可以不传
    id: str = field(default_factory=lambda: __import__('uuid').uuid4().hex)
    metadata: dict = field(default_factory=dict)

class MessageBus:
    def __init__(self):
        # channel-specific handlers: {"telegram": {h1, h2}, "discord": {h3}}
        # Set 而非 list：同一个 handler 注册两次，Set.add 幂等，不会重复调用
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
                del self._handlers[channel_type]  # 空 Set 及时清理，防内存泄漏

    async def publish(self, message: ChannelMessage) -> None:
        # 先快照（转 list），再 gather
        # 不快照直接 gather 的话，handler 执行期间若有 unsubscribe 调用
        # 会触发"set changed size during iteration"
        specific = list(self._handlers.get(message.channel_type, set()))
        glob     = list(self._global_handlers)
        await asyncio.gather(*[self._safe_call(h, message) for h in specific + glob])

    async def _safe_call(self, handler: MessageHandler, message: ChannelMessage) -> None:
        """隔仓包裹：handler 抛异常，只记日志，不 rethrow，gather 继续"""
        try:
            await handler(message)
        except Exception as e:
            logger.error(f"Handler '{handler.__name__}' failed on {message.id}: {e}",
                         exc_info=True)
            # 关键：不 rethrow。其他 handler 的 safe_call 照常完成。

    def handler_count(self, channel_type: str | None = None) -> int:
        if channel_type:
            return len(self._handlers.get(channel_type, set()))
        return sum(len(v) for v in self._handlers.values()) + len(self._global_handlers)
```

验证骨架跑通：

```python
async def test_skeleton():
    bus = MessageBus()

    async def dummy_handler(msg: ChannelMessage):
        print(f"[OK] 收到: {msg.channel_type} → {msg.content!r}")

    bus.subscribe("telegram", dummy_handler)
    await bus.publish(ChannelMessage(channel_type="telegram",
                                     user_id="u1", content="hello"))
    # 预期输出：[OK] 收到: telegram → 'hello'
    print(f"handler_count: {bus.handler_count()}")
    # 预期输出：handler_count: 1

asyncio.run(test_skeleton())
```

预期两行输出：`[OK] 收到: telegram → 'hello'` 和 `handler_count: 1`。骨架跑通，接下来逐步添加真实系统的需要。

---

## Beat 5 — 渐进组装

骨架已经有了最核心的 `_safe_call`，但还缺两件事：channel 需要一个标准化的"启动/停止"接口，Lena 需要一个能在运行时 attach/detach channel 的管理者。我们逐步加上。

| 扩展点 | 为何需要 | 如何加 |
|--------|---------|--------|
| `_safe_call` 实际验证 | 要看到"一个 handler 崩了，另一个继续"的实际输出，不只是相信理论 | 注册一个故意抛错的 handler，观察其他 handler 是否不受影响 |
| `ChannelPlugin` 基类 | channel 需要标准化的 start/stop 接口，才能被统一 attach/detach | 定义抽象基类，强制实现 `channel_type` 属性和 `receive()` |
| `ChannelManager` | Lena 需要一个地方管理所有活跃 channel，支持运行时增减 | 独立类，持有 `{channel_type: plugin}` 字典 |

### 扩展 1：验证 safeHandlerCall 的隔离效果

这是最重要的一步，我们先用代码证明它有效，再继续：

```python
# 三个 handler：agent_loop 和 analytics 正常，buggy_logger 故意崩
async def verify_isolation():
    bus = MessageBus()

    async def agent_loop(msg: ChannelMessage):
        print(f"  [AgentLoop] 处理: {msg.content!r}")

    async def buggy_logger(msg: ChannelMessage):
        raise RuntimeError("Logger 磁盘满了")

    async def analytics(msg: ChannelMessage):
        print(f"  [Analytics] 统计: channel={msg.channel_type}")

    bus.subscribe("telegram", agent_loop)
    bus.subscribe("telegram", buggy_logger)
    bus.subscribe("telegram", analytics)

    print(f"注册了 {bus.handler_count('telegram')} 个 telegram handlers\n")

    msg = ChannelMessage(channel_type="telegram", user_id="u1", content="test")
    await bus.publish(msg)

asyncio.run(verify_isolation())
```

运行结果：

```
注册了 3 个 telegram handlers

  [AgentLoop] 处理: 'test'
  [Analytics] 统计: channel=telegram
ERROR:bus:Handler 'buggy_logger' failed on ...: Logger 磁盘满了
```

`agent_loop` 和 `analytics` 都执行了，`buggy_logger` 的错误被记录但没有传播。注意输出顺序可能不固定——三个 handler 是并发执行的，谁先打印取决于调度。这是 `asyncio.gather` 的并发语义，是预期行为。

### 扩展 2：ChannelPlugin — channel 的标准化接口

热插拔需要 channel 能独立启动和停止。让我们定义接口：

```python
# channel_plugin.py — 可热插拔的 channel 基类
import abc
from bus import MessageBus, ChannelMessage

class ChannelPlugin(abc.ABC):
    """
    channel 实现这个接口，就能被 ChannelManager 热插拔。

    channel 是 Publisher：它监听外部来源（Telegram Bot API、Discord Webhook 等），
    把收到的消息转换成 ChannelMessage，通过 self.bus.publish() 发到 Bus。

    channel 不持有任何 Subscriber 的引用。这是 pub/sub 解耦的体现。
    """

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self._running = False

    @property
    @abc.abstractmethod
    def channel_type(self) -> str:
        """channel 的唯一标识，如 'telegram' / 'discord' / 'http'"""
        ...

    async def start(self) -> None:
        """启动 channel。子类 override 时在这里建立外部连接。"""
        self._running = True

    async def stop(self) -> None:
        """停止 channel。子类 override 时在这里关闭外部连接。"""
        self._running = False

    async def receive(self, user_id: str, content: str, **metadata) -> None:
        """
        收到外部消息时调用，发布到 Bus。
        子类的 polling/webhook 逻辑最终都调这里。
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

用于演示的 MockChannel：

```python
class MockChannel(ChannelPlugin):
    """无真实外部连接的 channel，用于测试和演示。"""

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

### 扩展 3：ChannelManager — 运行时 attach/detach

有了 ChannelPlugin 基类，ChannelManager 的逻辑很简单：

```python
# channel_manager.py — 运行时管理所有 channel
from bus import MessageBus
from channel_plugin import ChannelPlugin

class ChannelManager:
    def __init__(self, bus: MessageBus):
        self.bus = bus
        self._channels: dict[str, ChannelPlugin] = {}

    async def attach(self, channel: ChannelPlugin) -> None:
        """运行时接入新 channel。相同 channel_type 不能重复 attach。"""
        ct = channel.channel_type
        if ct in self._channels:
            raise ValueError(f"'{ct}' already attached. detach first.")
        self._channels[ct] = channel
        await channel.start()
        print(f"  [Manager] attach '{ct}' OK. Active: {self.list_channels()}")

    async def detach(self, channel_type: str) -> None:
        """运行时移除 channel。不存在时静默忽略。"""
        ch = self._channels.pop(channel_type, None)
        if ch:
            await ch.stop()
            print(f"  [Manager] detach '{channel_type}' OK. Active: {self.list_channels()}")

    def list_channels(self) -> list[str]:
        return list(self._channels.keys())
```

验证热插拔：

```python
async def verify_hotplug():
    bus = MessageBus()
    manager = ChannelManager(bus)

    async def agent_handler(msg: ChannelMessage):
        print(f"  [AgentLoop] {msg.channel_type}: {msg.content!r}")

    bus.subscribe("telegram", agent_handler)
    bus.subscribe("discord", agent_handler)

    # 只 attach telegram，discord 尚未连接
    telegram = MockChannel("telegram", bus)
    await manager.attach(telegram)
    print(f"  启动后 channels: {manager.list_channels()}")
    # 输出：启动后 channels: ['telegram']

    await telegram.receive("u1", "第一条消息")

    # 运行中 attach discord
    discord = MockChannel("discord", bus)
    await manager.attach(discord)
    print(f"  attach discord 后: {manager.list_channels()}")
    # 输出：attach discord 后: ['telegram', 'discord']

    await discord.receive("u2", "discord 消息")

    # 运行中 detach telegram
    await manager.detach("telegram")
    print(f"  detach telegram 后: {manager.list_channels()}")
    # 输出：detach telegram 后: ['discord']

asyncio.run(verify_hotplug())
```

每一步都有打印，确认状态与预期一致。三个中间状态都验证后，我们把完整的 Lena v0.16 组装起来。

---

## Beat 6 — 运行验证

下面端到端运行完整的 Lena v0.16，验证三个能力协同工作。完整代码在 `code/lena-v0.16/main.py`，这里展示关键部分：

```python
# main.py — Lena v0.16 完整示例（精简版，完整版见代码目录）
# 运行方式：python main.py
# 依赖：Python 3.10+ 标准库，无需 pip install

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

from bus import MessageBus, ChannelMessage
from channel_plugin import MockChannel
from channel_manager import ChannelManager


# ── Subscribers ──────────────────────────────────────────────────────

async def agent_loop_handler(msg: ChannelMessage) -> None:
    """核心 agent 逻辑（简化版，真实版会调 LLM API）"""
    print(f"  [AgentLoop] from={msg.channel_type} user={msg.user_id} '{msg.content}'")

async def logger_handler(msg: ChannelMessage) -> None:
    """全局日志：所有 channel 的消息都记录"""
    print(f"  [Logger]    {msg.channel_type}:{msg.user_id} → {msg.content[:40]!r}")

async def buggy_analytics(msg: ChannelMessage) -> None:
    """故意崩溃，验证 safeHandlerCall 隔离效果"""
    raise RuntimeError("Analytics service down")


async def main():
    bus = MessageBus()
    manager = ChannelManager(bus)

    # 注册 handlers
    bus.subscribe("telegram", agent_loop_handler)
    bus.subscribe("discord",  agent_loop_handler)
    bus.subscribe_all(logger_handler)   # global：所有 channel 都触发
    bus.subscribe_all(buggy_analytics)  # global：但每次都崩，验证隔离

    # 场景 1：telegram 消息
    telegram = MockChannel("telegram", bus)
    await manager.attach(telegram)
    print(f"\n[场景 1] telegram 消息（analytics 会崩，但 AgentLoop 和 Logger 正常）")
    await telegram.receive("user_001", "现在几点？")

    # 热插拔：attach discord
    print(f"\n[热插拔] attach discord")
    discord = MockChannel("discord", bus)
    await manager.attach(discord)
    print(f"当前 channels: {manager.list_channels()}")

    # 场景 2：discord 消息
    print(f"\n[场景 2] discord 消息")
    await discord.receive("user_002", "帮我查一下明天的天气")

    # 热插拔：detach telegram
    print(f"\n[热插拔] detach telegram")
    await manager.detach("telegram")
    print(f"剩余 channels: {manager.list_channels()}")

    # 场景 3：discord 消息（telegram 已移除，discord 正常）
    print(f"\n[场景 3] discord 消息（telegram 已移除）")
    await discord.receive("user_003", "好的，谢谢")

    print(f"\n最终 handler 数量: {bus.handler_count()}")

asyncio.run(main())
```

**运行 `python main.py`，你应该看到**（约 25 行，< 0.1 秒）：

```
  [MockChannel:telegram] started

[场景 1] telegram 消息（analytics 会崩，但 AgentLoop 和 Logger 正常）
  [AgentLoop] from=telegram user=user_001 '现在几点？'
  [Logger]    telegram:user_001 → '现在几点？'
ERROR:bus:Handler 'buggy_analytics' failed on ...: Analytics service down

[热插拔] attach discord
  [MockChannel:discord] started
当前 channels: ['telegram', 'discord']

[场景 2] discord 消息
  [AgentLoop] from=discord user=user_002 '帮我查一下明天的天气'
  [Logger]    discord:user_002 → '帮我查一下明天的天气'
ERROR:bus:Handler 'buggy_analytics' failed on ...: Analytics service down

[热插拔] detach telegram
  [MockChannel:telegram] stopped
剩余 channels: ['discord']

[场景 3] discord 消息（telegram 已移除）
  [AgentLoop] from=discord user=user_003 '好的，谢谢'
  [Logger]    discord:user_003 → '好的，谢谢'
ERROR:bus:Handler 'buggy_analytics' failed on ...: Analytics service down

最终 handler 数量: 4
```

**验证三点**：①`buggy_analytics` 报 ERROR 但其他 handler 正常打印（隔离有效；反证：删掉 `_safe_call` 的 `except` 块重跑，输出会消失）。②场景 2 的 discord 消息处理正常，但 discord 在场景 1 时还不存在（subscribe 先于 attach 生效）。③场景 3 telegram 已 detach 但 discord 正常（detach 不影响其他 channel）。

**常见报错诊断**：
- `RuntimeError: Channel 'X' not started` → 直接调用了 `channel.receive()` 而没有先 `await manager.attach(channel)`
- `set changed size during iteration` → 在 handler 执行过程中调用了 `bus.unsubscribe()`，修复方式是在 `publish` 里先 `list()` 转换再 gather（骨架代码已处理）
- `TypeError: object bool can't be used in 'await'` → handler 函数忘了加 `async`，是普通函数不是 coroutine
- `KeyError: 'telegram'` → `bus.handler_count('telegram')` 在没有 telegram handler 时返回 0 而非报错——这个 bug 在骨架代码里已修复（用 `.get(channel_type, set())`）

---

## Beat 7 — Design Note

> **Why Not Use a Message Queue (MQ)?**
>
> MessageBus 和 Kafka / RabbitMQ / Redis Streams 解决的看起来是同一个问题：publisher 发消息，subscriber 收消息，中间有一层 broker 解耦。既然这些系统成熟稳定、有监控工具、有 replay 能力，为什么不直接用，而是在进程内手写一个 Bus？
>
> **替代方案**：Lena 的每个 channel 发消息到 Redis pub/sub 的一个 channel，AgentLoop 作为 subscriber 消费。配置成本：`pip install redis`，加一个 Redis 连接，把 `publish` 改成 `redis.publish()`，把 handler 注册改成 Redis subscriber 的 listen loop。
>
> **Tradeoff 分析**：
>
> | 维度 | 进程内 MessageBus | Redis pub/sub | Kafka |
> |------|-----------------|--------------|-------|
> | 运维成本 | 零，无依赖 | Redis 实例 + 连接管理 | Kafka + KRaft + 监控 |
> | 消息延迟 | 数微秒量级（Python asyncio 事件循环调度开销；实际取决于 Python 版本和系统负载） | < 1 毫秒（本地回环，redis-benchmark 实测 SET p50 = 0.143 ms） | p99 = 5 ms @ 200K msg/s（Confluent 官方 benchmark，1 KB payload，单 broker 典型配置） |
> | 峰值吞吐 | 受 Python GIL 限制，单核约数万/s | redis-benchmark 典型吞吐 > 100K ops/s（50 并发客户端，来源：redis.io 官方 benchmarks 页；SET p50 = 0.143 ms 是每请求延迟，与吞吐不矛盾） | 实测峰值 605 MB/s（约 6 亿 byte/s，Confluent 2021 benchmark） |
> | 消息持久化 | 无（进程重启丢失） | 无（pub/sub 不落盘，Redis Streams 可持久化） | 有（可配置保留期） |
> | 消息回放 | 无 | pub/sub 无回放；Streams 有 | 有，offset 任意定位 |
> | 水平扩展 | 无，单进程 | 有，多消费者 | 有，consumer group |
>
> **当前选择的理由**：Lena 是单机 personal agent，channel 数量个位数（4–8 个），消息量每分钟几十条，峰值每分钟几百条。在这个规模下，引入 Redis 引入了 5 个新的运维问题（Redis 进程管理、连接池配置、连接超时处理、消息序列化/反序列化、Redis 崩溃时 Lena 的 fallback 行为），来解决一个在当前规模下不存在的问题（单进程处理能力不足）。这不是工程决策，是工程债务。
>
> **什么时候该换成 MQ**：Lena 需要**跨机器运行**时——主 agent 在服务器 A，Telegram channel 在服务器 B（比如为了隔离 Telegram Bot Token 的暴露面），两个进程之间的通信必须有网络传输，Redis pub/sub 是最简单的选择。或者 Lena 的消息量因为多租户（同时服务 1000 个用户）超出单进程处理能力时。
>
> **切换成本**：几乎没有。替换 `MessageBus.publish` 的实现，把它改成 `redis.publish()`；把 `subscribe/subscribe_all` 改成 Redis 订阅逻辑。上层 channel 代码（`channel.receive()` 调 `bus.publish()`）和 handler 代码完全不变。这是进程内 Bus 设计的最大优点：接口稳定，实现可替换。

---

## 本章小结

三个问题 → 三个工具：

- **耦合爆炸**（N×M 直连线）→ pub/sub Bus，N+M 条线，双方互不知晓
- **错误传播**（asyncio.gather 把一个 handler 的异常传播给整批）→ `_safe_call` 包裹层，异常在每个 handler 内部消化，不向外传播
- **静态结构**（添加/移除 channel 需要重启）→ `subscribe/unsubscribe` + `ChannelManager.attach/detach` 实现运行时热插拔

横切关注点用 `subscribe_all`（注册一次适用所有 channel），业务逻辑用 `subscribe`（精准订阅）——这是防止在 Bus 层复现 N×M 耦合的关键区分。

进程内 Bus vs 分布式 MQ 的选择是规模工程决策，不是品味问题：Kafka p99 在 200K msg/s 负载下为 5 ms，对个人 agent 的场景是引入 5 个新运维问题来解决一个不存在的规模问题。

---

下一章，Lena 有了 MessageBus，任何 channel 崩了不影响整体，channel 也可以随时热插拔。但 Lena 现在还是完全被动的——只有用户发消息，她才响应。

**Ch 17**：给 Lena 加上 Heartbeat。Heartbeat 本质上是 MessageBus 的一个特殊 Publisher：消息不来自用户，来自时钟。每次 tick，Heartbeat 向 Bus 发布一条 `system:heartbeat` 消息，AgentLoop 订阅它，检查"有没有 pending 的定时任务需要触发"。这是 Lena 从"被动响应"升级到"主动出击"的基础设施——Heartbeat 让她有了自己的生物钟。

---

## 延伸阅读

| 资料 | 内容 |
|------|------|
| `nano-claw/src/bus/index.ts`（134 行） | TypeScript 版 MessageBus 完整实现，本章 Python 版的原型 |
| `nano-claw/src/channels/manager.ts` | Channel → Bus 的注册逻辑（TypeScript 版） |
| Michael Nygard, *Release It!: Design and Deploy Production-Ready Software*, 2nd ed., Stability Patterns 章节 | Bulkhead Pattern 的标准参考（Nygard 在生产系统故障分析中系统化了这个模式）；不需要读完，只需要知道：隔仓 = 限制一个组件的故障影响范围 |
| Apache Kafka Documentation, "Introduction to Event Streaming" | 分布式 pub/sub 的标准参考；不需要读完，只需要知道：Kafka 解决的是"多机、高吞吐、持久化"场景，本章的进程内 Bus 解决的是"单机、低延迟、零运维"场景 |
| Confluent, "Benchmarking Apache Kafka, Apache Pulsar, and RabbitMQ" (developer.confluent.io/learn/kafka-performance/) | Beat 7 表格数据来源：Kafka p99 = 5 ms @ 200K msg/s，峰值 605 MB/s；RabbitMQ 在高吞吐下延迟会显著升高（Confluent 基准测试仅覆盖 Kafka 与 Pulsar 的对比，RabbitMQ 延迟特性见 CloudAMQP 最佳实践文档） |
| NATS.io, "Sophotech: Cutting Latency by 3x Migrating from RabbitMQ to NATS" (nats.io/blog/sophotech-rabbitmq-to-nats) | 进程间通信场景从 RabbitMQ 迁移到 NATS 的真实案例：p99 从 ~150 ms → ~40 ms，运维时间从数小时/周 → 1 小时以内 |
| Redis documentation, "Redis Benchmarks" (redis.io/docs/latest/operate/oss_and_stack/management/optimization/benchmarks) | redis-benchmark 官方实测数据：SET p50 = 0.143 ms（50 并发客户端，无流水线），吞吐典型值 > 100K ops/s |
