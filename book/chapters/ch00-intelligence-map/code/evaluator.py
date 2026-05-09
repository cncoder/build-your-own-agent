"""
聪明度自评脚本 — 《从零构建你的 AI Agent》序章配套工具

功能：给任意 agent 打 8 个聪明度维度的分数（0-10），
      输出文本版雷达图，作为全书学习进度仪表盘。

用法：
    python3 evaluator.py                    # 评估 v0.1 起点
    python3 evaluator.py --version v0.24    # 评估 v0.24 终点

Python >= 3.10 required
"""

import sys
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────

@dataclass
class DimensionTest:
    """单个聪明度维度的规格与得分"""
    name: str           # 维度名称（含序号）
    description: str    # 最低可观测行为
    score: int = 0      # 0-10，0 = 完全不具备
    evidence: str = ""  # 得分依据（可选，用于报告）

    def __post_init__(self):
        assert 0 <= self.score <= 10, f"分数须在 0-10 之间，实际: {self.score}"


@dataclass
class IntelligenceEval:
    """8 维聪明度评估器"""
    agent_name: str
    dimensions: list[DimensionTest] = field(default_factory=list)

    def add_dimension(
        self,
        name: str,
        desc: str,
        score: int = 0,
        evidence: str = "",
    ) -> None:
        self.dimensions.append(DimensionTest(name, desc, score, evidence))

    def total_score(self) -> float:
        if not self.dimensions:
            return 0.0
        return sum(d.score for d in self.dimensions) / len(self.dimensions)

    def report(self, verbose: bool = False) -> str:
        lines = [
            "",
            f"{'=' * 50}",
            f"  {self.agent_name} 聪明度评估",
            f"{'=' * 50}",
        ]
        for d in self.dimensions:
            bar = "█" * d.score + "░" * (10 - d.score)
            lines.append(f"  {d.name:14s} [{bar}] {d.score:2d}/10")
            if verbose and d.evidence:
                for line in d.evidence.split("；"):
                    if line.strip():
                        lines.append(f"    → {line.strip()}")
        lines.append(f"{'─' * 50}")
        lines.append(f"  综合得分: {self.total_score():.1f} / 10")
        lines.append(f"{'=' * 50}")
        return "\n".join(lines)


# ─────────────────────────────────────────
# 各版本评估预设
# ─────────────────────────────────────────

def build_v01_eval() -> IntelligenceEval:
    """
    v0.1 Lena：仅 LLM API 调用，无工具，无记忆，无计划，无安全层。
    对应本书 Ch1 结束时的状态。
    """
    ev = IntelligenceEval("Lena v0.1（仅 API 调用）")

    ev.add_dimension(
        "① 推理",
        "多步决策能力",
        score=2,
        evidence="模型本身有推理能力，但 harness 无结构化支持；"
                 "多步任务靠 LLM 内在 instinct，容易在第 3 步以后迷失",
    )
    ev.add_dimension(
        "② 记忆",
        "跨会话保持上下文",
        score=0,
        evidence="无任何持久化存储；每次对话从 [] 开始，前一次偏好全部丢失",
    )
    ev.add_dimension(
        "③ 规划",
        "自主拆解大目标为子步骤",
        score=1,
        evidence="模型偶尔会隐式规划（先做 A 再做 B），但无显式 plan 结构；"
                 "任务复杂度超过 3 步后显著退化",
    )
    ev.add_dimension(
        "④ 协作",
        "委托工作给其他 agent 并整合结果",
        score=0,
        evidence="单会话单线程；无 subagent 机制；无并发任务能力",
    )
    ev.add_dimension(
        "⑤ 学习",
        "通过反馈和经验更新自身行为",
        score=0,
        evidence="无任何反馈收集机制；同样错误下次仍会重犯",
    )
    ev.add_dimension(
        "⑥ 安全",
        "主动降级或请求人类确认",
        score=1,
        evidence="模型本身有安全 instinct，但 harness 无权限边界；"
                 "prompt injection 完全无防御；无 sandbox",
    )
    ev.add_dimension(
        "⑦ 自省",
        "监控自身状态并调整运行策略",
        score=0,
        evidence="context 满了会抛 API 错误（413），不会主动压缩；"
                 "无 token 计数、无 cost 追踪",
    )
    ev.add_dimension(
        "⑧ 跨界",
        "无需修改核心代码即可接入新能力",
        score=1,
        evidence="可以手动改代码加工具，但不是插件式注册；"
                 "新工具需要重启才能生效",
    )

    return ev


def build_v024_eval() -> IntelligenceEval:
    """
    v0.24 Lena：完整通用 agent（Ch24 结束时的目标状态）。
    含 Tool 系统 + RAG + Planning + Subagent + Safety + Always-on + MCP。
    """
    ev = IntelligenceEval("Lena v0.24（通用 agent 终态）")

    ev.add_dimension("① 推理", "多步决策能力",           score=8)
    ev.add_dimension("② 记忆", "跨会话保持上下文",       score=8)
    ev.add_dimension("③ 规划", "自主拆解大目标为子步骤", score=9)
    ev.add_dimension("④ 协作", "委托工作给其他 agent",   score=8)
    ev.add_dimension("⑤ 学习", "通过反馈更新自身行为",   score=9)
    ev.add_dimension("⑥ 安全", "主动降级/请求确认",      score=10)
    ev.add_dimension("⑦ 自省", "监控自身状态并调整",     score=9)
    ev.add_dimension("⑧ 跨界", "插件式接入新能力",       score=10)

    return ev


# ─────────────────────────────────────────
# 版本注册表（方便扩展）
# ─────────────────────────────────────────

VERSION_MAP = {
    "v0.1":  build_v01_eval,
    "v0.24": build_v024_eval,
}


# ─────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────

def main() -> None:
    version = "v0.1"
    verbose = False

    args = sys.argv[1:]
    if "--version" in args:
        idx = args.index("--version")
        if idx + 1 < len(args):
            version = args[idx + 1]
    if "--verbose" in args or "-v" in args:
        verbose = True

    if version not in VERSION_MAP:
        print(f"未知版本 '{version}'。可用版本：{list(VERSION_MAP.keys())}")
        sys.exit(1)

    ev = VERSION_MAP[version]()
    print(ev.report(verbose=verbose))

    print("\n  提示：读完每一章后，把对应维度的分数更新为该章 Lena 能达到的水平。")
    print("  这个脚本是你的进度仪表盘。")


if __name__ == "__main__":
    main()
