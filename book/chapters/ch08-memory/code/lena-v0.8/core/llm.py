"""
core/llm.py — Bedrock provider for lena-v0.8.
Bedrock Converse API via boto3.
本书代码默认 Bedrock。OpenAI/Anthropic 直连映射见附录 D。
"""
import os

import boto3

BEDROCK_REGION = os.environ.get("AWS_REGION", "us-west-2")
MODEL = "us.anthropic.claude-sonnet-4-6"  # inference profile ID（必须带 us. 前缀）

_client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


def call_llm(
    messages: list[dict],
    system: str,
    tools: list[dict] | None = None,
    max_tokens: int = 1024,
) -> dict:
    """
    Call Bedrock Converse API. Returns normalized response dict.

    messages 格式：[{"role": "user", "content": [{"text": "..."}]}]
    """
    kwargs: dict = {
        "modelId": MODEL,
        "system": [{"text": system}],
        "messages": messages,
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

    resp = _client.converse(**kwargs)
    msg = resp["output"]["message"]

    return {
        "stop_reason": resp.get("stopReason", "end_turn"),
        "content": [_block_to_dict(b) for b in msg.get("content", [])],
    }


def _block_to_dict(block: dict) -> dict:
    if "text" in block:
        return {"type": "text", "text": block["text"]}
    if "toolUse" in block:
        tu = block["toolUse"]
        return {
            "type": "tool_use",
            "id": tu["toolUseId"],
            "name": tu["name"],
            "input": tu["input"],
        }
    return {"type": "unknown"}
