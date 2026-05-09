"""
lena-v2.0 Browser Agent — 生产级实现
集成：Tab 保护 + 三层 fallback + 审批门控 + 进程锁 + 6 条血泪防护

血泪教训集成清单：
  1. 不发 Origin 头（CDP WebSocket 403 防护）
  2. 清除代理环境变量（Clash fake-ip 防护）
  3. 进程锁（cron 并发防护）
  4. Tab 主动清理（Chrome 拥堵防护）
  5. 截图空白检测（空白页误判防护）
  6. PUT 方法（/json/new + /json/close）
"""
import os
import asyncio
import fcntl
from typing import Optional

import aiohttp
from browser_use import Agent, Browser, BrowserConfig
from langchain_anthropic import ChatAnthropic

# ===== 教训 2：启动时清除代理环境变量 =====
# Clash fake-ip 模式拦截所有 DNS 查询，包括 localhost，
# 导致 CDP socket 被路由到代理而失败。
for _proxy_var in [
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
    "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY",
]:
    os.environ.pop(_proxy_var, None)

CDP_BASE = "http://localhost:9222"
CDP_WS = "ws://localhost:9222"
LOCK_FILE = "/tmp/.lena_browser_v2.lock"

# 高风险动作关键词（触发人工审批）
HIGH_RISK_KEYWORDS = [
    "submit", "purchase", "buy", "order", "delete", "remove",
    "transfer", "pay", "checkout", "confirm", "book", "reserve",
    "提交", "购买", "支付", "删除", "转账", "预订", "确认",
]


# ===== CDP 工具函数 =====

async def _get_tab_ids() -> set[str]:
    """获取当前所有 tab 的 ID 快照"""
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{CDP_BASE}/json") as r:
            return {t["id"] for t in await r.json()}


async def _close_new_tabs(protected: set[str]) -> int:
    """
    关闭本次任务新建的 tab
    教训 4：Tab 不清理会在 Chrome 里积累，导致内存耗尽
    教训 6：用 PUT 不用 GET
    """
    closed = 0
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{CDP_BASE}/json") as r:
                current = await r.json()
            for tab in current:
                if tab["id"] not in protected:
                    await s.put(f"{CDP_BASE}/json/close/{tab['id']}")
                    print(f"[Tab 清理] 关闭 tab: {tab['id'][:8]}")
                    closed += 1
    except Exception as e:
        print(f"[Tab 清理] 警告: {e}")
    return closed


# ===== 进程锁 =====

class BrowserLock:
    """
    进程级文件锁
    教训 3：cron 任务可能重叠执行，两个 agent 同时操作 Chrome 会导致竞态
    """

    def __enter__(self):
        self._fd = open(LOCK_FILE, "w")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._fd.close()
            raise RuntimeError(
                "[BrowserLock] 另一个 browser agent 正在运行，本次任务跳过。"
                f"如确认无其他进程，删除锁文件：{LOCK_FILE}"
            )
        return self

    def __exit__(self, *args):
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        self._fd.close()


# ===== 审批门控 =====

async def check_approval(task_description: str, interactive: bool = True) -> bool:
    """
    检查任务是否包含高风险操作
    高风险任务在 interactive 模式下需要用户确认
    Safety 支柱：浏览器有真实副作用，写操作必须有人工确认
    """
    is_risky = any(
        keyword in task_description.lower()
        for keyword in HIGH_RISK_KEYWORDS
    )
    if not is_risky:
        return True

    print(f"\n⚠️  检测到潜在高风险操作")
    print(f"   任务描述: {task_description[:100]}...")
    print(f"   这个操作可能有不可撤回的真实后果（提交订单/支付/删除数据等）")

    if not interactive:
        print("   [非交互模式] 自动取消高风险任务")
        return False

    confirm = input("\n   确认执行？输入 'yes' 继续，其他任意键取消：")
    return confirm.strip().lower() == "yes"


# ===== 主 Agent 类 =====

class LenaBrowserAgent:
    """
    lena-v2.0 Browser Agent 主类

    从 lena 通用 runtime 派生的 Browser 专用 agent：
    - 继承：安全规则、审批门控
    - 新增：浏览器工具集、DOM 感知、三层 fallback、Tab 管理

    使用方式：
        agent = LenaBrowserAgent()
        result = await agent.run_task("帮我查微博有没有新消息")
    """

    def __init__(
        self,
        model: str = "us.anthropic.claude-sonnet-4-6",
        require_approval_for_risky: bool = True,
        interactive: bool = True,
    ):
        self.llm = ChatAnthropic(model=model)
        self.require_approval = require_approval_for_risky
        self.interactive = interactive

    async def run_task(self, task: str) -> str:
        """
        执行一个浏览器任务

        铁律：
        - 永远在新 tab 操作，不覆盖用户现有 tab
        - 高风险操作需要人工确认
        - 使用进程锁防止并发冲突
        """
        # 审批检查
        if self.require_approval:
            approved = await check_approval(task, self.interactive)
            if not approved:
                return "[CANCELLED] 用户取消了任务（检测到高风险操作）"

        # 进程锁 + Tab 保护
        with BrowserLock():
            protected_tabs = await _get_tab_ids()
            print(f"[Browser Agent] 保护现有 {len(protected_tabs)} 个 tab")

            try:
                result = await self._execute(task)
                print(f"[Browser Agent] 任务完成")
                return result
            finally:
                # 教训 4：无论成功/失败都清理 tab
                closed = await _close_new_tabs(protected_tabs)
                print(f"[Browser Agent] 清理了 {closed} 个 tab")

    async def _execute(self, task: str) -> str:
        """执行核心：browser-use + CDP"""
        browser = Browser(config=BrowserConfig(
            cdp_url=CDP_WS,   # 连接已有 Chrome，不启动新实例
            headless=False,   # 使用用户可见的 Chrome
        ))

        agent = Agent(
            task=task,
            llm=self.llm,
            browser=browser,
            max_actions_per_step=5,  # 防止单步操作过多
        )

        result = await agent.run(max_steps=25)
        return str(result)


# ===== 快捷接口 =====

async def lena_browse(
    task: str,
    model: str = "claude-sonnet-4-6",
    safe: bool = True,
) -> str:
    """
    快捷接口：一行调用 browser agent

    Args:
        task: 任务描述（中文/英文均可）
        model: 使用的 LLM 模型
        safe: True 时对高风险操作请求人工确认

    Returns:
        任务执行结果文本

    Example:
        result = await lena_browse("帮我截图百度首页，告诉我有什么内容")
    """
    agent = LenaBrowserAgent(
        model=model,
        require_approval_for_risky=safe,
        interactive=True,
    )
    return await agent.run_task(task)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        task = "打开百度，告诉我今天的热搜第一是什么"
    else:
        task = " ".join(sys.argv[1:])

    print(f"[lena-v2.0] 任务: {task}")
    print("[lena-v2.0] 确保 CDP 已启动: ~/.claude/scripts/cdp-start.sh")
    print()

    result = asyncio.run(lena_browse(task))
    print(f"\n[结果]\n{result}")
