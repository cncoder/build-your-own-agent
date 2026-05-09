"""
并发工具执行器。
流式抢跑：tool_use block 完整即 add_tool()，不等 message_stop。
参考：StreamingToolExecutor.ts:40（公开仓库）
"""
import asyncio
from typing import Any, Callable, Coroutine

MAX_CONCURRENT_TOOLS = 10  # 对应 CC CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY


class ConcurrentToolExecutor:
    """
    流式抢跑并发执行器。

    使用方式：
        executor = ConcurrentToolExecutor(tool_fn)
        # 流式传输中途，tool_use block 完整时调用：
        executor.add_tool(tool_id, tool_name, tool_input)
        # message_stop 后等待全部完成：
        results = await executor.wait_all()
    """

    def __init__(self, tool_fn: Callable[[str, dict], Coroutine]):
        self.tool_fn = tool_fn
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_TOOLS)
        self.pending: dict[str, asyncio.Task] = {}

    def add_tool(self, tool_id: str, tool_name: str, tool_input: dict) -> None:
        """立即启动工具协程，不阻塞调用方。"""
        task = asyncio.create_task(
            self._run_with_semaphore(tool_id, tool_name, tool_input)
        )
        self.pending[tool_id] = task

    async def _run_with_semaphore(self, tool_id: str, name: str, inp: dict) -> Any:
        async with self.semaphore:  # 并发上限：同时最多 10 个工具
            return await self.tool_fn(name, inp)

    async def wait_all(self) -> dict[str, Any]:
        """等所有工具完成，返回 {tool_id: result}。"""
        results: dict[str, Any] = {}
        for tool_id, task in self.pending.items():
            try:
                results[tool_id] = await task
            except Exception as e:
                results[tool_id] = f"[工具错误] {e}"
        return results
