# 第 22 章：可观测性与部署——让 Lena 上线 7×24

> **[支柱：Long-horizon 执行 / Transparency / Safety]**

---

## Beat 1 — 路线图

```
Ch1  Ch3  Ch6  Ch8  Ch11  Ch15  Ch17  Ch18  Ch21  ▶ Ch22 ← 你在这里
基础 工具 安全 记忆  Planning  Gateway  Cron  Budget  Evals  可观测性+部署
                                                              ↓
                                                          Lena v0.22
                                                       (可在生产持续运行)
```

Lena 在前 21 章里学会了工具调用、子任务拆分、定时任务、安全护栏。但她还活在开发机上——你关了终端她就消失，你不知道她是否悄悄挂了，你也不知道她这周替你花了多少钱。

本章从三个症状出发 → 经过结构化日志 + OpenTelemetry + Budget 状态机 → 到 systemd / launchd / Docker 三种部署，途中会遇到一个反直觉的设计决策：**cost 监控为什么必须前置熔断而不是事后报警**。

章末 Lena 版本从 v0.21 升级到 v0.22，新增四个生产能力：
1. 每次 LLM 调用都有结构化日志 + OTel span，可用 jq 和 Jaeger 回放任意历史决策
2. 日预算四状态机，超预算自动限速，不炸账单
3. 三份部署文件，一条命令让 Lena 重启机器后自动复活
4. 两个 Hooks 示例，把 ruff lint 和 Stop 通知接进 Claude Code 自动化流程

> **🧠 聪明度增量（v0.21 → v0.22）**：Lena 第一次可观测——结构化日志 + OTel span + 日预算四状态机让每次 LLM 调用都可追踪，cost 前置熔断防止死循环炸账单，systemd/launchd 部署让她重启机器后自动复活。这一章教读者把生产级可观测性长在自己 agent 上的方法。

---

## Beat 2 — 动机

没有可观测性的 agent 上线，是把盲人派去驾驶飞机。

具体症状如下。

**症状一：三天后你不知道发生了什么。**

```python
# 现在 Lena 的日志（BAD）
print(f"LLM 回复：{reply[:50]}...")
print(f"工具执行：{tool_name}")
```

这两行在你盯着终端看时还凑合。三天后你想排查"上周五凌晨那次任务为什么失败"，你翻日志文件——是一堆无结构的纯文本。`grep` 找不到关联，`jq` 不认识，你只能肉眼读，10 分钟过去了还没定位。

对比结构化日志之后：`jq 'select(.event=="tool_fail" and .timestamp>"2026-05-09")' lena.log` ——0.3 秒出结果。

**症状二：你不知道 Lena 花了多少钱。**

一个死循环 bug（比如循环变量没清零，agent 无限重试同一个失败动作）在没有预算熔断的情况下，24 小时内可以产生 $40-$80 的 Bedrock 费用，全是同一条错误消息的重复。事后账单告警已经晚了。

真实情况是：**当你发现告警时，钱已经花出去了。** 预算熔断必须在调用 LLM 之前检查，而不是在账单到达之后。

**症状三：你关了终端 Lena 就死了。**

开发阶段可以接受 `python3 main.py` 跑着。生产环境不行。你需要 Lena 在你睡着时继续执行定时任务，在机器重启后自动恢复，在崩溃后自动重新拉起——这需要进程守护，而不是一个挂在 shell 里的进程。

---

## Beat 3 — 理论铺垫

### 3.1 Agent 的可观测性为什么和传统服务不同

传统 Web 服务的请求-响应是确定性的：同样的输入，同样的输出，日志主要用于排错。

Agent 的执行有三个显著不同：

**长尾延迟**：一次 agent 会话可能包含 3 次 LLM 调用 + 12 次工具调用，总耗时从 2 秒到 20 分钟不等。传统的 P99 延迟指标对 agent 没什么意义，你需要追踪的是**每步的决策链**——第几次 LLM 调用、用了什么工具、耗时多少、token 花了多少。

**非确定性输出**：同样的 system prompt + user input，因为模型随机性，Lena 今天选择工具 A，明天选择工具 B，后天两个都用。这意味着你无法像传统服务那样用"预期输出"来判断正确性——你需要追踪的是**意图与行为的一致性**，不是输出是否精确匹配。

**成本是变量**：一次 Web 请求的服务器成本是微秒级计算，可以忽略。一次 agent 任务的 LLM 调用成本从 $0.001 到 $0.5 不等，取决于任务复杂度。这让成本监控成为 agent 可观测性的一等公民，而不是事后统计。

