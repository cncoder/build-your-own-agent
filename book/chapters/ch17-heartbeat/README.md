# 第 17 章：Heartbeat——让 Agent 主动找你

```
Ch1 → Ch3 → Ch6 → Ch8 → Ch11 → Ch15 → Ch16 → [Ch17 ← 你在这里] → Ch18 → ...
```

本章从一个**只会回应的 Lena**（Ch16 产物，已有 MessageBus 和 Channel 插拔能力）出发，经过一个反直觉翻转——proactive agent 不只是"更勤快的 reactive agent"，而是**控制权归属**的根本切换——再实现最简 Heartbeat（178 行，setTimeout + EventEmitter），然后分解生产级 4 子模块的协同逻辑，最终让 Lena 每天 08:00 不等任何人发消息，自己推送早报到 Telegram（`lena-v0.17/`）。途中踩一个坑：当主 agent 挂掉时，告警通道为什么必须独立于主线程之外。

Lena 在本章从 **v0.16**（MessageBus + Channel）变成 **v0.17**，新能力是：**每天 08:00 主动开口**。

---

## Beat 1 — 路线图

```
                   ┌─────────────────────────────────────────────────────────┐
                   │               本章叙事弧                                 │
                   │                                                           │
  起点             │  中间地带                           终点                 │
  ────             │  ────────────────────               ────                 │
  只会响应的 Lena  │  1. Proactive 翻转（反直觉）        每天 08:00           │
  (Ch16 产物)      │  2. 178 行最简 Heartbeat            主动发 Telegram 早报 │
                   │  3. 生产级 4 子模块深度              (lena-v0.17)         │
                   │  4. Watchdog 独立告警通道                                 │
                   │                                                           │
                   │  途中踩坑：主线挂了，告警通道也跟着挂                    │
                   └─────────────────────────────────────────────────────────┘
```

**本章新增能力**：Proactive push。Lena 不再只等你叫，她知道什么时候该说话。

这是 always-on agent 的核心能力。没有 Heartbeat，Lena 只是一个反应式工具——你的交互体验和搜索引擎本质上没有区别；有了 Heartbeat，她才开始具备助理的本质属性：**主动感知时间，主动判断价值，主动开口**。

从读者的角度看，本章结束后你能做到：
- 用 178 行 TypeScript（或等价的 Python asyncio）实现一个能跑通的 Proactive Heartbeat
- 理解 active-hours 时区感知为什么不能简单用 `new Date().getHours()`，以及错误使用会产生什么后果
- 理解独立告警通道的架构必要性（不是"可以有更好"，而是"主线挂了必须能通知"的结构性需求）
- 知道什么时候用 nano-claw 178 行版本，什么时候需要 OpenClaw 4 子模块版本，以及为什么不要"以防万用"地直接用最复杂的版本

> **🧠 聪明度增量（v0.16 → v0.17）**：Lena 第一次有了脉搏——Heartbeat 定时器让她从"等人叫才开口"的被动工具变成"主动感知时间、主动判断价值、主动开口"的助理，每天 08:00 无需任何触发自动推送早报。这一章教读者把 always-on proactive 能力长在自己 agent 上的方法。

---

## Beat 2 — 动机：没有 Heartbeat 的 always-on agent 是什么

Ops 领域有一个经典隐喻 **Pets vs Cattle**，最早由微软工程师 Bill Baker 在 2012 年的演讲中提出：

> "A pet is a named, hand-tended individual you can't afford to lose. Cattle are interchangeable. In our case, the server became that pet; if a container failed, the session was lost."
> （Pets vs Cattle 隐喻，出处：Bill Baker，Microsoft，2012 年演讲；后被 ops 社区广泛采用）

没有 Heartbeat 的 agent 就是一只"宠物"——活着的时候很好用，死了你才发现它没在跑。Heartbeat 的本质是让 agent 变成"牛群"——stateless、可替换、挂了自动重生，通过定期**心跳信号**向外证明自己还活着。

把 Ch16 的 Lena 跑起来，等 24 小时，统计她主动发出的消息数量：**0 条**。

```bash
$ npm start
[Lena v0.16] started — gateway=ws://localhost:8765
[Channel] Telegram connected
[MessageBus] ready

... 等待用户发消息 ...
... 24 小时后 ...
... 仍然在等待 ...
```

这是 always-on 的悖论。"always-on"意味着进程一直运行、通道一直保持连接，但系统行为上仍然是完全被动的——用户不发消息，agent 永远不说话。你拥有一个全天候待命的助理，但这个助理什么也不主动做。

想象一个真实场景：你是一个工程师，Lena 帮你监控生产环境。

- 凌晨 2:30，某个后台任务静默失败
- 早上 9:00 你才发现，整整 6.5 小时没人知道

为什么 6.5 小时没有通知？因为 Lena 在等你问她"有没有问题"。她不会主动开口告诉你有问题。

两种看起来能解决问题的替代方案：

**方案 A：用外部 cron 每小时发一条假消息给 Lena**

```bash
# 系统 cron：每小时发一条"检查一下系统状态"
0 * * * * curl -X POST localhost:8765/message -d '{"text":"check"}'
```

这能跑，但有三个问题：① 时间控制逻辑泄漏到了 agent 外部，每加一个时间规则都要改 cron；② active-hours 的判断需要在两个系统里分别维护；③ Lena 收到的是一条"假消息"而不是真实的触发，她无法区分用户发的消息和 cron 发的指令——这会破坏对话历史的语义完整性。

**方案 B：用 setTimeout 在 agent 内部轮询，到了 8 点就执行任务**

这已经是 Heartbeat 的雏形了，但它还缺几个关键组件：active-hours 时区感知、内容门控（没有内容时静默跳过）、以及推送通道的解耦。

