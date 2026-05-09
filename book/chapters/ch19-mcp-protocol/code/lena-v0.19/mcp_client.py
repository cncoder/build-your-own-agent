"""
lena-v0.19 · MCP Client
stdio JSON-RPC 2.0 实现，支持 filesystem / github / brave-search

引用：nanoClaw/nanoclaw/mcp/client.py（R2-openclaw-nanoclaw-comparison.md §5）
完整 5 步流程：spawn → initialize → list_tools → call_tool → _stderr_loop

关键工程细节：_stderr_loop 必须单独排空，防止 PIPE_BUF 满导致子进程死锁。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class MCPError(Exception):
    """MCP JSON-RPC 错误"""

    def __init__(self, error: dict | str) -> None:
        if isinstance(error, dict):
            self.code = error.get("code", -1)
            self.message = error.get("message", "unknown error")
            super().__init__(f"MCP error {self.code}: {self.message}")
        else:
            super().__init__(error)


@dataclass
class MCPTool:
    """从 MCP server 发现的工具"""

    name: str
    description: str
    input_schema: dict


@dataclass
class MCPClient:
    """
    stdio JSON-RPC MCP 客户端。

    使用方式：
        client = MCPClient(name="fs", cmd=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"])
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("read_file", {"path": "/tmp/test.txt"})
        await client.close()

    或使用 async context manager：
        async with MCPClient(name="fs", cmd=[...]) as client:
            tools = await client.list_tools()
    """

    name: str
    cmd: list[str]
    env: dict[str, str] | None = None

    # 内部状态（init=False 不参与构造函数）
    _proc: asyncio.subprocess.Process | None = field(default=None, init=False, repr=False)
    _req_id: int = field(default=0, init=False, repr=False)
    _pending: dict[int, asyncio.Future] = field(default_factory=dict, init=False, repr=False)
    _reader_task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _stderr_task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    # ─────────────────────────────────────────────────────────────────
    # 公共接口
    # ─────────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Step 1 + 2：spawn 子进程并完成握手"""
        full_env = {**os.environ, **(self.env or {})}

        # Step 1: spawn MCP server 子进程
        # stdin/stdout/stderr 全部 PIPE——stderr 必须 PIPE，不能 DEVNULL！
        self._proc = await asyncio.create_subprocess_exec(
            *self.cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,  # ← 关键：必须 PIPE，见 _stderr_loop 注释
            env=full_env,
        )
        logger.debug("MCP server '%s' spawned: pid=%d", self.name, self._proc.pid)

        # 立即启动两个后台 task（并发，不等待）
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())  # ← 单独排空 stderr，防死锁

        # Step 2: 握手
        await self._initialize()

    async def list_tools(self) -> list[MCPTool]:
        """发现 MCP server 暴露的所有工具"""
        result = await self._call("tools/list", {})
        tools = []
        for t in result.get("tools", []):
            tools.append(
                MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                )
            )
        logger.debug("MCP '%s': discovered %d tools", self.name, len(tools))
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """调用工具，返回文本结果"""
        result = await self._call("tools/call", {"name": tool_name, "arguments": arguments})
        if result.get("isError"):
            parts = _extract_text(result.get("content") or [])
            raise MCPError(parts or "tool error")
        return _extract_text(result.get("content") or [])

    async def close(self) -> None:
        """关闭 MCP server 子进程"""
        for task in (self._reader_task, self._stderr_task):
            if task:
                task.cancel()
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._proc.kill()
            except ProcessLookupError:
                pass
        self._proc = None
        self._reader_task = None
        self._stderr_task = None

    # async context manager 支持
    async def __aenter__(self) -> "MCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ─────────────────────────────────────────────────────────────────
    # 内部实现
    # ─────────────────────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _initialize(self) -> None:
        """Step 2：MCP 握手协议"""
        result = await self._call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "lena", "version": "0.19"},
            },
        )
        # 发通知告知 server 初始化完成（无 id = notification，不需要响应）
        await self._notify("notifications/initialized", {})
        server_info = result.get("serverInfo", {})
        logger.info(
            "MCP server '%s' ready: %s v%s",
            self.name,
            server_info.get("name", "?"),
            server_info.get("version", "?"),
        )

    async def _call(self, method: str, params: dict) -> dict:
        """Step 3：发送 JSON-RPC 请求，等待响应"""
        if not self._proc or not self._proc.stdin:
            raise MCPError("MCP client not started")
        rid = self._next_id()
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        msg = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        await self._write(msg)
        try:
            result = await asyncio.wait_for(fut, timeout=30)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise MCPError(f"MCP '{self.name}' call '{method}' timed out")
        if "error" in result:
            raise MCPError(result["error"])
        return result.get("result") or {}

    async def _notify(self, method: str, params: dict) -> None:
        """发送通知（无 id，不需要响应）"""
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._write(msg)

    async def _write(self, obj: dict) -> None:
        """向子进程 stdin 写一行 JSON（加写锁，支持并发调用）"""
        if not self._proc or not self._proc.stdin:
            raise MCPError("MCP client not started")
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        async with self._write_lock:
            self._proc.stdin.write(data)
            await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        """
        Step 4：持续读取子进程 stdout，按行解析 JSON-RPC 响应。
        找到对应 id 的 Future，调用 set_result 唤醒 _call() 的 await。
        """
        assert self._proc and self._proc.stdout
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:  # EOF = server 退出了
                    break
                try:
                    msg = json.loads(line.decode("utf-8").strip())
                except json.JSONDecodeError:
                    continue
                # 有 id 字段 = 响应，匹配对应的 Future
                rid = msg.get("id")
                if rid is not None and rid in self._pending:
                    fut = self._pending.pop(rid)
                    if not fut.done():
                        fut.set_result(msg)
                # else: server 主动发的 notification（无 id），当前实现忽略
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("MCP '%s' reader died: %s", self.name, e)
        finally:
            # 清理所有待处理的 Future，防止泄漏
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(MCPError("MCP connection closed"))
            self._pending.clear()

    async def _stderr_loop(self) -> None:
        """
        Step 5：单独排空 stderr——防止 PIPE_BUF 满导致子进程阻塞死锁。

        为什么必须有这个 loop？
        ─────────────────────────────────────────────────────────────
        MCP server 是子进程，它的 stderr 通过 PIPE 连到内核缓冲区。
        这个缓冲区（PIPE_BUF）通常只有 4KB ~ 64KB。

        如果没有消费者持续读取：
        1. MCP server 往 stderr 写日志（调试信息、初始化输出等）
        2. buffer 写满
        3. MCP server 的 write(stderr_fd, ...) 系统调用阻塞
        4. MCP server 整个进程卡住（无法再处理 stdin 请求、写 stdout 响应）
        5. Lena 这边 await fut 永远等不到 set_result
        6. 整个 MCP 连接死锁，且没有任何错误信息

        症状：MCP server 刚启动正常，随机时间后挂死，无法排查。
        修复：一行代码 asyncio.create_task(self._stderr_loop())。

        这是 MCP 实现中最易遗漏的工程细节。
        ─────────────────────────────────────────────────────────────
        """
        assert self._proc and self._proc.stderr
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").rstrip()
                if text:
                    logger.debug("MCP '%s' stderr: %s", self.name, text)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("MCP '%s' stderr loop ended: %s", self.name, e)


def _extract_text(content: list[dict[str, Any]]) -> str:
    """拼接 MCP tool result 里所有 type=text 的块"""
    parts: list[str] = []
    for block in content:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)