Convention：**Trace** = 一次完整的用户请求，有唯一 `trace_id`；**Span** = 一次具体操作（如一次 LLM 调用），有开始/结束时间和父子关系，挂在 Trace 下；**Log** = 单个时间点的事件快照，通过 `trace_id` / `span_id` 关联到 Trace。

这三者不是可以二选一的替代方案：Log 告诉你"发生了什么"，Span 告诉你"花了多长时间"，Trace 告诉你"整体调用链是什么样的"。生产 agent 需要三者同时在场。

### 3.2 为什么 cost 熔断必须前置

这是一个在传统 Web 服务里没有对应概念的设计模式。

事后报警的逻辑是：花完钱 → 账单推送 → 收到告警 → 手动停止。这个链路有两个根本缺陷：

1. **时间差**：云平台账单报警的延迟通常是小时级。一个死循环 agent 在 1 小时内就能花掉$20+，等告警到的时候损失已经发生了。
2. **无法自愈**：告警通知的是人，人需要手动登录、找到进程、kill 掉。agent 的设计目标是自主运行，这和"需要人工介入才能停止"是矛盾的。

前置熔断的设计是：在每次调用 LLM 之前检查预算状态——如果已经超过阈值，当场拒绝调用，agent 自动停止或限速。这是 agent 自治的一部分：它不仅需要知道"能做什么"，还需要知道"现在能花多少"。

nanoClaw（`nanoclaw/security/budget.py`）采用的是迭代计数 + token 计数的双维度熔断；本章的 Lena v0.22 在此基础上增加了日美元预算的第三维度，并引入四状态机（OK → WARN → THROTTLE → STOP），让熔断动作有渐进性而不是突然硬停。

> 引用：nanoClaw `budget.py`（`SessionBudget.check_iteration()`，第 84 行）采用的是静态阈值硬停；Lena v0.22 的改进是引入 THROTTLE 状态，让 agent 在 90% 预算时先降速，而不是直接停止，减少对正在进行任务的干扰。这不是解决方案，而是在"可用性"和"成本控制"之间做了一个务实权衡——如果你的场景是实验性任务，硬停反而更简单。

### 3.3 进程守护的三种姿势

Convention：**launchd** = macOS 的原生进程管理器，以 plist XML 配置，随用户登录启动；**systemd** = Linux 的标准进程管理器，以 .service INI 配置，随系统启动；**Docker** = 容器运行时，用 Dockerfile 描述环境、用 `docker-compose.yml` 描述服务依赖关系。

三者不是竞争关系，而是适用不同场景：Mac 个人开发机用 launchd，Linux 服务器用 systemd，多服务组合部署用 Docker Compose。

一个共同的陷阱是**重启风暴**：如果进程启动即崩溃，守护程序会以极高频率反复重启，触发平台保护机制，导致进程被永久停止而没有任何告警。launchd 用 `ThrottleInterval` 控制，systemd 用 `StartLimitBurst` 控制，两者都需要显式配置。

---

## Beat 4 — 脚手架

下面先给 Lena 核心循环加上结构化日志，构建最小可观测骨架：

```python
# code/lena-v0.22/src/observability/logger.py
"""结构化日志配置。

Convention：
  - 开发模式：ConsoleRenderer（彩色可读）
  - 生产模式：JSONRenderer（每行一个 JSON，可被 jq / CloudWatch / ELK 直接处理）
"""
import logging
import sys

import structlog  # pip install structlog>=24.0


def setup_logging(
    level: str = "INFO",
    json_output: bool = False,  # 默认开发模式，生产传 True
) -> None:
    """初始化结构化日志。调用一次，全局生效。"""
    shared_processors = [
        structlog.stdlib.add_log_level,           # 注入 level 字段
        structlog.stdlib.add_logger_name,         # 注入 logger 字段
        structlog.processors.TimeStamper(fmt="iso"),  # ISO 8601 时间戳
        structlog.processors.StackInfoRenderer(), # 异常堆栈
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


# 用法：任何模块 import 后直接使用
# logger = structlog.get_logger(__name__)
# logger.info("llm_call", model="claude-sonnet-4-6", input_tokens=4230)
```

运行 `setup_logging(json_output=True)` 后，每条日志输出类似：

```json
{"event": "llm_call", "model": "claude-sonnet-4-6", "input_tokens": 4230,
 "level": "info", "timestamp": "2026-05-22T03:12:04Z", "logger": "lena.core"}
```

接下来我们在这个骨架上加入 OTel span 和 Budget 门控。

---

## Beat 5 — 渐进组装