这些缺少的组件，就是本章要实现的 178 行里的内容。

**用数字说明差距**：没有 Heartbeat 的 always-on agent，用户必须自己记住"该去问 Lena 了"——这和没有 Lena 本质上没有区别，用户的认知负担没有减少。有了 Heartbeat，用户的主动查询次数从"必须每次主动问"变为"只有 Lena 没说、你才需要主动问"。对于日报类场景，这意味着用户的主动交互频率降低了 90%。

---

## Beat 3 — 理论铺垫

### 3.1 Proactive vs Reactive 是什么

乍看，Reactive 等外部触发、Proactive 自己触发，这像是实现细节的差异。深一层，这是**控制权归属**的根本不同。

**Reactive agent** 的控制权完全在用户端：用户决定何时触发、触发什么、触发多频繁。agent 的价值取决于用户的主动性——用户忘了问，agent 永远不说。用户不知道该问什么，agent 也没有价值。这和搜索引擎的结构本质上一样：强大，但被动。

```
Reactive Agent 时序：

用户          Agent
 │              │
 │── 发消息 ───►│
 │              │── 思考 + 执行
 │◄── 回复 ─────│
 │              │
 │  （等待）    │  ← Agent 永远在等
 │              │
 │── 发消息 ───►│
 │              │── 思考 + 执行
 │◄── 回复 ─────│

问题：用户必须知道该问什么，agent 才有价值
     用户忘了问 → agent 永远沉默
```

**Proactive agent** 的控制权部分转移到 agent 端：agent 持有自己的时间感知，知道"现在是 08:00，这个时间点对用户有价值"，知道"后台任务在 2:30 失败了，用户应该知道"。

```
Proactive Agent 时序（有 Heartbeat）：

用户          Agent         Heartbeat
 │              │                │
 │              │◄──── tick ─────│  ← 08:00 触发
 │              │                │
 │              │── 判断 active hours
 │              │── 评估有无内容
 │              │── 生成早报摘要
 │◄── 主动推送 ──│
 │              │                │
 │  (可选回复)  │                │
 │── 回复 ──────►│               │
 │              │                │
 │              │◄──── tick ─────│  ← 09:00 触发（本次静默跳过）

优势：agent 知道什么时候说话，知道什么时候沉默
     用户不需要主动问，也能得到有价值的信息
```

Karpathy 在描述 LLM 的演化方向时说："increasingly, we'd want models to have agency and to be able to take actions in the world"（来源：Karpathy，Intro to LLMs，2024）。"在世界中采取行动"的前提，是 agent 能感知时间、主动判断何时行动。

Convention：**Reactive** = 等外部事件触发后才运行；**Proactive** = 自持时钟，主动判断何时运行。（后续统一用这两个词。）

这不是一个性能优化，而是一个**架构属性**的差异。没有 Heartbeat 的 always-on agent，"always-on"只是一个运维状态描述（进程没挂），不是一个能力描述（agent 在工作）。两者的区别，就像一个医院的急诊室（reactive：等病人来）和一个健康监测 app（proactive：主动提醒你体检）的区别——前者功能更强大，但你必须知道自己需要去急诊，才能得到帮助。

### 3.2 Heartbeat 的三层设计空间

一个可用的 Heartbeat 系统需要回答三个正交的问题。这三个问题构成了从 178 行甜点版到 OpenClaw 生产版的能力阶梯。

**问题 1：何时触发？**（时间门控）

最简方案：固定 interval，每 N 分钟检查一次。这已经能工作了，但有一个核心问题：凌晨 3 点的触发毫无意义——用户在睡觉，就算生成了内容也没人能看到。

生产方案加 active-hours：定义用户的活跃时间窗口，只在窗口内推送。active-hours 需要时区感知，因为用户可能在上海（UTC+8）而服务器在美国西部（UTC-7）——服务器的"下午 3 点"是用户的"次日早上 6 点"。如果不做时区转换，你以为 agent 在"下午推送"，实际上是在深夜打扰用户。

```
时区问题示意：

服务器 UTC-7 早上 7:00
         ↓
用户上海 UTC+8 就是当天 22:00（晚上 10 点）

错误配置：用服务器本地时间 7-22 作为 active hours
→ 实际上是在用户的 22:00 到次日 13:00 推送
→ 凌晨 3 点你的手机响了

正确配置：active-hours.timezone = "Asia/Shanghai"
          weekdays = { start: 8, end: 22 }
→ 严格对应用户上海时间的 8:00-22:00
```

**问题 2：是否推送？**（内容门控）

触发不等于推送。每次节拍都应该问一个问题："现在有值得说的内容吗？"

如果日历空空如也、没有任务完成、也没有系统事件，就静默跳过，不发无意义的"今天没什么"。LLM 的 HEARTBEAT_OK 机制（OpenClaw 生产版的概念）就是实现这个门控的：LLM 回了一个 ok token 表示没有实质内容，Heartbeat 静默跳过，不发任何消息。

内容门控是 agent 情商的核心体现：知道什么时候不说话，和知道什么时候说话同等重要。一个每次节拍都发消息的 agent，用不了三天用户就会关掉通知。

**问题 3：推送给谁，用什么通道？**（通道门控）

最简方案：固定 channel，固定 bot token。生产方案加三层：

- **Visibility**：用户当前是否在线（DND 模式、已读状态）。如果用户设置了勿扰，只发静默心跳包，不触发手机响
- **Dedupe**：24 小时内不发重复内容。如果今天和昨天的早报完全一样，用户不需要看第二遍
- **独立告警通道**：主线挂了告警仍能送达（这是 3.3 的主题）

这三个问题构成了设计阶梯：

