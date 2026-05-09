"""
lena-v0.21/scorer.py
三维度归一化评分：quality / latency / cost → composite
"""
from dataclasses import dataclass


@dataclass
class ThreeDimScore:
    quality: float     # 0–1
    latency: float     # 0–1（越高越好，已归一化）
    cost: float        # 0–1（越高越好，已归一化）
    composite: float   # 加权平均

    @classmethod
    def compute(
        cls,
        quality_raw: float,
        latency_ms: float,
        cost_usd: float,
        # 基准值：用 Lena v0.1 的历史数据（初始 agent）
        latency_baseline_ms: float = 3000.0,
        cost_baseline_usd: float = 0.005,
        # 权重：quality 最重要，latency 和 cost 各占 25%
        weights: tuple[float, float, float] = (0.5, 0.25, 0.25),
    ) -> "ThreeDimScore":
        """
        latency 和 cost 都是"越低越好"，所以归一化为 baseline/actual
        超过 baseline 的值 cap 到 1.0（比 baseline 快/省 不加分）
        """
        lat_score = min(1.0, latency_baseline_ms / max(latency_ms, 1.0))
        cst_score = min(1.0, cost_baseline_usd / max(cost_usd, 1e-9))
        composite = weights[0] * quality_raw + weights[1] * lat_score + weights[2] * cst_score
        return cls(
            quality=quality_raw,
            latency=lat_score,
            cost=cst_score,
            composite=composite,
        )

    def __str__(self) -> str:
        return (
            f"Score(quality={self.quality:.3f}, latency={self.latency:.3f}, "
            f"cost={self.cost:.3f}) → composite={self.composite:.3f}"
        )
