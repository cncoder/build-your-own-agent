"""
lena-v0.19 · MCP Server 配置

三个内置 MCP server：filesystem / github / brave-search

安全原则：
- filesystem 只暴露 /tmp，不暴露 /（最小权限原则）
- github 和 brave-search 需要 API key，key 从环境变量读取，不硬编码
"""

from __future__ import annotations

import os

# MCP server 配置表
# key：server 名称（用于工具名前缀和日志）
# cmd：启动命令（npx 会自动下载 npm 包，-y 跳过确认）
# env：额外环境变量（会与系统环境变量合并）
MCP_SERVERS: dict[str, dict] = {
    "filesystem": {
        "cmd": [
            "npx",
            "-y",
            "@modelcontextprotocol/server-filesystem",
            "/tmp",  # ← 只暴露 /tmp，最小权限原则（不要用 /）
        ],
        "env": {},
        "description": "读写本地文件系统（限 /tmp）",
    },
    "github": {
        "cmd": [
            "npx",
            "-y",
            "@modelcontextprotocol/server-github",
        ],
        "env": {
            # GITHUB_TOKEN 从系统环境变量读取，未设置时为空字符串
            # 未设置时 github server 仍可用但有 rate limit
            "GITHUB_PERSONAL_ACCESS_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
        },
        "description": "搜索 GitHub 仓库和文件（GITHUB_TOKEN 可选，未设置有 rate limit）",
    },
    "brave-search": {
        "cmd": [
            "npx",
            "-y",
            "@modelcontextprotocol/server-brave-search",
        ],
        "env": {
            # BRAVE_API_KEY 必须设置，否则 server 启动失败
            "BRAVE_API_KEY": os.environ.get("BRAVE_API_KEY", ""),
        },
        "description": "Brave 网页搜索（需要设置 BRAVE_API_KEY 环境变量）",
        "required_env": ["BRAVE_API_KEY"],  # 用于启动前检查
    },
}