| | nano-claw 178 行 | OpenClaw 4 子模块 |
|---|---|---|
| 时间门控 | 整数小时的 active-hours | 精确到分钟，支持跨午夜 |
| 内容门控 | 生成器返回 null 跳过 | HEARTBEAT_OK token + transcript prune |
| 通道门控 | 固定 channel | visibility + dedupe + 独立告警通道 |

178 行回答了问题 1 和问题 2 的最简版本；4 子模块对三个问题都给出了完整的生产级答案。本章的代码实现走 178 行路线。

### 3.3 独立告警通道的必要性

这是一个典型的"踩了才记住"的设计原则。

考虑这个场景：你用 Watchdog 监控 OpenClaw，出问题时发 Telegram 告警。Watchdog 的告警消息通过 OpenClaw 的 Telegram bot 发出。

某天 OpenClaw 崩溃了。Watchdog 检测到崩溃，准备发"OpenClaw 崩溃了"这条告警。问题来了：这条消息需要通过 OpenClaw 的 bot 发出——而这个 bot 的运行依赖 OpenClaw 的 gateway，而 gateway 刚刚崩溃了。

结果：告警消息静默丢失。故障发生，无声无息，没有任何通知。

```
                      OpenClaw 崩溃
                           │
                           ▼
Watchdog ──发告警──► OpenClaw gateway ──► 💥 已崩溃
                           │
                           ▼
                     告警消息丢失
                     你什么都不知道

正确做法：
Watchdog ──发告警──► 独立 AlertChannel ──► Telegram API（直连）
                     （不依赖 OpenClaw）        ↓
                                          你收到告警 ✓
```

这不是一个可以靠"加重试"解决的问题。根本原因是：告警通道和被监控的系统共享了同一个故障点。无论重试多少次，只要 OpenClaw gateway 不可达，所有通过它发出的消息都会丢失。

Convention：**主通道** = agent 正常工作时的消息通道；**独立告警通道** = 独立于主 agent 运行时的备用告警路径。（后续统一用这两个词。）

解法的核心约束：**独立告警通道不能依赖任何主 agent 的代码路径**。这意味着：独立进程（或至少独立类）、独立 bot token（另一个 Telegram bot）、最小依赖（只需系统级网络库，不依赖 agent 的任何模块）。

还有一个更微妙的问题：**指数退避**。如果 OpenClaw 每隔 5 秒崩溃一次又重启（crash loop），没有退避控制的 Watchdog 会每 5 秒发一条告警，凌晨 3 点你的手机会被刷屏 720 条通知。指数退避把告警频率控制在合理范围：第一次故障立刻通知，连续故障逐渐降低频率。这是一个"静默失败比刷屏更好吗？"的 tradeoff，答案是：两者都不好，指数退避是中间路线。

这是 Beat 7 的主题，我们在那里深入展开。

---

## Beat 4 — 脚手架

下面实现最小的 Heartbeat 骨架，从最基本的部分开始：一个按计划触发并发出事件的计时器。

```typescript
// 最小骨架：能跑通，30 行，无 active-hours，无内容生成
// 运行后每 5 秒打印一次 beat 事件
import { EventEmitter } from "events";

interface HeartbeatConfig {
  intervalMs: number;  // 节拍间隔，测试用 5_000（5 秒），生产用 3_600_000（1 小时）
  enabled:    boolean; // 开关，方便集成测试时关掉整个 Heartbeat
}

export class Heartbeat extends EventEmitter {
  private config:    HeartbeatConfig;
  private timer:     ReturnType<typeof setTimeout> | null = null;
  private tickCount = 0;  // 节拍计数，方便日志追踪（tick#1, tick#2, ...）

  constructor(config: HeartbeatConfig) {
    super();
    this.config = config;
  }

  start(): void {
    if (!this.config.enabled) { console.log("[Heartbeat] disabled"); return; }
    console.log(`[Heartbeat] started, interval=${this.config.intervalMs}ms`);
    this.scheduleNext();
  }

  stop(): void {
    if (this.timer !== null) { clearTimeout(this.timer); this.timer = null; }
    console.log("[Heartbeat] stopped");
  }

  // 关键设计：递归 setTimeout，而非 setInterval
  // 原因：LLM 调用可能耗时 5-30 秒，setInterval 会导致节拍重叠
  // （上一次还没完成，下一次就触发了）
  // setTimeout 递归保证：上一次完成 → 等 intervalMs → 才触发下一次
  private scheduleNext(): void {
    this.timer = setTimeout(() => {
      void this.tick().finally(() => this.scheduleNext());
    }, this.config.intervalMs);
  }

  private async tick(): Promise<void> {
    this.tickCount += 1;
    this.emit("beat", { count: this.tickCount, ts: new Date() });
    console.log(`[Heartbeat] beat #${this.tickCount} at ${new Date().toISOString()}`);
  }
}
```

运行 `new Heartbeat({ intervalMs: 5000, enabled: true }).start()` 应该每 5 秒打印一次 `beat #N`。接下来我们在这个骨架上逐步增加 active-hours、payload 生成和 outbound 事件。

**Python 等价骨架**（用 `asyncio` 替代 `setTimeout`，同样保证节拍不重叠）：

