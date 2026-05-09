"""
Three-layer compaction for Lena v0.10.

Layer 1 — microcompact:    inline cleanup of stale tool_result blocks, no API call.
Layer 2 — AutoCompactor:   LLM-powered summary triggered at token threshold.
Layer 3 — reactive_compact: emergency collapse triggered by a live 413 error.

运行时：AWS Bedrock Converse API（boto3）
"""

from __future__ import annotations

import boto3


# --------------------------------------------------------------------------- #
# Layer 1 — Microcompact                                                        #
# --------------------------------------------------------------------------- #

def microcompact(messages: list[dict], keep_last: int = 3) -> list[dict]:
    """
    Replace stale tool_result blocks with a placeholder.

    Keeps the most recent `keep_last` tool-result turns intact.
    Cost: zero. Safe to call on every loop iteration.

    Source reference: microCompact.ts:253 (Claude Code)

    Bedrock 消息格式：toolResult 在 content 数组中作为独立 block。
    """
    result_turns = [
        i for i, m in enumerate(messages)
        if m.get("role") == "user"
        and isinstance(m.get("content"), list)
        and any("toolResult" in c for c in m["content"])
    ]
    for idx in result_turns[:-keep_last]:
        messages[idx]["content"] = [
            ({"text": "[tool_result cleared by microcompact]"}
             if "toolResult" in c else c)
            for c in messages[idx]["content"]
        ]
    return messages


# --------------------------------------------------------------------------- #
# Layer 2 — AutoCompactor                                                       #
# --------------------------------------------------------------------------- #

class AutoCompactor:
    """
    Trigger an LLM-powered summary when token count nears the context ceiling.

    buffer_tokens: headroom below context_window before compaction fires.
                   13 000 matches AUTOCOMPACT_BUFFER_TOKENS in autoCompact.ts:62.
    max_failures:  circuit-breaker—stop retrying after this many consecutive
                   failures (MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3).
    """

    BUFFER_TOKENS = 13_000
    MAX_FAILURES  = 3

    def __init__(self, client: boto3.client, model: str) -> None:
        self.client  = client
        self.model   = model
        self._fails  = 0

    def should_compact(self, token_count: int, context_window: int) -> bool:
        """Return True if autocompact should be attempted."""
        if self._fails >= self.MAX_FAILURES:
            return False   # circuit breaker open
        return token_count >= context_window - self.BUFFER_TOKENS

    def compact(self, messages: list[dict]) -> list[dict] | None:
        """
        Call the LLM to summarize the conversation.

        Returns a replacement messages list on success, None on failure.
        Failure increments the circuit-breaker counter.
        """
        try:
            resp = self.client.converse(
                modelId=self.model,
                system=[{
                    "text": (
                        "Summarize the following conversation into a structured recap. "
                        "Preserve: "
                        "(1) the original user goal, "
                        "(2) all decisions and actions taken, "
                        "(3) every error message verbatim—do NOT omit, paraphrase, or "
                        "collapse error text. Errors are navigation markers."
                    )
                }],
                messages=messages,
                inferenceConfig={"maxTokens": 2048},
            )
            summary = resp["output"]["message"]["content"][0]["text"]
            self._fails = 0  # reset on success
            return [{"role": "user", "content": [{"text": f"[Conversation summary]\n{summary}"}]}]
        except Exception:
            self._fails += 1
            return None

    def reset_failures(self) -> None:
        """Manually reset the circuit breaker (useful in tests)."""
        self._fails = 0


# --------------------------------------------------------------------------- #
# Layer 3 — Reactive Compact                                                    #
# --------------------------------------------------------------------------- #

def reactive_compact(messages: list[dict]) -> list[dict]:
    """
    Emergency compaction called after receiving a 413 / prompt_too_long error.

    Collapses every tool_result user turn to a single-line placeholder.
    Bedrock toolResult blocks → replaced with plain text.
    """
    compacted: list[dict] = []
    for m in messages:
        if (m.get("role") == "user"
                and isinstance(m.get("content"), list)
                and any("toolResult" in c for c in m["content"])):
            compacted.append({
                "role": "user",
                "content": [{"text": "[context cleared by reactive_compact due to 413 error]"}],
            })
        else:
            compacted.append(m)
    return compacted