### 扩展表

| 扩展点 | 为何需要 | 如何加 |
|--------|----------|--------|
| OTel span 包裹 LLM 调用 | 看完整调用链耗时，定位瓶颈 | `with tracer.start_as_current_span("llm_call") as span` |
| Budget 状态机 | 前置熔断，防账单爆炸 | 调 LLM 前 `await budget.check_and_wait()` |
| Stop Hook 通知 | Lena 停止时通过 Discord 告知 | `hooks/notify_stop.py` 读 stdin JSON |
| PostToolUse Hook lint | 每次写 Python 文件自动 ruff 检查 | `hooks/lint_on_write.py` |

### 扩展 1：OTel span 追踪

下面把 LLM 调用包裹在 OpenTelemetry span 里，验证完整调用链：

```python
# code/lena-v0.22/src/observability/tracing.py
"""OpenTelemetry 接入。

选型说明：OTLP exporter 支持 Jaeger/Tempo/Honeycomb/X-Ray，
换后端只改一行 endpoint，不改业务代码。
"""
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource


def setup_tracing(
    service_name: str = "lena",
    otlp_endpoint: str = "http://localhost:4317",  # 本地 Jaeger
) -> trace.Tracer:
    """初始化 tracer，导出到 OTLP。

    本地开发：docker run -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one
    生产迁移：改 endpoint 到 AWS X-Ray ADOT collector（其余不变）
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

中间验证：启动 Jaeger（`docker run -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one`），运行 Lena 发一条消息，打开 `http://localhost:16686`，应看到服务名 `lena` 下有 trace 记录，每次 LLM 调用是一个 span，含 `input_tokens` / `output_tokens` / `latency_ms` 三个 attribute。

### 扩展 2：Budget 四状态机

```python
# code/lena-v0.22/src/budget/budget_controller.py
"""日预算四状态机。

四个状态：
  NORMAL   (0-80%)   — 正常运行
  WARNING  (80-90%)  — 记录告警日志，但不减速
  THROTTLE (90-100%) — 每次调用前 sleep 2s，主动降速
  STOPPED  (≥100%)   — 拒绝调用，返回 False

为什么四状态而不是二状态（正常/停止）？
  THROTTLE 状态给正在进行的长任务一个"优雅降速"窗口，
  而不是在任务进行到一半时突然切断。这是在成本控制和任务可用性之间的务实权衡。
  对于纯实验性场景，可以把 throttle_pct 设等于 1.0 退化为二状态。
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
    daily_usd: float = 5.0           # 日预算 $5，可按需调大
    warn_pct: float = 0.80           # 80% → WARNING
    throttle_pct: float = 0.90       # 90% → THROTTLE
    throttle_delay_sec: float = 2.0  # THROTTLE 时每次调用延迟


@dataclass
class BudgetController:
    config: BudgetConfig = field(default_factory=BudgetConfig)
    _spent_usd: float = 0.0
    _date: date = field(default_factory=date.today)
    _state_change_callbacks: list[Callable[[BudgetState], None]] = field(
        default_factory=list
    )

    def _reset_if_new_day(self) -> None:
        """午夜自动重置——日预算是日历天，不是滚动窗口。"""
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
        """LLM 调用前的预算门控。

        返回 False 表示已到达上限，调用方不应继续执行。
        THROTTLE 状态下会 sleep 后返回 True（减速但不停止）。
        """
        s = self.state
        if s == BudgetState.STOPPED:
            log.warning(
                "budget_stopped",
                spent_usd=self._spent_usd,
                limit_usd=self.config.daily_usd,
                msg="已达日预算上限，拒绝 LLM 调用",
            )
            return False
        if s == BudgetState.THROTTLE:
            log.info("budget_throttle", delay_sec=self.config.throttle_delay_sec)
            await asyncio.sleep(self.config.throttle_delay_sec)
        return True

    def record_cost(self, usd: float) -> None:
        """每次 LLM 调用完成后记录实际费用，检查状态是否跃迁。"""
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
        """注册状态跃迁回调（可用于发 Telegram 告警）。"""
        self._state_change_callbacks.append(callback)

    @property
    def usage_pct(self) -> float:
        self._reset_if_new_day()
        return round(self._spent_usd / self.config.daily_usd, 4)
```

中间验证：