```python
# heartbeat.py — 最小骨架（Python asyncio 版）
# 运行后每 5 秒打印一次 beat 事件；asyncio.sleep 等价于递归 setTimeout
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Awaitable

@dataclass
class HeartbeatConfig:
    interval_sec: float   # 节拍间隔：测试用 5，生产用 3600
    enabled: bool         # 开关，集成测试时设 False

class Heartbeat:
    def __init__(self, config: HeartbeatConfig) -> None:
        self._config = config
        self._tick_count = 0
        self._task: asyncio.Task | None = None
        self._callbacks: list[Callable[..., Awaitable[None]]] = []

    def on_beat(self, fn: Callable[..., Awaitable[None]]) -> None:
        """注册 beat 回调（等价于 EventEmitter.on("beat", fn)）"""
        self._callbacks.append(fn)

    def start(self) -> None:
        if not self._config.enabled:
            print("[Heartbeat] disabled")
            return
        print(f"[Heartbeat] started, interval={self._config.interval_sec}s")
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
        print("[Heartbeat] stopped")

    async def _run(self) -> None:
        # 关键：await sleep 在 tick 完成后才等，保证节拍不重叠
        # 等价于 TypeScript 的 finally(() => scheduleNext())
        while True:
            await self._tick()
            await asyncio.sleep(self._config.interval_sec)

    async def _tick(self) -> None:
        self._tick_count += 1
        ts = datetime.now(timezone.utc)
        print(f"[Heartbeat] beat #{self._tick_count} at {ts.isoformat()}")
        for cb in self._callbacks:
            await cb(count=self._tick_count, ts=ts)

# 入口验证：运行后每 5 秒打印一次 beat
async def _demo() -> None:
    hb = Heartbeat(HeartbeatConfig(interval_sec=5, enabled=True))
    hb.on_beat(lambda **kw: asyncio.coroutine(lambda: None)())
    hb.start()
    await asyncio.sleep(16)   # 等 3 次 beat
    hb.stop()

if __name__ == "__main__":
    asyncio.run(_demo())
```

预期输出：
```
[Heartbeat] started, interval=5s
[Heartbeat] beat #1 at 2026-05-12T08:00:05.001Z
[Heartbeat] beat #2 at 2026-05-12T08:00:10.003Z
[Heartbeat] beat #3 at 2026-05-12T08:00:15.005Z
[Heartbeat] stopped
```

---

## Beat 5 — 渐进组装

| 扩展点 | 为何需要 | 如何加 |
|--------|---------|--------|
| Active Hours 检查 | 凌晨 3 点发"早上好"是 bug，不是 feature；时区感知防止服务器时间和用户时间错位 | 在 `tick()` 里调用 `isActiveHours()`，不在窗口内直接 return |
| Payload 生成器注入 | Heartbeat 不应该知道内容是什么——今天发问候、明天发天气，这是调用方的决策 | 构造函数接受 `generatePayload: () => Promise<string \| null>`，null 表示本次无内容跳过 |
| OutboundPayload 事件 | 解耦"什么时候推送"（Heartbeat 的职责）和"推到哪里"（channel 的职责） | 生成内容后 `emit("outbound", payload)`，调用方监听并决定用 Telegram / Discord / 飞书 |

**第一步扩展：加 active-hours 检查**

```typescript
// 扩展点 1：active-hours
// 时区感知是关键——用 Intl.DateTimeFormat 获取指定时区的本地时间
// 不要用 new Date().getHours()，那是服务器本地时间，与用户时区可能相差 8 小时
export interface ActiveHoursConfig {
  timezone: string;                            // IANA 时区，如 "Asia/Shanghai"
  weekdays: { start: number; end: number };    // 工作日时间窗口（0-23 小时整数）
  weekend?: { start: number; end: number };    // 可选：周末单独配置
}

export function isActiveHours(config: ActiveHoursConfig): boolean {
  const now   = new Date();
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: config.timezone,
    hour:     "numeric",
    weekday:  "short",
    hour12:   false,
  }).formatToParts(now);

  const hour      = parseInt(parts.find(p => p.type === "hour")!.value, 10);
  const weekday   = parts.find(p => p.type === "weekday")!.value;
  const isWeekend = weekday === "Sat" || weekday === "Sun";
  const schedule  = isWeekend ? (config.weekend ?? config.weekdays) : config.weekdays;

  return hour >= schedule.start && hour < schedule.end;
}
```

中间验证：`console.log(isActiveHours({ timezone: "Asia/Shanghai", weekdays: { start: 8, end: 22 } }))` 根据你当前的本地时间应该返回 `true`（如果现在是北京时间 8:00-22:00 之间）。

**Python 版 active-hours**（用标准库 `zoneinfo` 替代 `Intl.DateTimeFormat`）：

```python
# active_hours.py — 时区感知的活跃时间窗口检查（Python 3.9+）
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+ 内置；3.8 用 pip install backports.zoneinfo

@dataclass
class ActiveHoursConfig:
    timezone: str             # IANA 时区，如 "Asia/Shanghai"
    weekday_start: int        # 工作日开始小时（0-23）
    weekday_end: int          # 工作日结束小时（0-23）
    weekend_start: int = 0    # 周末开始，默认与工作日相同
    weekend_end: int = 24     # 周末结束，默认全天

def is_active_hours(cfg: ActiveHoursConfig) -> bool:
    """判断当前时刻是否在用户的活跃时间窗口内。
    
    关键：用 ZoneInfo 转换到用户时区，不用 datetime.now().hour（服务器本地时间）。
    """
    now = datetime.now(ZoneInfo(cfg.timezone))
    hour = now.hour
    is_weekend = now.weekday() >= 5          # 0=周一，5=周六，6=周日
    start = cfg.weekend_start if is_weekend else cfg.weekday_start
    end   = cfg.weekend_end   if is_weekend else cfg.weekday_end
    return start <= hour < end

# 中间验证
if __name__ == "__main__":
    cfg = ActiveHoursConfig(timezone="Asia/Shanghai", weekday_start=8, weekday_end=22)
    print(is_active_hours(cfg))   # True，当北京时间在 8:00-22:00 之间
```

**第二步扩展：注入 Payload 生成器，加 OutboundPayload 事件**

