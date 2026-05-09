"""
tools.py — Lena v0.3 工具定义

每个工具就是一个普通 Python 函数，加上一份 JSON Schema 描述。
LLM 读 schema 决定要不要调用；runtime 读 handler 真正执行。

Ch 3 只需要一个工具：get_time。
"""

from datetime import datetime
from typing import Any


def get_time_handler(timezone: str = "local") -> str:
    """真正执行 get_time 的函数。"""
    now = datetime.now()
    return now.strftime(f"当前时间是 %Y年%m月%d日 %H:%M:%S（{timezone}）")


# ─── 工具注册表 ────────────────────────────────────────────────────────────────
# 每个条目：{"schema": <Anthropic tool_use 格式>, "handler": <Python 函数>}

TOOLS: list[dict[str, Any]] = [
    {
        "schema": {
            "name": "get_time",
            "description": "获取当前本地时间。当用户问'现在几点'、'今天几号'等时间相关问题时调用。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "时区说明，默认 'local'",
                        "default": "local",
                    }
                },
                "required": [],
            },
        },
        "handler": get_time_handler,
    }
]


def get_tool_schemas() -> list[dict]:
    """返回所有工具的 schema（传给 LLM）。"""
    return [t["schema"] for t in TOOLS]


def execute_tool(name: str, inputs: dict) -> str:
    """按名称执行工具，返回结果字符串。"""
    for tool in TOOLS:
        if tool["schema"]["name"] == name:
            try:
                result = tool["handler"](**inputs)
                return str(result)
            except Exception as e:
                return f"工具执行出错：{e}"
    return f"未知工具：{name}"