```python
import asyncio
from lena.budget.budget_controller import BudgetConfig, BudgetController

cfg = BudgetConfig(daily_usd=1.0, warn_pct=0.5, throttle_pct=0.8)
bc = BudgetController(config=cfg)
bc.record_cost(0.55)  # 触发 WARNING
print(bc.state)       # BudgetState.WARNING
bc.record_cost(0.30)  # 触发 THROTTLE
print(bc.state)       # BudgetState.THROTTLE
bc.record_cost(0.20)  # 触发 STOPPED
print(bc.state)       # BudgetState.STOPPED

# 预期输出（通过 structlog console renderer）：
# [warning] budget_state_change from_state=normal to_state=warning spent_usd=0.55 daily_limit=1.0
# [warning] budget_state_change from_state=warning to_state=throttle spent_usd=0.85 daily_limit=1.0
# [warning] budget_state_change from_state=throttle to_state=stopped spent_usd=1.05 daily_limit=1.0
```

### 扩展 3：将 Budget 接入 Agent Loop

```python
# code/lena-v0.22/src/core/agent_loop.py （关键修改，非完整文件）
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
        # Budget 门控：调用 LLM 前检查
        allowed = await self.budget.check_and_wait()
        if not allowed:
            log.warning("step_blocked_by_budget")
            return None  # 调用方决定是否重试或停止

        self.messages.append({"role": "user", "content": user_input})

        with tracer.start_as_current_span("llm_call") as span:
            span.set_attribute("input_messages", len(self.messages))
            resp = await self._call_llm()
            span.set_attribute("input_tokens", resp.usage.input_tokens)
            span.set_attribute("output_tokens", resp.usage.output_tokens)

        # 记录实际成本（Sonnet 4.6：$3/1M input + $15/1M output）
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

中间验证：运行一条对话，`jq '.cost_usd' lena.log | paste -sd+ | bc` 应该能算出当天累计费用。

### 扩展 4：Claude Code Hooks

Claude Code 的 Hook 机制（`utils/hooks.ts:85`）在 14 个生命周期节点插入外部命令。机制：`child_process.spawn()` 启动命令，JSON 通过 stdin 传入，stdout 返回 `{"decision": "approve"|"block", "reason": "..."}` 或 `{"blockingErrors": [...]}` 控制 agent 行为。

14 种事件按触发时机分为五类：

```
工具生命周期  PreToolUse / PostToolUse / PostToolUseFailure
会话生命周期  SessionStart / Setup / Stop / StopFailure
子代理生命周期  SubagentStart / SubagentStop
用户交互    UserPromptSubmit / Notification
环境变化    InstructionsLoaded / FileChanged / CwdChanged
```

Convention：**PreToolUse** = 工具执行前，可以返回 `"block"` 阻止执行；**PostToolUse** = 工具执行成功后，可以触发副作用（lint、埋点）但不能撤回执行；**Stop** = agent loop 正常退出时，返回 `{"blockingErrors": [...]}` 可以让 loop 继续而不退出。

两个最实用的 hook 示例：

**Hook A：PostToolUse — ruff 自动 lint**

```json
// .claude/settings.json（项目级）
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
"""PostToolUse hook：每次 Write 工具写 .py 文件后自动 ruff check。

如果 ruff 报错，向 Claude Code 返回 block + 错误原因，让 agent 修复再重试。
这不是强制门控，是"给 agent 自动修复机会"的反馈循环。
"""
import json
import subprocess
import sys


def main() -> None:
    data = json.loads(sys.stdin.read())
    file_path = data.get("tool_input", {}).get("file_path", "")

    if not file_path.endswith(".py"):
        # 非 Python 文件，直接放行
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
            "reason": f"Ruff lint 失败，请修复后再提交：\n{result.stdout[:500]}",
        }))
    else:
        print(json.dumps({"decision": "approve"}))


if __name__ == "__main__":
    main()