```typescript
// 扩展点 2 + 3 的完整 HeartbeatRunner
// 把 Beat 4 的骨架替换成这个，加入 activeHours + generator + outbound
export interface HeartbeatConfig {
  intervalMs:  number;
  activeHours: ActiveHoursConfig;
  agentId:     string;
  channelId:   string;
}

export interface OutboundPayload {
  agentId: string; channelId: string;
  content: string; timestamp: number; reason: string;
}

type PayloadGenerator = () => Promise<string | null>;

export class HeartbeatRunner extends EventEmitter {
  private config:          HeartbeatConfig;
  private timer:           ReturnType<typeof setTimeout> | null = null;
  private generatePayload: PayloadGenerator;
  private tickCount = 0;

  constructor(config: HeartbeatConfig, generatePayload: PayloadGenerator) {
    super();
    this.config = config; this.generatePayload = generatePayload;
  }

  start(): void {
    console.log(
      `[Heartbeat] started — interval=${this.config.intervalMs}ms` +
      ` tz=${this.config.activeHours.timezone}` +
      ` hours=${this.config.activeHours.weekdays.start}:00-` +
      `${this.config.activeHours.weekdays.end}:00`
    );
    this.scheduleNext();
  }

  stop(): void {
    if (this.timer !== null) { clearTimeout(this.timer); this.timer = null; }
    console.log("[Heartbeat] stopped");
  }

  private scheduleNext(): void {
    this.timer = setTimeout(() => {
      void this.onTick().finally(() => this.scheduleNext());
    }, this.config.intervalMs);
  }

  private async onTick(): Promise<void> {
    this.tickCount += 1;
    const id = `tick#${this.tickCount}`;

    // 扩展点 1：active-hours 门控
    if (!isActiveHours(this.config.activeHours)) {
      console.log(`[Heartbeat] ${id} — outside active hours, skipping`);
      this.emit("tick", true);
      return;
    }

    // 扩展点 2：调用注入的内容生成器
    let content: string | null = null;
    try {
      content = await this.generatePayload();
    } catch (err) {
      console.error(`[Heartbeat] ${id} — generator failed:`, err);
    }

    if (!content) {
      console.log(`[Heartbeat] ${id} — no content, skipping`);
      this.emit("tick", false);
      return;
    }

    // 扩展点 3：emit outbound，调用方决定通过哪个 channel 推送
    const payload: OutboundPayload = {
      agentId: this.config.agentId, channelId: this.config.channelId,
      content, timestamp: Date.now(), reason: id,
    };
    console.log(`[Heartbeat] ${id} — emitting outbound`);
    this.emit("outbound", payload);
    this.emit("tick", false);
  }
}
```

中间验证：监听 `runner.on("outbound", p => console.log("got outbound:", p.content))`，把 `intervalMs` 改成 `3000`，3 秒后应该看到 outbound 事件打印（确保当前时间在 activeHours 范围内）。如果看到 "outside active hours"，把 `start` 降低到当前小时或更低。

**Python 版完整 HeartbeatRunner**（asyncio 实现，逻辑与 TypeScript 版完全对应）：

```python
# heartbeat_runner.py — 完整 HeartbeatRunner（Python asyncio 版）
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

from active_hours import ActiveHoursConfig, is_active_hours

@dataclass
class OutboundPayload:
    agent_id: str
    channel_id: str
    content: str
    timestamp: float   # Unix timestamp（秒）
    reason: str        # 触发原因，如 "tick#3"，方便事后追溯

# 内容生成器：返回 None 表示本次无内容，节拍静默跳过
PayloadGenerator = Callable[[], Awaitable[str | None]]

@dataclass
class HeartbeatRunnerConfig:
    interval_sec: float
    active_hours: ActiveHoursConfig
    agent_id: str
    channel_id: str

class HeartbeatRunner:
    def __init__(self, cfg: HeartbeatRunnerConfig, generate: PayloadGenerator) -> None:
        self._cfg = cfg
        self._generate = generate
        self._tick_count = 0
        self._task: asyncio.Task | None = None
        self._outbound_handlers: list[Callable[[OutboundPayload], Awaitable[None]]] = []

    def on_outbound(self, fn: Callable[[OutboundPayload], Awaitable[None]]) -> None:
        self._outbound_handlers.append(fn)

    def start(self) -> None:
        cfg = self._cfg
        print(
            f"[Heartbeat] started — interval={cfg.interval_sec}s "
            f"tz={cfg.active_hours.timezone} "
            f"hours={cfg.active_hours.weekday_start}:00-{cfg.active_hours.weekday_end}:00"
        )
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
        print("[Heartbeat] stopped")

    async def _run(self) -> None:
        while True:
            await self._on_tick()
            await asyncio.sleep(self._cfg.interval_sec)  # tick 完成后再等，防重叠

    async def _on_tick(self) -> None:
        self._tick_count += 1
        tick_id = f"tick#{self._tick_count}"

        # 扩展点 1：active-hours 门控
        if not is_active_hours(self._cfg.active_hours):
            print(f"[Heartbeat] {tick_id} — outside active hours, skipping")
            return

        # 扩展点 2：调用注入的内容生成器；异常只记录，不重新抛出
        content: str | None = None
        try:
            content = await self._generate()
        except Exception as exc:
            print(f"[Heartbeat] {tick_id} — generator failed: {exc}")

        if not content:
            print(f"[Heartbeat] {tick_id} — no content, skipping")
            return

        # 扩展点 3：触发 outbound，调用方决定通过哪个 channel 推送
        payload = OutboundPayload(
            agent_id=self._cfg.agent_id,
            channel_id=self._cfg.channel_id,
            content=content,
            timestamp=time.time(),
            reason=tick_id,
        )
        print(f"[Heartbeat] {tick_id} — emitting outbound")
        for fn in self._outbound_handlers:
            await fn(payload)
