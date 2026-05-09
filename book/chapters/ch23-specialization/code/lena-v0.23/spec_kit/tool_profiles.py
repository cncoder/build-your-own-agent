"""
工具集配置（派生姿势 ②：工具集裁剪）

每个专用 agent 只保留它需要的工具。
工具越少，幻觉越少，安全边界越清晰。
"""

from typing import NamedTuple


class ToolSpec(NamedTuple):
    name: str
    description: str
    input_schema: dict


# ── 通用工具库（完整集合）──────────────────────────────────────────────

ALL_TOOLS = {
    # 市场数据
    "get_price": ToolSpec(
        name="get_price",
        description="查询加密货币实时价格",
        input_schema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "交易对，如 BTC/USDT"},
            },
            "required": ["symbol"],
        },
    ),
    "get_indicators": ToolSpec(
        name="get_indicators",
        description="获取技术指标（RSI/MACD/BB）",
        input_schema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "timeframe": {"type": "string", "description": "1m/5m/15m/1h/4h/1d"},
            },
            "required": ["symbol"],
        },
    ),
    # 交易操作
    "get_positions": ToolSpec(
        name="get_positions",
        description="查询当前持仓",
        input_schema={"type": "object", "properties": {}},
    ),
    "place_order": ToolSpec(
        name="place_order",
        description="下单（受硬编码风控保护，超额会被拒绝）",
        input_schema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "amount": {"type": "number", "description": "下单数量（基础货币）"},
                "order_type": {"type": "string", "enum": ["market", "limit"], "default": "market"},
                "price": {"type": "number", "description": "限价单价格（market 单不需要）"},
            },
            "required": ["symbol", "side", "amount"],
        },
    ),
    "close_position": ToolSpec(
        name="close_position",
        description="平仓",
        input_schema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "reason": {"type": "string", "description": "平仓原因（记录到日志）"},
            },
            "required": ["symbol"],
        },
    ),
    "get_pnl": ToolSpec(
        name="get_pnl",
        description="查询今日盈亏",
        input_schema={"type": "object", "properties": {}},
    ),
    # 内容采集
    "collect_news": ToolSpec(
        name="collect_news",
        description="从 15 个 collector 采集最新资讯（去重后返回）",
        input_schema={
            "type": "object",
            "properties": {
                "topics": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "default": 50},
            },
        },
    ),
    "summarize": ToolSpec(
        name="summarize",
        description="对内容列表生成摘要",
        input_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "style": {"type": "string", "enum": ["bullet", "prose", "podcast"], "default": "prose"},
            },
            "required": ["content"],
        },
    ),
    "tts_synthesize": ToolSpec(
        name="tts_synthesize",
        description="将文本合成语音（调用 Qwen3-TTS Rust proxy port 8880）",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "voice": {"type": "string", "enum": ["host_a", "host_b"], "description": "双声道：host_a 低沉，host_b 理性"},
                "output_path": {"type": "string"},
            },
            "required": ["text", "voice", "output_path"],
        },
    ),
    # DevOps
    "list_alarms": ToolSpec(
        name="list_alarms",
        description="列出 AWS CloudWatch 告警",
        input_schema={
            "type": "object",
            "properties": {
                "state": {"type": "string", "enum": ["ALARM", "OK", "INSUFFICIENT_DATA"], "default": "ALARM"},
            },
        },
    ),
    "restart_service": ToolSpec(
        name="restart_service",
        description="重启 ECS/K8s 服务",
        input_schema={
            "type": "object",
            "properties": {
                "service_name": {"type": "string"},
                "cluster": {"type": "string"},
            },
            "required": ["service_name"],
        },
    ),
    # 通用
    "send_message": ToolSpec(
        name="send_message",
        description="发送消息到 Discord/飞书",
        input_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "content": {"type": "string"},
                "format": {"type": "string", "enum": ["text", "markdown", "embed"], "default": "markdown"},
            },
            "required": ["channel", "content"],
        },
    ),
}


# ── 专用工具集（裁剪后）──────────────────────────────────────────────────

TOOL_PROFILES: dict[str, list[str]] = {
    "trading": [
        "get_price",
        "get_indicators",
        "get_positions",
        "place_order",
        "close_position",
        "get_pnl",
        "send_message",
    ],
    "podcaster": [
        "collect_news",
        "summarize",
        "tts_synthesize",
        "send_message",
    ],
    "devops": [
        "list_alarms",
        "restart_service",
        "send_message",
    ],
}


def get_tools_for_profile(profile: str) -> list[dict]:
    """根据 profile 名返回 Anthropic SDK 格式的工具列表。"""
    tool_names = TOOL_PROFILES.get(profile, list(ALL_TOOLS.keys()))
    result = []
    for name in tool_names:
        if name in ALL_TOOLS:
            spec = ALL_TOOLS[name]
            result.append({
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
            })
    return result
