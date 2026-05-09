"""
lena-v0.21/regression.py
Baseline 对比：检测 eval 分数退化
"""
import json
from pathlib import Path

REGRESSION_THRESHOLD = -0.05   # 下降超过 5% 视为退化


class BaselineManager:
    def __init__(self, baseline_path: str = "baseline/latest.json"):
        self.path = Path(baseline_path)
        self.baseline: dict[str, float] = {}
        if self.path.exists():
            self.baseline = json.loads(self.path.read_text())

    def compare(self, case_id: str, current_score: float) -> float:
        """
        返回 delta（正数 = 进步，负数 = 退化）
        首次出现的 case_id 没有 baseline，返回 delta = 0
        """
        if case_id not in self.baseline:
            return 0.0
        return current_score - self.baseline[case_id]

    def is_regression(self, delta: float) -> bool:
        return delta < REGRESSION_THRESHOLD

    def update(self, results: dict[str, float]) -> None:
        """
        更新 baseline（仅在 main branch 成功合并后调用）
        results: {case_id: composite_score}
        """
        self.baseline.update(results)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.baseline, indent=2))
        print(f"Baseline updated: {len(results)} cases → {self.path}")