```

中间验证：把 `interval_sec=3`、`weekday_start=0`、`weekday_end=24`，启动后 3 秒应看到 `tick#1 — emitting outbound` 和处理器打印。

注意 `_on_tick()` 里的错误处理策略：`generatePayload()` 抛出异常时我们只记录日志，**不重新抛出**。这是有意为之的设计：Heartbeat 是一个持续运行的后台系统，单次内容生成失败不应该让整个节拍器崩溃。丢一次节拍比整个系统停止要好。这和 `finally(() => this.scheduleNext())` 的设计一致——无论 `onTick()` 成功还是失败，下一次节拍都会按时调度。

**第三步扩展：独立告警通道（Watchdog 模式）**

```typescript
// alert-channel.ts — 独立类，零依赖主 agent 任何模块
// 指数退避防止单次故障导致 Telegram 刷屏：
//   第 1 次失败 → 1 分钟后告警
//   第 2 次失败 → 5 分钟后告警
//   第 3 次失败 → 15 分钟后告警
//   之后每小时一次（不再加密）
const BACKOFF_MS = [60_000, 300_000, 900_000, 1_800_000, 3_600_000] as const;

export class AlertChannel {
  private states = new Map<string, { count: number; lastAt: number }>();

  constructor(private botToken: string, private chatId: string) {}

  shouldAlert(checkId: string): boolean {
    const s    = this.states.get(checkId) ?? { count: 0, lastAt: 0 };
    const wait = BACKOFF_MS[Math.min(s.count, BACKOFF_MS.length - 1)];
    if (Date.now() - s.lastAt >= wait) {
      this.states.set(checkId, { count: s.count + 1, lastAt: Date.now() });
      return true;
    }
    return false;
  }

  resetAlert(checkId: string): void { this.states.delete(checkId); }

  async send(msg: string): Promise<void> {
    // 独立 HTTPS 调用，不走 OpenClaw gateway，不依赖任何 agent 模块
    // 实现见 lena-v0.17/src/heartbeat/alert-channel.ts
  }
}
```

中间验证：`alert.shouldAlert("test")` 第 1 次返回 `true`，立刻再调 4 次全都返回 `false`（退避时间未到）。60 秒后再调返回 `true`（第 2 次告警，但已进入下一档退避，需等 5 分钟）。

**Python 版 AlertChannel**（零依赖，只用标准库 `urllib`）：

```python
# alert_channel.py — 独立告警通道（Python 版）
# 零依赖：只用标准库 urllib，不引用任何 agent 模块
import json
import time
import urllib.request
from dataclasses import dataclass, field

# 指数退避梯度（秒）：60s → 5min → 15min → 30min → 1h
BACKOFF_SECS = [60, 300, 900, 1800, 3600]

@dataclass
class _AlertState:
    count: int = 0
    last_at: float = 0.0

class AlertChannel:
    """独立告警通道：不依赖主 agent 任何代码路径，直连 Telegram API。"""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._states: dict[str, _AlertState] = {}

    def should_alert(self, check_id: str) -> bool:
        """判断是否到了应发告警的时间（指数退避）。"""
        s = self._states.setdefault(check_id, _AlertState())
        wait = BACKOFF_SECS[min(s.count, len(BACKOFF_SECS) - 1)]
        if time.time() - s.last_at >= wait:
            s.count += 1
            s.last_at = time.time()
            return True
        return False

    def reset_alert(self, check_id: str) -> None:
        self._states.pop(check_id, None)

    def send(self, msg: str) -> None:
        """同步发送 Telegram 消息（直连 API，不走任何 agent gateway）。"""
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        body = json.dumps({"chat_id": self._chat_id, "text": msg}).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[AlertChannel] sent, status={resp.status}")
```

---

## Beat 6 — 运行验证

下面把所有模块组装成可运行的 `lena-v0.17`，每天 08:00 自动推送晨报。

```typescript
// agent.ts — 完整入口（精简版，完整版见 lena-v0.17/src/agent.ts）
import { HeartbeatRunner, OutboundPayload } from "./heartbeat/index.js";
import https from "https";
import fs    from "fs";

const config = JSON.parse(fs.readFileSync("config.json", "utf-8"));

// 早报生成器：当前版本返回简单问候
// 生产扩展：这里接入 Anthropic API，拉取日历/新闻后生成摘要
async function generateBriefing(): Promise<string | null> {
  const d = new Date().toLocaleDateString("zh-CN",
    { year: "numeric", month: "long", day: "numeric", weekday: "long" });
  return `早上好！今天是 ${d}。\n\n有什么需要我帮忙的吗？`;
}

const runner = new HeartbeatRunner(
  {
    intervalMs:  config.heartbeat.intervalMs,
    activeHours: config.heartbeat.activeHours,
    agentId:     "lena",
    channelId:   "telegram",
  },
  generateBriefing,
);

runner.on("outbound", async (payload: OutboundPayload) => {
  // 直接调用 Telegram HTTP API，不走任何 agent gateway
  const body = JSON.stringify({
    chat_id: config.telegram.chatId,
    text:    payload.content,
    parse_mode: "Markdown",
  });
  // ... HTTPS POST 到 api.telegram.org ...
  console.log(`[Lena] heartbeat sent at ${new Date().toISOString()}`);
});

runner.start();
process.on("SIGINT", () => { runner.stop(); process.exit(0); });
```

**运行步骤**：

```bash
cd book/chapters/ch17-heartbeat/code/lena-v0.17
npm install

# 必须：配置 Telegram bot token（用 @BotFather 创建）
# 在 config.json 填入 botToken 和 chatId

# 测试技巧：改 config.json 让触发时间更短
# "intervalMs": 10000      ← 10 秒触发一次
# "weekdays": { "start": 0, "end": 24 }  ← 全天 active

npm run dev
```

