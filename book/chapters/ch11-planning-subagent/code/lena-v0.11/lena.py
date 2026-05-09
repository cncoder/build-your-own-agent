"""
lena-v0.11：自主拆任务 + 并发派 3 子 agent + 多 agent 拓扑可视化

运行：python3 lena.py
需要：
  - AWS credentials（~/.aws/credentials 或环境变量）
  - Bedrock 访问权限（us-west-2，claude-sonnet-4-6 + claude-haiku-4-5）

Demo 功能：
  - 多 agent 拓扑实时可视化（终端 ASCII，节点高亮激活者）
  - 输入"调研 X Y Z"类任务可触发并发 Worker
  - 输入"exit"退出
"""
import asyncio
import sys
import time
from typing import Optional

from orchestrator import Orchestrator


# ── 多 agent 拓扑可视化 ────────────────────────────────────────────────────────

class TopologyDisplay:
    """
    终端实时多 agent 拓扑图。
    不依赖 rich/curses，零额外依赖。

    设计说明：
    - Orchestrator 节点始终显示（顶层）
    - Worker 节点在 on_worker_start 时动态添加
    - 高亮（★）标记当前激活的节点
    """

    def __init__(self):
        self._workers: dict[str, dict] = {}    # agent_id → {task, status, elapsed}
        self._orchestrator_status = "idle"     # idle | planning | aggregating

    def orchestrator_planning(self):
        self._orchestrator_status = "planning"
        self._render()

    def orchestrator_aggregating(self):
        self._orchestrator_status = "aggregating"
        self._render()

    def orchestrator_done(self):
        self._orchestrator_status = "idle"

    def on_worker_start(self, agent_id: str, task: str):
        self._workers[agent_id] = {"task": task[:38], "status": "running", "elapsed": None}
        self._render()

    def on_worker_done(self, agent_id: str, elapsed: float, error: Optional[str]):
        if agent_id in self._workers:
            self._workers[agent_id]["status"] = "error" if error else "done"
            self._workers[agent_id]["elapsed"] = elapsed
        self._render()

    def _render(self):
        # 顶部留一个空行，让输出有呼吸感
        print()

        # Orchestrator 节点（顶层）
        orc_icon = {
            "idle": "○",
            "planning": "★",       # 高亮：正在规划
            "aggregating": "★",    # 高亮：正在汇总
        }.get(self._orchestrator_status, "○")

        orc_label = {
            "idle": "Orchestrator (Lena)",
            "planning": "Orchestrator (Lena) ← 规划中...",
            "aggregating": "Orchestrator (Lena) ← 汇总中...",
        }.get(self._orchestrator_status, "Orchestrator (Lena)")

        print(f"  {orc_icon} {orc_label}")

        if not self._workers:
            return

        # Worker 节点（带连接线）
        worker_list = list(self._workers.items())
        for i, (aid, info) in enumerate(worker_list):
            is_last = i == len(worker_list) - 1
            branch = "└─" if is_last else "├─"

            status_icon = {
                "running": "★",   # 高亮：激活状态
                "done": "✓",
                "error": "✗",
            }.get(info["status"], "?")

            elapsed_str = f" ({info['elapsed']:.1f}s)" if info["elapsed"] else ""
            print(f"     {branch} {status_icon} [{aid}] {info['task']}{elapsed_str}")

        print()


# ── 主循环 ─────────────────────────────────────────────────────────────────────

async def main():
    display = TopologyDisplay()

    def on_worker_start(agent_id: str, task: str):
        display.on_worker_start(agent_id, task)

    def on_worker_done(agent_id: str, elapsed: float, error: Optional[str]):
        display.on_worker_done(agent_id, elapsed, error)

    orchestrator = Orchestrator(
        orchestrator_model="us.anthropic.claude-sonnet-4-6",
        worker_model="us.anthropic.claude-haiku-4-5",
        on_worker_start=on_worker_start,
        on_worker_done=on_worker_done,
    )

    print("\nLena v0.11 — Orchestrator-Worker Mode")
    print("=" * 55)
    print("示例：调研 LangGraph CrewAI AutoGen 并对比")
    print("输入 'exit' 退出\n")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("再见！")
            break

        display.orchestrator_planning()
        start = time.time()

        result = await orchestrator.execute(user_input)

        display.orchestrator_aggregating()
        total = time.time() - start
        display.orchestrator_done()

        print(f"[完成] 总耗时 {total:.1f}s\n")
        print("─" * 55)
        print(result)
        print("─" * 55 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