```

**Hook B：Stop — Discord 通知**

```python
# code/lena-v0.22/hooks/notify_stop.py
"""Stop hook：agent 正常停止时发 Discord webhook 通知。

Stop hook 返回 {"blockingErrors": [...]} 可以阻止 agent 退出（让 loop 继续）。
这里只做通知，不阻止退出，所以返回 {}。

局限性：Stop hook 在 StopFailure（异常停止）时不触发，
需要配合 StopFailure hook 做独立的异常告警。
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
        msg = f"✅ Lena session `{session_id[:8]}` 完成 | reason: {stop_reason}"
        try:
            httpx.post(webhook_url, json={"content": msg}, timeout=5)
        except Exception:
            pass  # 通知失败不应该阻断 agent 退出

    print(json.dumps({}))  # 空响应 = 允许正常退出


if __name__ == "__main__":
    main()
```

---

## Beat 6 — 运行验证

### 最终产物结构

```
code/lena-v0.22/
├── src/
│   ├── observability/
│   │   ├── logger.py          # structlog 配置
│   │   └── tracing.py         # OTel + Jaeger/X-Ray 接入
│   ├── budget/
│   │   └── budget_controller.py  # 四状态机
│   └── core/
│       └── agent_loop.py      # 集成日志 + OTel + Budget
├── deploy/
│   ├── lena.service           # systemd（Linux）
│   ├── ai.lena.agent.plist    # launchd（macOS）
│   └── docker-compose.yml     # Docker Compose（多服务）
├── hooks/
│   ├── lint_on_write.py       # PostToolUse → ruff
│   └── notify_stop.py         # Stop → Discord
├── Dockerfile
└── requirements.txt
```

### 三份部署文件

**launchd（macOS）**

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
      ThrottleInterval 是防重启风暴的关键。
      不加这个：崩溃 → launchd 立即重启 → 再次崩溃 → 60s 内超 5 次 → 进程永久停止。
      加了之后：每次重启间隔至少 30s，给代码修复时间，也让日志有时间写入。
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
# 首次加载
launchctl load ~/Library/LaunchAgents/ai.lena.agent.plist

# 修改 plist 后必须 unload/load（不是 SIGUSR1，那不刷新环境变量）
launchctl unload ~/Library/LaunchAgents/ai.lena.agent.plist
launchctl load ~/Library/LaunchAgents/ai.lena.agent.plist

# 查看状态（0 = running，非 0 = 上次退出码）
launchctl list | grep lena
```

**systemd（Linux）**

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
EnvironmentFile=/opt/lena/.env  # 敏感值单独文件，不进 git

Restart=on-failure
RestartSec=15s

# StartLimitBurst：5 次崩溃内 300s，超过就停止并发告警
# 触发后手动恢复：systemctl reset-failed lena && systemctl start lena
StartLimitIntervalSec=300
StartLimitBurst=5

MemoryMax=1G
CPUQuota=80%

# 安全加固：进程无法提权，/tmp 私有，/opt/lena 之外只读
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

# 实时日志
sudo journalctl -u lena -f

# JSON 格式（可接 filebeat / fluentd）
sudo journalctl -u lena -o json | jq '.MESSAGE | fromjson? // .'
```

**Docker Compose（多服务）**

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
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317  # Docker Compose 内网服务名，宿主机访问用 localhost:4317
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
      - "16686:16686"  # Jaeger UI（浏览器打开看 trace）
      - "4317:4317"    # OTLP gRPC（Lena 的 OTel exporter 指向这里）
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
# 启动（后台）
docker compose -f deploy/docker-compose.yml up -d

# 检查 Lena 是否在跑
docker compose -f deploy/docker-compose.yml ps

# 实时日志
docker compose -f deploy/docker-compose.yml logs -f lena

# 预期输出：每条 LLM 调用一行 JSON，budget_pct 字段随每次调用递增
```

### 遇到问题排查

**"launchd 停止了进程，`launchctl list` 显示非零退出码"**：通常是 ThrottleInterval 触发，说明进程在短时间内崩溃了多次。先 `launchctl unload` 摘掉 KeepAlive，手动 `python3 src/main.py` 查看实际报错，修复后再 `load`。

**"systemd `systemctl status lena` 显示 `(Result: start-limit-hit)`"**：StartLimitBurst 已触发，运行 `systemctl reset-failed lena` 重置计数器，然后 `systemctl start lena`，同时检查 `journalctl -u lena -n 50` 找崩溃原因。

**"Jaeger UI 看不到 trace"**：先确认 `docker compose ps` 中 jaeger 是 running，再检查 `OTEL_EXPORTER_OTLP_ENDPOINT` 环境变量是否正确设为 `http://jaeger:4317`（Docker 网络内服务名），不是 `localhost:4317`。

**"budget_state_change 日志没有出现"**：检查 `record_cost(usd)` 的 usd 值是否正确计算——如果你用的是 Haiku 而不是 Sonnet，价格参数需要调整（Haiku: $0.25/1M input + $1.25/1M output，比 Sonnet 便宜 10 倍以上）。

---

## §工具调用 Span + Cost 追踪：Agent 专属可观测性

> **[支柱：Transparency / Long-horizon 执行]**

### 为什么 Agent 需要专属 Observability

传统 Web 服务的可观测性三件套——日志（Logs）、指标（Metrics）、追踪（Traces）——是为请求-响应模型设计的。一次请求，一次响应，P99 延迟，错误率。

Agent 的执行模型完全不同，有四个传统 observability 工具看不到的盲区：

**盲区一：工具调用链**。一次 agent 任务包含 N 次 LLM 调用和 M 次工具调用，每次工具调用有独立的延迟和成功/失败状态。传统 APM 只看到"一次 HTTP 请求花了 45 秒"，看不到"第 3 次 LLM 调用之后，`filesystem__read_file` 工具调用失败了，触发了第 4 次 LLM 重试"。

**盲区二：Token 消耗分布**。一次任务的 token 消耗可能极度不均匀——前 3 次 LLM 调用各用 500 tokens，第 4 次因为工具返回了大量数据突然用了 15,000 tokens。不追踪 per-call token 就无法优化 context 管理。

**盲区三：推理链（Reasoning Trace）**。agent 做出某个工具选择的"想法"记录在 LLM 的 text 输出里，不在任何标准 APM 字段里。没有推理链追踪，你无法事后理解"为什么 Lena 选了工具 A 而不是工具 B"。

**盲区四：成本（Cost）**。传统服务成本是固定的 infra 费用，和请求内容无关。Agent 的成本是变量，每次 LLM 调用的成本取决于 token 数量，而 token 数量取决于任务复杂度。不追踪 per-request cost，你不知道哪类任务在"烧钱"。

这四个盲区加在一起，意味着你不能把 Datadog、New Relic 这类传统 APM 工具直接套在 agent 上——你需要专门的 agent observability 层。

### 关键指标：Agent Observability 的最小集合

以下是每个生产 agent 都应该追踪的最小指标集：

| 指标 | 类型 | 字段名 | 说明 |
|------|------|--------|------|
| 工具调用延迟 | Span | `tool.name`, `tool.duration_ms`, `tool.success` | 每次工具调用单独一个 span |
| 每次请求输入 token | Counter | `gen_ai.usage.input_tokens` | 用于 context 优化 |
| 每次请求输出 token | Counter | `gen_ai.usage.output_tokens` | 用于成本计算 |
| Cache hit 率 | Gauge | `gen_ai.usage.cache_read_input_tokens` | Prompt cache 效果 |
| 每次请求成本 | Gauge | `gen_ai.request.cost_usd` | 成本可观测性核心 |
| 推理链 | Log | `gen_ai.reasoning_trace` | LLM text 输出，用于调试 |
| 幻觉率 | Gauge | `gen_ai.hallucination_rate` | 可选，需要 eval pipeline 配合 |

### OpenTelemetry Semantic Conventions for GenAI

OpenTelemetry（OTel）社区在 2025 年发布了 GenAI 语义约定规范（[opentelemetry.io/docs/specs/semconv/gen-ai/](https://opentelemetry.io/docs/specs/semconv/gen-ai/)），统一了 LLM 调用的 span attribute 命名。

这很重要：如果每个 agent 框架自创字段名，切换可观测性后端时需要重写所有 dashboard。遵循语义约定，你的 agent 数据可以直接被 Grafana / Langfuse / Honeycomb 识别，不需要适配层。

核心字段（来源：OTel GenAI Semantic Conventions v1.36.0，[opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/)）：

```
# 启用最新实验性规范（v1.36.0+）
# OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental

gen_ai.operation.name      = "chat"                      # 必须：操作类型
gen_ai.provider.name       = "anthropic"                 # 必须：服务商标识
gen_ai.request.model       = "claude-sonnet-4-6"         # 条件必须：请求时指定的模型
gen_ai.response.model      = "claude-sonnet-4-6-20261001" # 推荐：实际响应的模型版本
gen_ai.usage.input_tokens  = 4230                        # 推荐：输入 token 总数
gen_ai.usage.output_tokens = 512                         # 推荐：输出 token 总数
gen_ai.usage.cache_read.input_tokens     = 3800          # 推荐：从 provider cache 读取的 token
gen_ai.usage.cache_creation.input_tokens = 200           # 推荐：写入 provider cache 的 token
gen_ai.tool.name           = "filesystem__read_file"     # 工具调用 span 必须：工具名
gen_ai.tool.call.id        = "call_abc123"               # 工具调用 span 推荐：唯一 ID
gen_ai.tool.type           = "function"                  # 工具调用 span 推荐：类型
```

**Agent 专属 span 属性**（来源：[opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)）：

```
gen_ai.operation.name      = "invoke_agent"              # 调用 agent 操作
gen_ai.agent.name          = "ResearchAgent"             # agent 名称（条件必须）
gen_ai.agent.id            = "agent-001"                 # agent 唯一 ID（条件必须）
gen_ai.agent.version       = "0.11.0"                    # agent 版本（条件必须）
gen_ai.conversation.id     = "conv-xyz"                  # 会话 ID（条件必须，可用时）
```

Span 命名规范：
- 推理 span → `chat claude-sonnet-4-6`（`{gen_ai.operation.name} {gen_ai.request.model}`）
- 工具执行 span → `execute_tool filesystem__read_file`
- 调用 agent span → `invoke_agent ResearchAgent`

字段 `gen_ai.usage.cache_read.input_tokens` 对应 Anthropic Prompt Cache（2024 年 8 月发布）：读取缓存的 token 费用是正常输入 token 的 10%（`gen_ai.usage.cache_read.input_tokens` 已包含在 `gen_ai.usage.input_tokens` 总数内）。追踪 cache hit 率可以量化 prompt 工程的成本优化效果，与 Ch10 context 工程章节形成呼应。

> 注意：v1.36.0 之前的 instrumentation 使用旧字段名（如 `gen_ai.usage.prompt_tokens`），如需迁移到最新规范，需设置环境变量 `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`。

### 完整代码：给 Lena 加 Span + Cost 计算

```python
# code/lena-v0.22/src/observability/agent_tracer.py
# 约 55 行，OTel Semantic Conventions for GenAI + 工具调用 span + cost 计算

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import structlog
from opentelemetry import trace
from opentelemetry.trace import Span

log = structlog.get_logger(__name__)

# Claude Sonnet 4.6 定价（2026 年，来源：https://www.anthropic.com/api#pricing）
COST_PER_INPUT_TOKEN   = 3.0 / 1_000_000   # $3 / 1M tokens
COST_PER_OUTPUT_TOKEN  = 15.0 / 1_000_000  # $15 / 1M tokens
COST_PER_CACHE_READ    = 0.3 / 1_000_000   # $0.30 / 1M tokens（90% 折扣）
COST_PER_CACHE_WRITE   = 3.75 / 1_000_000  # $3.75 / 1M tokens（25% 溢价）


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
    """给 Lena 的 agent loop 加工具调用 span + cost 计算。"""

    def __init__(self, tracer: trace.Tracer):
        self._tracer = tracer
        self._session_cost = 0.0

    @contextmanager
    def llm_span(self, model: str):
        """包裹 LLM 调用，记录 GenAI 语义约定字段。"""
        with self._tracer.start_as_current_span("gen_ai.completion") as span:
            span.set_attribute("gen_ai.system", "anthropic")
            span.set_attribute("gen_ai.request.model", model)
            t0 = time.monotonic()
            yield span
            span.set_attribute("gen_ai.duration_ms", int((time.monotonic() - t0) * 1000))

    def record_llm_usage(self, span: Span, usage) -> LLMCallMetrics:
        """从 Anthropic SDK usage 对象提取并记录 token 指标。"""
        metrics = LLMCallMetrics(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0),
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0),
        )
        # 写入 OTel span（遵循 GenAI 语义约定）
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
        """包裹单次工具调用，记录延迟和成功/失败。"""
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

在 agent loop 里的用法：

```python
# 在 AgentLoop.step() 里集成
tracer_wrapper = AgentTracer(tracer)

with tracer_wrapper.llm_span(model="claude-sonnet-4-6") as span:
    resp = await self._call_llm()
    metrics = tracer_wrapper.record_llm_usage(span, resp.usage)

# 工具调用时
for tool_call in resp.tool_calls:
    with tracer_wrapper.tool_span(tool_call.name, tool_call.id):
        result = await execute_tool(tool_call)
```

运行后在 Jaeger UI 里可以看到：每次 LLM 调用下挂着若干工具调用 span，点开任意 span 可以看到 token 数、cost、工具名、耗时。整个任务的调用树一目了然。

### 可视化工具对比：四个选择

| 工具 | 定位 | 部署模式 | 最适场景 |
|------|------|---------|---------|
| **Jaeger** | 分布式追踪（原生 OTel） | 自托管 Docker | 本地开发调试，trace 可视化 |
| **Langfuse** | Agent 专属 observability | 自托管 / 云端 | 需要 eval + trace 一体化，开源可审计 |
| **Helicone** | LLM 调用代理 + 分析 | 云端 SaaS | 快速接入，不需要 OTel 代码改造 |
| **Phoenix (Arize)** | LLM/AI 可观测性平台 | 自托管 / 云端 | 需要 embedding 分析、hallucination 检测 |

**推荐策略**：

- **本地开发**：Jaeger（`docker run -p 16686:16686 jaegertracing/all-in-one`，5 秒启动）
- **团队项目 / 需要 eval 集成**：Langfuse（开源，支持 LLM-as-judge 和 trace 联动，Ch21 eval pipeline 可直接接入）
- **快速原型验证（不想改代码）**：Helicone（在 API base URL 前加一层代理，零侵入）
- **需要 embedding 漂移检测 / 幻觉率监控**：Phoenix（适合 RAG agent，对应 Ch9 的知识库系统）

### 数据驱动的优化示例

这里引用一个在生产 agent 系统中真实发生的优化场景：某团队开启了 per-request token 追踪后，发现 P50 的 TTFT（Time-to-First-Token）在启用 prompt cache 后下降了约 60%——原因是他们的 system prompt（约 4,000 tokens）在每次请求都重新发送，开启 cache 后这部分 token 的读取成本降为原来的 10%，同时延迟也因为跳过了 KV cache 计算而显著降低。

这个优化只有在追踪了 `cache_read_input_tokens` 和 TTFT 之后才能被发现和量化。没有 observability，这个优化机会会永远埋在账单里。

```python
# 用 structlog 输出 cache 命中率统计（每 100 次调用汇总一次）
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

预期输出（100 次调用后）：
```
[info] cache_stats hit_rate=78.3% total_calls=100 avg_input_tokens=4230
```

78% 的 cache hit 率意味着你的 token 成本中有 78% × 90% = 70% 在以折扣价计算。如果 hit 率低于 40%，说明 system prompt 结构需要优化（cache 要求 prompt 前缀稳定）。

> **本节给读者带来的能力**：
> 1. **用 OTel Semantic Conventions 规范化 agent trace**——遵循标准字段名，可以直接接入任何兼容 OTel 的可观测性平台，不被厂商锁定
> 2. **追踪 per-tool-call span 和 per-request cost**——能定位慢工具、高成本任务，是 agent 性能优化的基础数据来源
> 3. **根据场景选择合适的可观测性工具**——知道什么时候用 Jaeger / Langfuse / Helicone / Phoenix，不盲目引入重型平台

---

## Beat 7 — Design Note

> **Why Not Just Alert After the Fact? — Cost 监控为何必须前置熔断**

最直接的 cost 监控方案是：接入云账单 API，每小时拉一次花费，超阈值发 Slack 告警，然后人工处理。

这个方案有三个真实的工程缺陷：

**缺陷一：时间窗口问题。** AWS Cost Explorer 的数据延迟约 8-24 小时，Google Cloud Billing 约 1-6 小时。一个死循环 agent 在 1 小时内可以产生 $30+ 的费用。等告警推送到你手机时，损失已经发生。

**缺陷二：依赖人工响应。** 告警本质上是通知人，人需要时间响应。一个在凌晨 3 点触发的告警，到你 8 点醒来看手机，中间 5 小时的损失没人能负责。agent 系统的设计目标是自主运行——依赖人工响应和这个目标是根本矛盾的。

**缺陷三：无法渐进降速。** 硬停止在长任务的中间状态会导致数据不一致（比如已经写了一半的文件、发了一半的消息）。前置熔断的 THROTTLE 状态给了任务一个"优雅降速"窗口，在成本可控的范围内尽量把当前任务完成。

当前选择：在 agent loop 调用 LLM 之前检查 BudgetController，这是 nanoClaw `budget.py`（第 84 行）设计的直接延伸，增加了渐进降速语义。

局限性：这个设计只能控制 LLM 调用频率，无法控制第三方工具（如发 email 工具、数据库写入工具）的副作用频率。如果需要对所有工具调用做速率控制，应该在 PreToolUse hook 层面加独立的 rate limiter。这是一个尚未解决得很好的问题：如何统一控制"既有成本又有副作用"的 agent 操作，目前没有通行标准。

> Anthropic 官方的 [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) 强调"Transparency"原则——agent 的每步行为应可审计。本章的结构化日志 + OTel span 是 Transparency 原则的具体落地：每次 LLM 调用不仅被记录，还被赋予可追溯的 `trace_id`，让任何历史决策都能回放。

---

## 叙事钩子

Lena 现在能在生产环境 7×24 运行，每次决策都有日志可查，每次花费都在预算控制内。

但还有一个维度没有解决：她能泛化成任何专用 agent 吗？一个做代码审查的 Lena、一个做市场调研的 Lena、一个管理日历的 Lena——它们共用一套 runtime，但有不同的工具集、不同的 system prompt、不同的技能包。下一章，我们把这个"通用 runtime → 专用 agent"的通路打通。