**预期输出**（约 10 秒后）：

```
[Heartbeat] started — interval=10000ms tz=Asia/Shanghai hours=0:00-24:00
[Heartbeat] tick#1 — active, generating payload...
[Heartbeat] tick#1 — emitting outbound
[Telegram] sent (status=200)
[Lena] heartbeat sent at 2026-05-05T08:00:01.234Z
[Heartbeat] tick#2 — active, generating payload...
```

Telegram 手机上收到：

```
早上好！今天是 2026年5月5日，星期二。

有什么需要我帮忙的吗？
```

**常见失败诊断**：

- `tick#1 — outside active hours, skipping` — 当前小时不在 `weekdays.start-end` 范围内。测试时把 `start` 改成 `0`，`end` 改成 `24`
- `[Telegram] sent (status=401)` — `botToken` 错误，用 `@BotFather` 的 `/token` 命令重新获取
- `ECONNREFUSED` 或 `ETIMEDOUT` — 网络问题，检查是否需要代理（国内服务器连 `api.telegram.org` 可能需要）
- 10 秒后什么都不打印 — 检查 `tsconfig.json` 是否存在，`npm run dev` 是否依赖 `tsx`（`npm install` 是否成功）

恢复生产配置：把 `intervalMs` 改回 `3_600_000`（1 小时），`weekdays` 改回 `{ start: 8, end: 22 }`。Heartbeat 每小时唤醒一次检查，第一个落在 08:00 窗口内的节拍发出早报。

**失败率的现实预期**

这是不诚实标注的正确位置：以上例子是最佳情况。实际运行中，常见失败模式有：

1. **Telegram API 偶发 429**（请求频率限制）：Heartbeat 每小时最多发一次，在正常配置下不会触发，但如果你有多个 agent 共享同一 bot token 就会有问题
2. **LLM 调用超时**：内容生成器调用 Anthropic API，如果网络抖动超时 30 秒，这次节拍会静默跳过（因为我们用了 `generatePayload()` 捕获异常），用户收不到这小时的推送
3. **内容生成器总返回 null**：如果 `generateBriefing()` 里的逻辑有 bug 一直返回 null，Heartbeat 会持续运行但永远不发消息——你需要监控 `tick` 事件的 skipped 比率来发现这类问题

这些失败模式不影响 Heartbeat 的节拍器本身继续运行，只影响具体某次推送。这是"优雅降级"的体现：单点失败不级联。

下一章，我们给 Lena 加上 Cron——Heartbeat 管"主动打招呼"，Cron 管"定时执行具体任务并汇报结果"。两者共同构成 always-on agent 的时间感知体系：Heartbeat 是"我有话说"的触发器，Cron 是"我有任务要做"的调度器。

---

## Beat 7 — Design Note

> **Why Must the Alert Channel Be Independent of the Main Agent?**

第一直觉是让 Watchdog 通过 Lena 的主推送 API 发告警。这样只需要维护一套 bot、一套 token，代码最少。这是符合直觉的做法，大多数人会在第一次构建时这样做。

这条路有一个结构性缺陷，tradeoff 如下：

- 🟢 优势：实现简单，只有一个 bot token 需要管理，所有消息从同一入口出
- 🔴 问题一：**主 agent 崩溃时，告警通道也一起崩溃**。"OpenClaw 挂了"这条告警需要通过 OpenClaw 发出——逻辑上不可能。这不是一个可以靠重试解决的问题，根因是告警路径依赖了被告警对象
- 🔴 问题二：**网络分区时两者同时丢失**。如果 gateway 端口不可达，正常消息和告警消息一起丢失，外部看到的是完全沉默——比收到告警更糟糕
- 🔴 问题三：**单点升级风险**。主 agent 在部署新版本时有几分钟的停机窗口，这段时间内的告警会丢失

独立告警通道的最小要求：

1. **独立进程或独立类**：不引用主 agent 的任何模块（特别是 gateway、session、channel 系统）
2. **独立 bot token**：另一个 Telegram bot，@BotFather 创建一个 `lena_watchdog_bot`
3. **最小依赖**：只需要操作系统级网络调用（Node.js 内置 `https` 模块或 Python 的 `urllib`），不依赖任何第三方库
4. **单一职责**：只做一件事——发 Telegram 消息。不做日志、不做数据库写入、不做状态管理

这个模式在生产系统里有一个名字：**Out-of-band alerting**（带外告警）。"带外"的含义是：告警信号走的通道，独立于被监控系统的主数据通道。

如果在规模更大的生产系统里，还会进一步把独立告警通道部署在不同的机器（或不同的云区域）上，这样能抵御整机宕机或单可用区故障的场景。但这是"可以更好"而不是"必须要做"——`lena-v0.17` 里的 `AlertChannel` 是这个模式在个人项目级别的最小正确实现：一个 standalone 类，不共享任何主 agent 代码路径，只有 `botToken`、`chatId`，以及一个 `send()` 方法。

这个设计在实际系统里有一个具体的副产品：你需要维护两个 Telegram bot。这是一点额外的运维复杂度，但它换来的是"主 agent 挂了你一定知道"这条确定性保证——在生产环境里，这是值得的。

---

## 附录：OpenClaw 生产级 Heartbeat 的 4 子模块

> 本节供深入研究。日常开发用上面的 178 行版本即可。

nano-claw 178 行只回答了"何时触发"（active-hours）和"是否推送"（content null 检查）两个问题，而且回答的是最简版本。OpenClaw 的 `heartbeat-runner.ts` 由 4 个子模块协同，对三个问题都给出了生产级答案：

