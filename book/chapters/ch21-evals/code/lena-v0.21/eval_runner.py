"""
lena-v0.21/eval_runner.py
最小 Eval Runner — code-based grader + 延迟/成本记录
"""
from dataclasses import dataclass, field
from typing import Callable, Any, Awaitable
import time
import asyncio


@dataclass
class EvalCase:
    id: str
    input: str
    tags: list[str] = field(default_factory=list)
    # code-based grader 用
    expected_contains: list[str] = field(default_factory=list)
    expected_not_contains: list[str] = field(default_factory=list)
    # model-based grader 用（空字符串表示不使用 LLM judge）
    rubric: str = ""


@dataclass
class CaseResult:
    case: EvalCase
    actual: str
    score: float        # 0.0–1.0，code-based grader 结果
    latency_ms: float
    cost_usd: float


class EvalRunner:
    def __init__(self, cases: list[EvalCase]):
        self.cases = cases

    async def run(
        self,
        agent_fn: Callable[[str], Awaitable[tuple[str, float]]],
    ) -> list[CaseResult]:
        """
        agent_fn: async (input: str) -> (output: str, cost_usd: float)
        """
        results = []
        for case in self.cases:
            t0 = time.time()
            actual, cost = await agent_fn(case.input)
            latency_ms = (time.time() - t0) * 1000

            score = self._code_grade(case, actual)
            results.append(CaseResult(
                case=case,
                actual=actual,
                score=score,
                latency_ms=latency_ms,
                cost_usd=cost,
            ))
            print(f"[{case.id}] score={score:.2f} latency={latency_ms:.0f}ms cost=${cost:.4f}")

        return results

    def _code_grade(self, case: EvalCase, actual: str) -> float:
        """
        code-based grader：字符串包含检查
        returns 0.0–1.0（所有检查的平均通过率）
        """
        scores: list[float] = []

        if case.expected_contains:
            hits = sum(1 for s in case.expected_contains if s in actual)
            scores.append(hits / len(case.expected_contains))

        if case.expected_not_contains:
            misses = sum(1 for s in case.expected_not_contains if s not in actual)
            scores.append(misses / len(case.expected_not_contains))

        # 没有任何 code-based 约束的用例，默认通过（等待 model-based grader）
        return sum(scores) / len(scores) if scores else 1.0
