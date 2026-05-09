"""
supervisor_demo.py：SupervisorAgent（agent-as-tools 模式）演示

运行：
  python examples/supervisor_demo.py
"""

from __future__ import annotations

import json

from spec_kit.supervisor import SupervisorAgent


# ── Mock 专用 agent 实现 ──────────────────────────────────────────────────

class MockTradingAgent:
    @property
    def name(self) -> str:
        return "trader"

    @property
    def description(self) -> str:
        return "量化交易专用 agent，处理价格查询、仓位管理、交易信号分析"

    def handle(self, task: str) -> str:
        return json.dumps({
            "agent": "TradingBot",
            "task": task,
            "result": "BTC/USDT 当前 RSI=42，MACD 金叉，BB 位置中轨以上。多头信号置信度 0.72，建议小仓位试多。"
        }, ensure_ascii=False)


class MockNewsAgent:
    @property
    def name(self) -> str:
        return "news"

    @property
    def description(self) -> str:
        return "新闻采集和摘要 agent，处理最新资讯、市场情绪分析"

    def handle(self, task: str) -> str:
        return json.dumps({
            "agent": "NewsBot",
            "task": task,
            "result": "近 24h BTC 新闻：1）美联储暗示暂停加息，市场情绪偏多；2）大型机构增持 BTC 3万枚；3）ETF 资金净流入 $450M。"
        }, ensure_ascii=False)


class MockDevOpsAgent:
    @property
    def name(self) -> str:
        return "devops"

    @property
    def description(self) -> str:
        return "DevOps 监控 agent，处理 AWS 告警、服务健康检查、自动恢复"

    def handle(self, task: str) -> str:
        return json.dumps({
            "agent": "DevOpsBot",
            "task": task,
            "result": "当前无活跃 ALARM，所有服务正常。最近一次告警：昨日 03:15 ECS 内存告警，已自动重启恢复。"
        }, ensure_ascii=False)


# ── 主程序 ────────────────────────────────────────────────────────────────

def main():
    print("SupervisorAgent 演示（agent-as-tools 模式）")
    print("=" * 50)

    supervisor = SupervisorAgent(
        agents=[MockTradingAgent(), MockNewsAgent(), MockDevOpsAgent()]
    )

    test_queries = [
        "BTC 现在值得买吗？结合技术面和新闻来分析。",
        "帮我检查一下服务器状态是否正常。",
        "今天有什么重要的加密货币新闻？",
    ]

    for query in test_queries:
        print(f"\n用户：{query}")
        print("-" * 40)
        result = supervisor.handle(query)
        print(f"Supervisor：{result}")
        print()


if __name__ == "__main__":
    main()