```
heartbeat-runner.ts（主控制器）
    │
    ├── heartbeat-active-hours.ts    → 何时触发？（精细到分钟）
    │       • IANA timezone 感知
    │       • start/end 精确到 HH:MM（不只是整数小时）
    │       • 支持 24:00 跨午夜配置（如 22:00 - 02:00）
    │       关键：用 Intl.DateTimeFormat 换算"目标时区当前分钟数"
    │       (openclaw/src/infra/heartbeat-active-hours.ts)
    │
    ├── heartbeat-events-filter.ts   → 这次 beat 的原因是什么？
    │       • 区分四种触发类型：
    │         - interval：定时节拍（普通 Heartbeat）
    │         - exec-event：后台任务完成通知
    │         - cron：计划任务触发
    │         - wake：手动唤醒（开发调试用）
    │       • 不同 reason 对应不同 prompt 模板
    │       • exec-event 会把任务执行结果注入 prompt，让 LLM 汇报给用户
    │
    ├── heartbeat-visibility.ts      → 用户现在能收到吗？
    │       三种可见性模式：
    │       - showAlerts：发真实内容（用户可接受推送）
    │       - showOk：只发 HEARTBEAT_OK token（静默心跳包）
    │       - useIndicator：发无声指示器（channel 支持时）
    │       应用场景：用户设置了 DND、或 channel 检测到用户离线
    │
    └── heartbeat-reason.ts          → 为什么这条消息被发出？（可追溯性）
            记录每条推送的触发 reason kind
            用途：24 小时后 debug "为什么昨天 08:03 那条消息被发出"
```

**一个值得单独关注的设计：transcript prune**

OpenClaw `heartbeat-runner.ts` 里有一个对教学有价值的细节：当 beat 判断为 `HEARTBEAT_OK`（LLM 认为没有实质内容，只返回了一个 ok token）时，代码会通过 `pruneHeartbeatTranscript()` 把这次交互从会话历史里截断。

```
// 伪代码展示 transcript prune 的逻辑
const preSize = await captureTranscriptState(sessionKey);  // 记录文件的当前字节大小
const reply   = await getReplyFromLLM(heartbeatPrompt);    // 调用 LLM

if (reply.isHeartbeatOK) {
  await pruneTranscript(preSize);  // 用 fs.truncate() 截断到调用前的大小，移除这次交互
  return { status: "ok-empty" };
}
// 有实质内容时，正常写入历史，推送给用户
```

为什么需要截断？

一个生产级 agent 每天可能触发 24 次 Heartbeat（1 小时一次）。如果每次都写进会话历史，一周后 context window 里有 168 条"我没什么可说的"对话记录。这会导致两个问题：

- **Context 污染**：LLM 每次对话都要"读过"这些空洞的历史，可能影响对"现在有没有事情"的判断（见过太多"没事"的上下文，容易继续回答"没事"）
- **Context Window 占满**：168 条记录可能消耗数千 token，把有价值的历史（用户昨天的请求、上周的任务完成记录）推出窗口

截断的实现很简单：记录文件大小 → 执行 LLM 调用 → 如果结果是 ok，用 `fs.truncate()` 把文件缩回原来的大小。这是一个文件系统级的"撤销"操作。

截断是必须的，不是可选的优化。nano-claw 178 行版本没有这个机制，因为教学用途下会话历史量有限，但如果你把 lena-v0.17 跑满一个月，就会感受到为什么需要这个设计。

**Dedupe：防止相同内容重复推送**

OpenClaw 还有一个 dedupe 机制：如果当前生成的 Heartbeat 内容和 24 小时内最近一次推送的内容完全相同，就静默跳过。

这解决了一个实际问题：如果用户每天的早报都是"今天没什么特别的事"，LLM 每次生成的内容几乎完全一样。没有 dedupe 时，用户会每天收到 24 条格式完全相同的消息（每小时一条，每条都说"今天没什么"）。有了 dedupe 后，相同内容只发一次，用户收到的是"最近一次值得关注的更新"，而不是噪音的轰炸。

Dedupe 的判断条件（来自 `heartbeat-runner.ts`）：
```
isDuplicate =
  normalized.text.trim() === prevHeartbeatText.trim()  // 内容完全相同
  && startedAt - prevHeartbeatAt < 24 * 60 * 60 * 1000 // 且在 24 小时内
  && !mediaUrls.length                                  // 且没有附件（图片/文件不去重）
```

**4 子模块 vs 178 行的选型建议**：

| 维度 | nano-claw 178 行 | OpenClaw 4 子模块 |
|------|-----------------|-----------------|
| 适用场景 | 个人项目、单 channel、单 agent | 多 agent、多 channel、审计需求 |
| 代码量 | 178 行（1 个文件） | ~600 行（4 个文件） |
| 时间精度 | 整数小时 | 精确到分钟 |
| 触发原因区分 | 无（只有 interval） | interval / exec-event / cron / wake |
| Transcript 管理 | 无（每次 beat 都写进历史） | pruneHeartbeatTranscript 防 context 污染 |
| 调试友度 | console.log | reason 链路 + 结构化事件日志 |

个人项目和原型用 178 行版本——够用，清晰，易懂。多团队、多 channel、需要 audit trail 的系统用 4 子模块。不要"以防万用"地直接用 OpenClaw 版本——4 子模块的配置复杂度会让你的项目维护成本翻倍，而你可能根本用不到 visibility 和 reason 子模块。

这是一个通用的工程原则：先用最简方案满足当前需求，当需求增长到最简方案的边界时，再升级到下一层复杂度。Heartbeat 的设计阶梯就是这么构建出来的——nano-claw 178 行是"当前需求"的答案，OpenClaw 4 子模块是"多 agent / 多 channel / 审计"需求的答案，两者不是同一个问题的好答案和差答案，而是不同问题的各自正确答案。
