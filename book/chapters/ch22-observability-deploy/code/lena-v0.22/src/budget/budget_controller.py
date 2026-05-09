"""日预算四状态机。

四个状态（NORMAL → WARNING → THROTTLE → STOPPED）：
  NORMAL   (0-80%)   正常运行
  WARNING  (80-90%)  记录告警日志，不影响调用
  THROTTLE (90-100%) 每次 LLM 调用前 sleep 2s，主动降速
  STOPPED  (≥100%)   拒绝调用，返回 False

为什么四状态而不是二状态（正常/停止）：
  THROTTLE 状态给正在进行的长任务一个"优雅降速"窗口，
  在成本可控的范围内尽量把当前任务完成，而不是在任务进行到一半时突然切断。
  对于纯实验性场景，把 throttle_pct 设为 1.0 可退化为二状态。

已知局限性：
  - 只控制 LLM 调用频率，不控制工具调用的副作用（如写文件、发邮件）
  - 成本估算基于固定每 token 价格，不同模型价格差异大，需按实际模型调整
  - 重启后 _spent_usd 归零，如需跨进程持久化，需把 _spent_usd 写入 SQLite

参考：nanoClaw security/budget.py SessionBudget（迭代计数 + token 计数双维度熔断）
本实现在此基础上增加了美元维度和渐进降速语义。
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
    """预算配置。

    Attributes:
        daily_usd:         日预算上限（美元）
        warn_pct:          超过此比例触发 WARNING 状态（默认 80%）
        throttle_pct:      超过此比例触发 THROTTLE 状态（默认 90%）
        throttle_delay_sec: THROTTLE 状态下每次 LLM 调用前的延迟（秒）
    """
    daily_usd: float = 5.0
    warn_pct: float = 0.80
    throttle_pct: float = 0.90
    throttle_delay_sec: float = 2.0


@dataclass
class BudgetController:
    """日预算控制器。

    使用方式：
        budget = BudgetController(BudgetConfig(daily_usd=10.0))

        # 每次 LLM 调用前
        allowed = await budget.check_and_wait()
        if not allowed:
            return None

        # LLM 调用完成后
        budget.record_cost(cost_usd)

        # 查询当前状态
        print(budget.state)        # BudgetState.WARNING
        print(budget.usage_pct)    # 0.8234
    """
    config: BudgetConfig = field(default_factory=BudgetConfig)
    _spent_usd: float = field(default=0.0, repr=False)
    _date: date = field(default_factory=date.today, repr=False)
    _state_change_callbacks: list[Callable[[BudgetState], None]] = field(
        default_factory=list, repr=False
    )

    def _reset_if_new_day(self) -> None:
        """午夜自动重置。日预算是日历天，不是滚动 24 小时窗口。"""
        today = date.today()
        if today != self._date:
            log.info(
                "budget_reset",
                prev_date=str(self._date),
                prev_spent_usd=round(self._spent_usd, 4),
            )
            self._spent_usd = 0.0
            self._date = today

    @property
    def state(self) -> BudgetState:
        """当前预算状态（每次访问自动检查是否需要日历天重置）。"""
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

        Returns:
            True  = 可以继续调用（NORMAL / WARNING / THROTTLE）
            False = 已达上限，不应调用（STOPPED）

        THROTTLE 状态下会 sleep throttle_delay_sec 秒后返回 True（减速但不停止）。
        """
        s = self.state
        if s == BudgetState.STOPPED:
            log.warning(
                "budget_stopped",
                spent_usd=round(self._spent_usd, 4),
                daily_limit_usd=self.config.daily_usd,
            )
            return False
        if s == BudgetState.THROTTLE:
            log.info(
                "budget_throttle",
                delay_sec=self.config.throttle_delay_sec,
                spent_pct=round(self.usage_pct * 100, 1),
            )
            await asyncio.sleep(self.config.throttle_delay_sec)
        return True

    def record_cost(self, usd: float) -> None:
        """记录一次 LLM 调用的实际费用，检查并通知状态跃迁。

        Args:
            usd: 本次调用的美元费用，可通过 token 数 × 单价计算。

        示例（claude-sonnet-4-6 价格）：
            cost = input_tokens * 3e-6 + output_tokens * 15e-6
            budget.record_cost(cost)
        """
        prev_state = self.state
        self._spent_usd += usd
        new_state = self.state
        if new_state != prev_state:
            log.warning(
                "budget_state_change",
                from_state=prev_state.value,
                to_state=new_state.value,
                spent_usd=round(self._spent_usd, 4),
                daily_limit_usd=self.config.daily_usd,
                usage_pct=round(self.usage_pct * 100, 1),
            )
            for cb in self._state_change_callbacks:
                cb(new_state)

    def on_state_change(self, callback: Callable[[BudgetState], None]) -> None:
        """注册状态跃迁回调（如发 Telegram / Discord 告警）。

        callback 在状态发生跃迁（任意方向）时被调用，传入新状态。
        """
        self._state_change_callbacks.append(callback)

    @property
    def usage_pct(self) -> float:
        """当前使用比例（0.0 ~ 1.0+），每次访问自动重置日历天。"""
        self._reset_if_new_day()
        return self._spent_usd / self.config.daily_usd

    @property
    def remaining_usd(self) -> float:
        """剩余预算（美元），可能为负（超额）。"""
        return max(0.0, self.config.daily_usd - self._spent_usd)
