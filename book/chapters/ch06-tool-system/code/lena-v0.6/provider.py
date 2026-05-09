"""
provider.py — Lena v0.4 Provider 适配层（Bedrock 单 provider）

运行时：AWS Bedrock Converse API（boto3）
modelId：us.anthropic.claude-sonnet-4-6（inference profile，必须带 us. 前缀）

Bedrock Converse 消息格式关键点：
  - content 是 list of blocks：[{"text": "..."}] 或 [{"toolUse": {...}}] 或 [{"toolResult": {...}}]
  - system 是顶层数组：[{"text": "..."}]
  - 工具定义：toolConfig.tools = [{"toolSpec": {"name":..., "description":..., "inputSchema":{"json":...}}}]
  - stopReason = "tool_use" 时需要调用工具
  - 工具结果回填：{"role":"user","content":[{"toolResult":{"toolUseId":..,"content":[{"text":...}]}}]}

协议差异参考（仅作背景知识）：
  Anthropic SDK  → tool_use block；tool_result（snake_case）
  OpenAI         → tool_calls 顶层；role="tool" 消息
  Bedrock        → toolUse / toolResult（camelCase），boto3

生产里可加其他 provider，本书代码默认 Bedrock。
附录 D 有 OpenAI/Anthropic 直连映射速查。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import boto3


BEDROCK_REGION = os.getenv("AWS_REGION", "us-west-2")
MODEL_ID = os.getenv("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6")

_bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

SYSTEM_PROMPT = "你是 Lena，一个有帮助的 AI 助手。请用中文回答。"


@dataclass
class LLMResponse:
    """统一的 LLM 响应格式。"""
    content: str
    tool_calls: list[dict]             # [{name, inputs, id}]
    stop_reason: str                    # "end_turn" | "tool_use"
    raw: Any = None


def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    system: str = SYSTEM_PROMPT,
    max_tokens: int = 1024,
) -> LLMResponse:
    """Bedrock Converse API 单入口。"""
    kwargs: dict = {
        "modelId": MODEL_ID,
        "messages": messages,
        "system": [{"text": system}],
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if tools:
        kwargs["toolConfig"] = {
            "tools": [
                {
                    "toolSpec": {
                        "name": t["name"],
                        "description": t["description"],
                        "inputSchema": {"json": t["input_schema"]},
                    }
                }
                for t in tools
            ]
        }

    raw = _bedrock.converse(**kwargs)
    msg = raw["output"]["message"]

    text_parts: list[str] = []
    tool_calls: list[dict] = []

    for block in msg.get("content", []):
        if "text" in block:
            text_parts.append(block["text"])
        elif "toolUse" in block:
            tu = block["toolUse"]
            tool_calls.append({
                "id": tu["toolUseId"],
                "name": tu["name"],
                "inputs": tu["input"],
            })

    return LLMResponse(
        content=" ".join(text_parts),
        tool_calls=tool_calls,
        stop_reason=raw.get("stopReason", "end_turn"),
        raw=raw,
    )


def make_tool_result_message(tool_id: str, result: str) -> dict:
    """构建 Bedrock 格式的工具结果消息。"""
    return {
        "role": "user",
        "content": [{"toolResult": {"toolUseId": tool_id, "content": [{"text": result}]}}],
    }


def make_assistant_with_tool_use(response: LLMResponse) -> dict:
    """将包含工具调用的 LLM 响应转成 assistant 消息。"""
    content: list[dict] = []
    if response.content:
        content.append({"text": response.content})
    for tc in response.tool_calls:
        content.append({
            "toolUse": {
                "toolUseId": tc["id"],
                "name": tc["name"],
                "input": tc["inputs"],
            }
        })
    return {"role": "assistant", "content": content}
