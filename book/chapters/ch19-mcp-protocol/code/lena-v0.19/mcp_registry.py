"""
lena-v0.19 · MCP ToolRegistry

把多个 MCP server 的工具统一注册到 Lena 的 ToolRegistry。
工具名格式：{server_name}__{tool_name}，双下划线分隔，避免不同 server 工具名冲突。

设计：
- 并发连接所有 server（asyncio.gather）
- 单个 server 失败不影响其他 server（return_exceptions=True）
- 工具名用 {server}__{tool} 格式，LLM 调用时路由到对应 server
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from mcp_client import MCPClient, MCPTool
from mcp_config import MCP_SERVERS

logger = logging.getLogger(__name__)


@dataclass
class ToolRegistry:
    """
    统一管理多个 MCP server 的工具。

    使用方式：
        registry = ToolRegistry()
        await registry.connect_all()
        tools_for_llm = registry.to_anthropic_tools()
        result = await registry.call("filesystem__read_file", {"path": "/tmp/test.txt"})
        await registry.close_all()
    """

    _clients: dict[str, MCPClient] = field(default_factory=dict, init=False)
    _tools: dict[str, tuple[str, MCPTool]] = field(default_factory=dict, init=False)
    # _tools: tool_key → (server_name, MCPTool)

    async def connect_all(self) -> None:
        """并发连接所有配置的 MCP server，并发现所有工具"""
        # 过滤掉缺少必需环境变量的 server
        servers_to_connect = {}
        for name, cfg in MCP_SERVERS.items():
            required = cfg.get("required_env", [])
            missing = [k for k in required if not os.environ.get(k)]
            if missing:
                logger.info(
                    "MCP server '%s' skipped: missing env vars %s", name, missing
                )
                continue
            servers_to_connect[name] = cfg

        # 并发连接
        tasks = {
            name: asyncio.ensure_future(self._connect_one(name, cfg))
            for name, cfg in servers_to_connect.items()
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for name, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning("MCP server '%s' failed to connect: %s", name, result)

        total_tools = len(self._tools)
        total_servers = len(self._clients)
        logger.info(
            "MCP registry ready: %d tools from %d servers", total_tools, total_servers
        )

    async def _connect_one(self, name: str, cfg: dict) -> None:
        """连接单个 MCP server 并注册其工具"""
        client = MCPClient(name=name, cmd=cfg["cmd"], env=cfg.get("env"))
        await client.connect()
        self._clients[name] = client

        tools = await client.list_tools()
        for tool in tools:
            # 双下划线前缀防止不同 server 工具名冲突
            # 例：filesystem__read_file, github__search_repositories
            key = f"{name}__{tool.name}"
            self._tools[key] = (name, tool)
        logger.info("MCP server '%s': %d tools registered", name, len(tools))

    def to_anthropic_tools(self) -> list[dict]:
        """
        把所有 MCP 工具转换为 Anthropic API 的 tools 格式。
        传给 claude.messages.create(tools=...)
        """
        result = []
        for key, (server_name, tool) in self._tools.items():
            result.append(
                {
                    "name": key,
                    "description": f"[{server_name}] {tool.description}",
                    "input_schema": tool.input_schema
                    or {"type": "object", "properties": {}},
                }
            )
        return result

    async def call(self, tool_key: str, arguments: dict[str, Any]) -> str:
        """调用工具，自动路由到对应 MCP server"""
        if tool_key not in self._tools:
            raise KeyError(f"Unknown tool: {tool_key!r}. Available: {list(self._tools)[:5]}...")
        server_name, tool = self._tools[tool_key]
        client = self._clients[server_name]
        return await client.call_tool(tool.name, arguments)

    def list_tool_names(self) -> list[str]:
        """列出所有可用工具名"""
        return list(self._tools.keys())

    async def close_all(self) -> None:
        """关闭所有 MCP server 连接"""
        await asyncio.gather(
            *(client.close() for client in self._clients.values()),
            return_exceptions=True,
        )
        self._clients.clear()
        self._tools.clear()

    # async context manager 支持
    async def __aenter__(self) -> "ToolRegistry":
        await self.connect_all()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close_all()
