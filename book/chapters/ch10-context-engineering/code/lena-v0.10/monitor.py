"""
Token usage monitor for Lena v0.10.

Tracks per-session totals, compaction count, and cache hit rate.
Designed to print one summary line per turn so progress is visible in
the terminal during the 50-round test.
"""

from __future__ import annotations

from cache import TokenUsage


class TokenMonitor:
    """
    Accumulate token usage across turns and report live stats.

    Usage:
        monitor = TokenMonitor()
        for turn in range(50):
            response = lena.run(...)
            usage = parse_usage(response.usage.__dict__, "anthropic")
            monitor.record(usage)
            print(monitor.summary_line(turn + 1))
    """

    def __init__(self) -> None:
        self._total_input:  int = 0
        self._cache_reads:  int = 0
        self._cache_writes: int = 0
        self._output_total: int = 0
        self._compactions:  int = 0

    def record(self, usage: TokenUsage) -> None:
        """Accumulate one turn's usage."""
        self._total_input  += usage.input_tokens
        self._output_total += usage.output_tokens
        self._cache_reads  += usage.cache_read_tokens
        self._cache_writes += usage.cache_write_tokens

    def record_compaction(self) -> None:
        """Increment the compaction counter (call after any compaction fires)."""
        self._compactions += 1

    @property
    def cache_hit_rate(self) -> float:
        """Session-level cache hit rate (cache_read / total_input)."""
        if self._total_input == 0:
            return 0.0
        return self._cache_reads / self._total_input

    def summary_line(self, turn: int) -> str:
        """Single-line summary suitable for terminal output."""
        return (
            f"Turn {turn:2d} | "
            f"input: {self._total_input:7,} | "
            f"cache_hit: {self.cache_hit_rate:5.1%} | "
            f"compactions: {self._compactions}"
        )

    def full_report(self) -> str:
        """End-of-session summary."""
        return (
            f"=== Session Summary ===\n"
            f"Total input tokens:  {self._total_input:,}\n"
            f"Total output tokens: {self._output_total:,}\n"
            f"Cache reads:         {self._cache_reads:,}\n"
            f"Cache writes:        {self._cache_writes:,}\n"
            f"Cache hit rate:      {self.cache_hit_rate:.1%}\n"
            f"Compactions fired:   {self._compactions}\n"
        )
