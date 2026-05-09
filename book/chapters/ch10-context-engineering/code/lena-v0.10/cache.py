"""
Prompt caching utilities for Lena v0.10.

Two responsibilities:
1. parse_usage() — normalize the three providers' different cache field names
   into a unified TokenUsage.
2. build_request_with_caching() — construct API kwargs with exactly one
   message-level cache_control marker (one-marker discipline).

Provider field map:
  Anthropic  cache_read_input_tokens / cache_creation_input_tokens  (root-level)
  OpenAI     prompt_tokens_details.cached_tokens                     (nested dict)
  DeepSeek   prompt_cache_hit_tokens / prompt_cache_miss_tokens      (root-level)

Source reference: claude.ts:358 (getCacheControl), claude.ts:3078 (one-marker limit),
                  nanoclaw/core/llm.py:18-38 (_parse_openai_usage).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenUsage:
    input_tokens:        int = 0
    output_tokens:       int = 0
    cache_read_tokens:   int = 0
    cache_write_tokens:  int = 0

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of input tokens served from cache (0.0–1.0)."""
        if self.input_tokens == 0:
            return 0.0
        return self.cache_read_tokens / self.input_tokens


def parse_usage(raw: dict, provider: str) -> TokenUsage:
    """
    Map provider-specific usage dict to a unified TokenUsage.

    Args:
        raw:      The raw usage dict from the API response.
        provider: One of "anthropic", "openai", "deepseek".

    Returns:
        TokenUsage with all four fields populated.
    """
    u = TokenUsage(
        input_tokens=raw.get("input_tokens") or raw.get("prompt_tokens", 0),
        output_tokens=raw.get("output_tokens") or raw.get("completion_tokens", 0),
    )
    if provider == "anthropic":
        u.cache_read_tokens  = raw.get("cache_read_input_tokens",     0)
        u.cache_write_tokens = raw.get("cache_creation_input_tokens", 0)
    elif provider == "openai":
        # OpenAI nests cache stats inside prompt_tokens_details
        details = raw.get("prompt_tokens_details") or {}
        u.cache_read_tokens = details.get("cached_tokens", 0)
        # OpenAI does not expose a separate cache-write field
    elif provider == "deepseek":
        u.cache_read_tokens  = raw.get("prompt_cache_hit_tokens",  0)
        u.cache_write_tokens = raw.get("prompt_cache_miss_tokens", 0)
    return u


def build_request_with_caching(
    system_prompt: str,
    tool_definitions: list[dict],
    messages: list[dict],
) -> dict:
    """
    Construct kwargs for client.messages.create() with caching enabled.

    One-marker discipline: exactly one message-level cache_control per request.
    We place it on the last tool definition—the longest stable prefix in the
    request. The system prompt is passed as a plain string; the SDK handles
    top-level caching automatically when cache_control is set at the root level.

    Rationale: placing multiple message-level cache_control markers causes the
    last one to silently override the earlier ones (claude.ts:3078). Using
    exactly one avoids this footgun.
    """
    # Deep-copy tool list to avoid mutating the caller's objects
    tools = [t.copy() for t in tool_definitions]
    if tools:
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}

    return {
        "system": system_prompt,
        "tools": tools if tools else [],
        "messages": messages,
    }
