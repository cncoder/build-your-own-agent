"""
trading_bot.py：完整可运行的量化交易 agent 示例

演示三种派生姿势 + 熔断器状态机 + 硬编码风控

运行：
  python -m spec_kit.cli create trader --role "crypto trader" --template trading
  python examples/trading_bot.py
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import boto3


# ── 熔断器状态机（案例 19.1 血泪教训：缺 CLOSED 自动恢复会永久停止交易）──

class CircuitState(Enum):
    CLOSED = "closed"        # 正常
    OPEN = "open"            # 熔断
    HALF_OPEN = "half_open"  # 试探期


@dataclass
class CircuitBreaker:
    max_losses: int = 3
    cooldown_seconds: int = 86400  # 24h

    state: CircuitState = CircuitState.CLOSED
    consecutive_losses: int = 0
    open_at: float = 0.0

    def record_loss(self):
        self.consecutive_losses += 1
        if self.consecutive_losses >= self.max_losses:
            self.state = CircuitState.OPEN
            self.open_at = time.time()
            print(f"[CIRCUIT BREAKER] 熔断触发！连续亏损 {self.consecutive_losses} 次，冷却 {self.cooldown_seconds}s")

    def record_win(self):
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.consecutive_losses = 0  # 关键：必须清零（血泪教训）
            print("[CIRCUIT BREAKER] 熔断解除，恢复正常交易")

    def can_trade(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.open_at >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
                print("[CIRCUIT BREAKER] 进入试探期（HALF_OPEN）")
                return True
            return False
        if self.state == CircuitState.HALF_OPEN:
            return True
        return False


# ── 硬编码风控（代码级，AI prompt 无法绕过）──────────────────────────────

@dataclass
class RiskLimits:
    max_position_pct: float = 0.02   # 单笔最大 2% 资金
    max_daily_loss_pct: float = 0.05 # 每日最大 5% 亏损
    total_capital: float = 10000.0   # 总资金（USDT）
    daily_loss: float = 0.0

    def validate(self, order_value: float) -> tuple[bool, str]:
        """返回 (是否通过, 拒绝原因)"""
        if order_value <= 0:
            return False, "订单金额必须 > 0"
        max_allowed = self.total_capital * self.max_position_pct
        if order_value > max_allowed:
            return False, f"超出单笔风险限额（{order_value:.2f} > {max_allowed:.2f}）"
        max_daily_loss = self.total_capital * self.max_daily_loss_pct
        if self.daily_loss >= max_daily_loss:
            return False, f"今日亏损已达上限（{self.daily_loss:.2f} >= {max_daily_loss:.2f}）"
        return True, ""


# ── Mock 工具函数（实际使用时替换为真实 API 调用）──────────────────────────

def get_price(symbol: str) -> dict:
    """Mock 价格数据（实际替换为 Bybit/OKX API）"""
    mock_prices = {"BTC/USDT": 103200.0, "ETH/USDT": 2480.0, "SOL/USDT": 168.5}
    price = mock_prices.get(symbol, 100.0)
    return {"symbol": symbol, "price": price, "timestamp": time.time()}


def get_indicators(symbol: str, timeframe: str = "1h") -> dict:
    """Mock 技术指标（实际替换为 TA-Lib 或交易所 API）"""
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "rsi_14": 42.0,        # 中性偏低
        "macd_cross": "golden", # 金叉
        "bb_position": "above_mid",  # 中轨以上
        "signal_strength": 0.72,
    }


def place_order(symbol: str, side: str, amount: float, order_type: str = "market", price: float = 0) -> dict:
    """Mock 下单（实际替换为交易所 SDK）"""
    print(f"[ORDER] {side.upper()} {amount} {symbol} @ {'market' if order_type == 'market' else price}")
    return {"order_id": f"mock_{int(time.time())}", "status": "filled", "filled_price": get_price(symbol)["price"]}


def get_positions() -> dict:
    """Mock 查询仓位"""
    return {"positions": [], "total_unrealized_pnl": 0.0}


def get_pnl() -> dict:
    """Mock 查询盈亏"""
    return {"today_pnl": 0.0, "today_trades": 0}


def send_message(channel: str, content: str, format: str = "markdown") -> dict:
    """Mock 发送消息（实际替换为 Discord/飞书 webhook）"""
    print(f"[MESSAGE → {channel}] {content[:100]}...")
    return {"status": "sent"}


# ── 工具调用分发 ──────────────────────────────────────────────────────────

TOOL_MAP = {
    "get_price": get_price,
    "get_indicators": get_indicators,
    "place_order": place_order,
    "get_positions": get_positions,
    "get_pnl": get_pnl,
    "send_message": send_message,
}

risk_limits = RiskLimits()
circuit_breaker = CircuitBreaker()


def handle_tool_call(name: str, inputs: dict) -> str:
    """执行工具调用，place_order 前强制风控检查。"""
    if name == "place_order":
        # 硬编码风控：不可绕过
        amount = inputs.get("amount", 0)
        price_data = get_price(inputs.get("symbol", "BTC/USDT"))
        order_value = amount * price_data["price"]
        ok, reason = risk_limits.validate(order_value)
        if not ok:
            return json.dumps({"error": f"风控拒绝：{reason}"})
        if not circuit_breaker.can_trade():
            return json.dumps({"error": "熔断器触发，禁止交易"})

    fn = TOOL_MAP.get(name)
    if fn is None:
        return json.dumps({"error": f"未知工具：{name}"})
    try:
        result = fn(**inputs)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── Trading Agent 主循环 ──────────────────────────────────────────────────

def load_system_prompt() -> str:
    prompt_path = Path("agents/trader/system_prompt.md")
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return """\
你是 TradingBot，一个量化交易专用 agent。
市场分析 → 信号确认 → 风控 → 执行。
风控规则由代码层强制执行，你无法绕过。
"""


def load_tools() -> list[dict]:
    from spec_kit.tool_profiles import get_tools_for_profile
    return get_tools_for_profile("trading")


def _to_bedrock_tools(anthropic_tools: list[dict]) -> list[dict]:
    """Convert Anthropic SDK tool defs → Bedrock toolSpec format."""
    return [
        {
            "toolSpec": {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": {"json": t.get("input_schema", {"type": "object", "properties": {}})},
            }
        }
        for t in anthropic_tools
    ]


def run_trading_cycle(client, cycle_num: int = 1):
    """执行一次交易分析周期。运行时：AWS Bedrock Converse API。"""
    system_prompt = load_system_prompt()
    anthropic_tools = load_tools()
    bedrock_tools = _to_bedrock_tools(anthropic_tools)

    print(f"\n{'='*50}")
    print(f"交易周期 #{cycle_num}")
    print(f"熔断状态：{circuit_breaker.state.value}")
    print(f"{'='*50}")

    messages = [
        {
            "role": "user",
            "content": [{"text": "请执行一次完整的市场扫描，分析当前 BTC/USDT 的交易机会，如有信号则执行（记住先通过风控检查）。"}],
        }
    ]

    MODEL = "us.anthropic.claude-sonnet-4-6"
    BEDROCK_REGION = os.getenv("AWS_REGION", "us-west-2")

    max_rounds = 10
    for _ in range(max_rounds):
        resp = client.converse(
            modelId=MODEL,
            system=[{"text": system_prompt}],
            toolConfig={"tools": bedrock_tools},
            messages=messages,
            inferenceConfig={"maxTokens": 2048},
        )

        stop_reason = resp.get("stopReason", "end_turn")
        msg = resp["output"]["message"]

        if stop_reason == "end_turn":
            for block in msg.get("content", []):
                if "text" in block:
                    print(f"\n[AGENT] {block['text']}")
            break

        if stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": msg["content"]})
            tool_results = []
            for block in msg.get("content", []):
                if "toolUse" in block:
                    tu = block["toolUse"]
                    print(f"[TOOL] {tu['name']}({json.dumps(tu['input'], ensure_ascii=False)[:80]})")
                    result = handle_tool_call(tu["name"], tu["input"])
                    print(f"  → {result[:100]}")
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tu["toolUseId"],
                            "content": [{"text": result}],
                        }
                    })
            messages.append({"role": "user", "content": tool_results})


def main():
    import os
    client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-west-2"))
    print("TradingBot 启动（Lena-SpecKit 派生，案例 19.1）")
    print("按 Ctrl+C 停止\n")

    cycle = 1
    try:
        while True:
            run_trading_cycle(client, cycle)
            cycle += 1
            print(f"\n等待下一个周期（5 分钟）...")
            time.sleep(300)
    except KeyboardInterrupt:
        print("\n停止。")


if __name__ == "__main__":
    main()
