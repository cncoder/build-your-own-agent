"""
provider.py — Lena v0.3 Provider 适配层（Bedrock 单 provider）

运行时：AWS Bedrock Converse API（boto3）
modelId：us.anthropic.claude-sonnet-4-6（inference profile，必须带 us. 前缀）

Bedrock Converse 消息格式关键点：
  - content 是 list of blocks：[{"text": "..."}] 或 [{"toolUse": {...}}] 或 [{"toolResult": {...}}]
  - system 是顶层数组：[{"text": "..."}]
  - 工具定义：toolConfig.tools = [{"toolSpec": {"name":..., "description":..., "inputSchema":{"json":...}}}]
  - 工具调用返回：response["output"]["message"]["content"] 里含 {"toolUse": {"toolUseId":..., "name":..., "input":...}}
  - stopReason = "tool_use" 时需要调用工具
  - 工具结果回填：{"role":"user","content":[{"toolResult":{"toolUseId":..,"content":[{"text":...}]}}]}

协议差异参考（仅作背景知识）：
  Anthropic SDK  → tool_use block；tool_result 用独立 user 消息（snake_case）
  OpenAI         → tool_calls 字段在顶层；role="tool" 消息
  Bedrock        → toolUse / toolResult（camelCase），boto3 封装

生产里可加其他 provider，本书代码默认 Bedrock。
附录 D 有 OpenAI/Anthropic 直连映射速查。
"""

from __future__ import annotations

import json
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
    content: str                        # 文字回复（可为空）
    tool_calls: list[dict]             # [{name, inputs, id}]（可为空列表）
    stop_reason: str                    # "end_turn" | "tool_use"
    raw: Any = None                     # 原始响应（调试用）


def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    system: str = SYSTEM_PROMPT,
    max_tokens: int = 1024,
) -> LLMResponse:
    """
    Bedrock Converse API 单入口。

    messages 格式（Bedrock 风格）：
      [{"role": "user", "content": [{"text": "..."}]}]

    tools 格式（Anthropic SDK input_schema → Bedrock toolSpec）：
      传入 Anthropic 风格的工具定义列表，内部转换。
    """
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
    """构建 Bedrock 格式的 tool_result 消息。"""
    return {
        "role": "user",
        "content": [{"toolResult": {"toolUseId": tool_id, "content": [{"text": result}]}}],
    }


def make_assistant_with_tool_use(response: LLMResponse) -> dict:
    """将包含 tool_use 的 LLM 响应转成 assistant 消息（用于回填 messages）。"""
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


class BedrockProvider:
    """Bedrock provider 封装，对外暴露统一接口。"""

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        return chat(messages, tools)

    def make_assistant_with_tool_use(self, response: LLMResponse) -> dict:
        return make_assistant_with_tool_use(response)

    def make_tool_result_message(self, tool_id: str, result: str) -> dict:
        return make_tool_result_message(tool_id, result)


def create_provider(name: str) -> BedrockProvider:
    """
    工厂函数：按名称返回 provider 实例。

    支持的值：
      "bedrock"   — AWS Bedrock Converse API（默认，无需额外依赖）
      "anthropic" — 与 bedrock 使用相同底层（教学环境统一走 Bedrock）

    生产扩展：可在此处加 OpenAIProvider 分支，业务代码无需改动。
    """
    supported = ("anthropic", "bedrock")
    if name not in supported:
        raise ValueError(f"未知 provider '{name}'，支持：{supported}")
    # 本书统一走 Bedrock；anthropic 别名保持向后兼容
    return BedrockProvider()
