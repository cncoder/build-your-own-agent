"""
Lena v0.10 — Agent loop with three-layer compaction and prompt caching.

New in v0.10 (compared to v0.9):
  - compaction.py: microcompact / AutoCompactor / reactive_compact
  - cache.py:      parse_usage(), build_request_with_caching()
  - monitor.py:    live token stats + cache hit rate per turn

Usage:
    python3 lena.py

运行时：AWS Bedrock Converse API（boto3）
本书代码默认 Bedrock。OpenAI/Anthropic 直连映射见附录 D。
"""

from __future__ import annotations

import os

import boto3

from cache import TokenUsage, build_request_with_caching, parse_usage
from compaction import AutoCompactor, microcompact, reactive_compact
from monitor import TokenMonitor

BEDROCK_REGION = os.getenv("AWS_REGION", "us-west-2")
MODEL = "us.anthropic.claude-sonnet-4-6"  # inference profile ID
CONTEXT_WINDOW = 128_000


# --------------------------------------------------------------------------- #
# Rough token estimator (client-side, no tokenizer dependency)                 #
# --------------------------------------------------------------------------- #

def estimate_tokens(messages: list[dict]) -> int:
    """
    Approximate token count for a messages list.
    Rule of thumb: 1 token ≈ 4 characters for English prose.
    """
    return len(str(messages)) // 4


# --------------------------------------------------------------------------- #
# Agent Loop                                                                    #
# --------------------------------------------------------------------------- #

class AgentLoop:
    """
    Minimal agent loop with three-layer context compaction.

    Three-layer cascade (executed in order each turn):
      1. microcompact   — inline, zero cost, every turn
      2. autocompact    — threshold-based, one LLM call, circuit-breaker
      3. reactive       — 413 error path, one LLM call, last resort
    """

    SYSTEM_PROMPT = (
        "You are Lena, a general-purpose assistant. "
        "Answer concisely. Acknowledge previous turns when relevant."
    )

    def __init__(self, model: str = MODEL) -> None:
        self._client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
        self.model = model
        self.messages: list[dict] = []
        self.compactor = AutoCompactor(self._client, model)
        self.monitor = TokenMonitor()

    def run(self, user_input: str, tools: list[dict] | None = None) -> str:
        """
        Process one user turn. Returns the assistant's reply.

        tools: list of tool definition dicts (Anthropic SDK format with input_schema).
               Pass None or [] if this turn does not use tools.
        """
        tools = tools or []
        self.messages.append({"role": "user", "content": [{"text": user_input}]})

        # ------------------------------------------------------------------ #
        # Layer 1 — Microcompact (always, 0 cost)                             #
        # ------------------------------------------------------------------ #
        self.messages = microcompact(self.messages)

        # ------------------------------------------------------------------ #
        # Layer 2 — AutoCompact (threshold-based)                             #
        # ------------------------------------------------------------------ #
        token_estimate = estimate_tokens(self.messages)
        if self.compactor.should_compact(token_estimate, CONTEXT_WINDOW):
            compacted = self.compactor.compact(self.messages)
            if compacted:
                self.messages = compacted
                self.monitor.record_compaction()

        kwargs: dict = {
            "modelId": self.model,
            "system": [{"text": self.SYSTEM_PROMPT}],
            "messages": self.messages,
            "inferenceConfig": {"maxTokens": 1024},
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

        while True:
            try:
                resp = self._client.converse(**kwargs)
            except Exception as exc:
                exc_str = str(exc)
                if "prompt_too_long" in exc_str or "413" in exc_str:
                    # -------------------------------------------------------- #
                    # Layer 3 — ReactiveCompact (413 recovery)                 #
                    # -------------------------------------------------------- #
                    self.messages = reactive_compact(self.messages)
                    kwargs["messages"] = self.messages
                    self.monitor.record_compaction()
                    continue
                raise

            # Record usage
            raw_usage = {
                "input_tokens":                resp.get("usage", {}).get("inputTokens", 0),
                "output_tokens":               resp.get("usage", {}).get("outputTokens", 0),
                "cache_read_input_tokens":     0,
                "cache_creation_input_tokens": 0,
            }
            self.monitor.record(parse_usage(raw_usage, "bedrock"))

            stop_reason = resp.get("stopReason", "end_turn")
            msg = resp["output"]["message"]

            if stop_reason == "end_turn":
                reply = " ".join(
                    b["text"] for b in msg.get("content", []) if "text" in b
                )
                self.messages.append({"role": "assistant", "content": [{"text": reply}]})
                return reply

            # Tool use — collect results and loop (simplified; see Ch 6 for full impl)
            tool_results = []
            for block in msg.get("content", []):
                if "toolUse" in block:
                    tu = block["toolUse"]
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tu["toolUseId"],
                            "content": [{"text": "[tool not wired in this stub]"}],
                        }
                    })

            self.messages.append({"role": "assistant", "content": msg["content"]})
            self.messages.append({"role": "user", "content": tool_results})
            kwargs["messages"] = self.messages


# --------------------------------------------------------------------------- #
# 50-round test                                                                 #
# --------------------------------------------------------------------------- #

def run_50_rounds() -> None:
    """Run 50 turns of conversation and print live stats."""
    lena = AgentLoop()

    prompts = [
        "What is the capital of France?",
        "Write a Python function that reverses a string.",
        "What did we discuss in the previous two turns?",
        "Add a docstring to the function you wrote.",
        "What is 2 + 2?",
    ]

    for i in range(1, 51):
        prompt = prompts[(i - 1) % len(prompts)]
        lena.run(f"Turn {i}: {prompt}")
        print(lena.monitor.summary_line(i))

    print()
    print(lena.monitor.full_report())


if __name__ == "__main__":
    run_50_rounds()
