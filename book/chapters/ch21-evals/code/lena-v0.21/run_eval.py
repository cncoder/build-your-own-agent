"""
lena-v0.21/run_eval.py
CLI 入口，供 GitHub Actions 和本地调用
"""
import argparse
import asyncio
import json
import random
from pathlib import Path

import anthropic

from eval_runner import EvalRunner, EvalCase
from judge import model_grade
from scorer import ThreeDimScore
from regression import BaselineManager

PASS_THRESHOLD = 0.75   # composite 低于此值 CI 失败


async def run_agent_stub(input_text: str) -> tuple[str, float]:
    """
    占位符：替换为你的实际 Lena agent 调用。
    返回 (output_text, cost_usd)
    """
    # 实际接入时替换为：
    # from lena import Lena
    # lena = Lena()
    # result = await lena.step(input_text)
    # return result.text, result.cost_usd
    raise NotImplementedError(
        "替换为实际的 Lena agent 调用。参考注释中的接入方式。"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Lena Eval Runner")
    parser.add_argument("--dataset", default="golden-dataset.json",
                        help="golden dataset JSON 文件路径")
    parser.add_argument("--sample-size", type=int, default=None,
                        help="随机采样条数（不指定 = 全量）")
    parser.add_argument("--output", default="eval-report.json",
                        help="输出报告路径")
    parser.add_argument("--baseline", default="baseline/latest.json",
                        help="baseline JSON 路径")
    parser.add_argument("--update-baseline", action="store_true",
                        help="运行完成后更新 baseline（仅 main branch 调用）")
    args = parser.parse_args()

    # 加载 dataset
    cases_raw = json.loads(Path(args.dataset).read_text())
    cases = [EvalCase(**c) for c in cases_raw]
    if args.sample_size and args.sample_size < len(cases):
        cases = random.sample(cases, args.sample_size)
    print(f"Running eval on {len(cases)} cases...")

    # 运行 eval
    runner = EvalRunner(cases)
    results = await runner.run(run_agent_stub)

    # 评分
    client = anthropic.Anthropic()
    baseline = BaselineManager(args.baseline)
    report: dict = {"cases": [], "summary": {}}
    scores_3d: list[ThreeDimScore] = []

    for r in results:
        quality = r.score
        judge_info = {}

        if r.case.rubric:
            j = await model_grade(r.case.input, r.case.rubric, r.actual, client)
            quality = j.get("overall", r.score)
            judge_info = {"judge_model": j.get("judge_model"), "reason": j.get("reason")}

        s3d = ThreeDimScore.compute(quality, r.latency_ms, r.cost_usd)
        delta = baseline.compare(r.case.id, s3d.composite)
        scores_3d.append(s3d)

        report["cases"].append({
            "id": r.case.id,
            "tags": r.case.tags,
            "score": round(s3d.composite, 4),
            "quality": round(s3d.quality, 4),
            "latency": round(s3d.latency, 4),
            "cost": round(s3d.cost, 4),
            "latency_ms": round(r.latency_ms, 1),
            "cost_usd": round(r.cost_usd, 6),
            "delta": round(delta, 4),
            "regression": delta < -0.05,
            **judge_info,
        })

    def avg(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    summary = {
        "composite": round(avg([s.composite for s in scores_3d]), 4),
        "quality":   round(avg([s.quality   for s in scores_3d]), 4),
        "latency":   round(avg([s.latency   for s in scores_3d]), 4),
        "cost":      round(avg([s.cost      for s in scores_3d]), 4),
        "regressions": sum(1 for c in report["cases"] if c["regression"]),
        "total": len(results),
        "pass": avg([s.composite for s in scores_3d]) >= PASS_THRESHOLD,
    }
    report["summary"] = summary

    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False))

    # 打印摘要
    status = "PASS" if summary["pass"] else "FAIL"
    print(f"\n{'='*50}")
    print(f"Status:     {status}")
    print(f"Composite:  {summary['composite']:.3f} (threshold: {PASS_THRESHOLD})")
    print(f"Quality:    {summary['quality']:.3f}")
    print(f"Latency:    {summary['latency']:.3f}")
    print(f"Cost:       {summary['cost']:.3f}")
    print(f"Regressions:{summary['regressions']}/{summary['total']}")
    print(f"Report:     {args.output}")

    if args.update_baseline:
        baseline.update({c["id"]: c["score"] for c in report["cases"]})

    # CI 门控：失败时以非零退出码退出
    if not summary["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
