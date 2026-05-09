"""
tools.py — Lena v0.4 工具实现（四工具版）

工具：
  read_file    — 读取文件内容（is_read_only=True, max_result_size=None 防 Read 循环）
  write_file   — 写入文件（is_read_only=False, is_destructive=True）
  shell        — 执行 shell 命令（is_concurrency_safe=False，需串行，安全白名单）
  web_search   — DuckDuckGo 搜索（is_read_only=True, is_concurrency_safe=True）

安全设计说明（参考 R2 nanoClaw ShellSandbox）：
  shell 工具只允许白名单命令，阻断危险操作（rm/sudo/curl 等）。
  生产场景应添加 R2 §4 描述的三层过滤（BLOCKED/CONFIRM/EXECUTE）。

案例 4.2 教训：
  HA 华为空调 MQTT bug 根因：类型不一致（{"on":true} vs {"on":1}）。
  Pydantic 校验在 registry.execute() 层拦截这类 bug：
  如果工具定义了 on: bool，传 on=1 会自动转换为 True（Pydantic v2 默认行为）。
  如果工具定义了 on: Literal[True, False]，传 1 会报 ValidationError 而不是静默通过。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from registry import registry

# ── 工具 1：read_file ──────────────────────────────────────────────────────────
# max_result_size_chars=None（等效 Infinity）
# 设计理由：如果对 read_file 的结果也截断，LLM 会反复调用 read_file 读后续内容，
# 形成"Read 循环"。Claude Code FileReadTool.maxResultSizeChars = Infinity 同理。
# 参考：R1 §5 toolResultStorage.ts:30

class ReadFileInput(BaseModel):
    path: str = Field(description="文件路径（绝对路径或相对于当前目录）")
    encoding: str = Field(default="utf-8", description="文件编码，默认 utf-8")


@registry.tool(
    description="读取本地文件的内容。支持文本文件，返回完整内容。",
    is_read_only=True,
    is_destructive=False,
    is_concurrency_safe=True,
    max_result_size_chars=None,  # Infinity：防 Read 循环
)
def read_file(input: ReadFileInput) -> str:
    path = Path(input.path)
    if not path.exists():
        return f"错误：文件不存在 {input.path}"
    if not path.is_file():
        return f"错误：{input.path} 不是文件"
    try:
        content = path.read_text(encoding=input.encoding)
        lines = content.splitlines()
        header = f"=== {input.path} ({len(lines)} 行) ===\n"
        return header + content
    except Exception as e:
        return f"读取失败：{e}"


# ── 工具 2：write_file ─────────────────────────────────────────────────────────

class WriteFileInput(BaseModel):
    path: str = Field(description="写入路径（绝对路径或相对路径）")
    content: str = Field(description="写入内容")
    append: bool = Field(default=False, description="True=追加模式，False=覆盖模式")


@registry.tool(
    description="将内容写入本地文件。覆盖或追加模式可选。",
    is_read_only=False,
    is_destructive=True,   # 覆盖模式不可逆（Ch10 安全专章会拦截此标志）
    is_concurrency_safe=False,  # 同一文件并发写会竞争
    max_result_size_chars=500,
)
def write_file(input: WriteFileInput) -> str:
    path = Path(input.path)
    # 自动创建父目录
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if input.append else "w"
    try:
        with open(path, mode, encoding="utf-8") as f:
            f.write(input.content)
        action = "追加" if input.append else "写入"
        return f"成功{action} {len(input.content)} 字符到 {input.path}"
    except Exception as e:
        return f"写入失败：{e}"


# ── 工具 3：shell ──────────────────────────────────────────────────────────────
# ⚠️ 安全警告：shell 工具是最危险的工具。
# 生产场景必须在 isDestructive=True 基础上添加：
#   1. 命令白名单（只允许 ls/cat/grep/find 等安全命令）
#   2. 用户确认弹框（Ch10 权限专章的 PermissionDecision 流程）
# 本章为教学目的使用简单白名单，不适合生产。

SHELL_ALLOWED_PREFIXES = (
    "ls", "cat", "grep", "find", "echo", "pwd", "wc", "head", "tail",
    "date", "whoami", "uname", "df", "du", "ps", "env", "which", "file",
    "python3 -c", "python3 --version",
)

SHELL_BLOCKED_PATTERNS = (
    "rm ", "sudo ", "curl ", "wget ", "ssh ", "scp ", "chmod ", "chown ",
    "mkfs", "dd ", "kill ", "pkill ", "> /", "| bash", "| sh",
)


class ShellInput(BaseModel):
    command: str = Field(description="要执行的 shell 命令")
    timeout: int = Field(default=30, description="超时秒数，默认 30")


@registry.tool(
    description=(
        "执行 shell 命令并返回输出。"
        "⚠️ 仅允许白名单命令（ls/cat/grep/find/echo 等安全操作）。"
        "危险命令（rm/sudo/curl 等）会被阻断。"
    ),
    is_read_only=False,     # shell 可能修改状态
    is_destructive=True,    # 不可逆（Ch10 会拦截，要求用户确认）
    is_concurrency_safe=False,  # 串行执行，防竞争
    max_result_size_chars=4000,
)
def shell(input: ShellInput) -> str:
    cmd = input.command.strip()

    # 安全检查：阻断危险命令
    for blocked in SHELL_BLOCKED_PATTERNS:
        if blocked in cmd:
            return (
                f"🚫 安全阻断：命令包含危险操作 '{blocked.strip()}'。\n"
                "如需执行此操作，请直接在终端中手动执行。"
            )

    # 白名单检查：只允许已知安全命令
    allowed = any(cmd.startswith(prefix) for prefix in SHELL_ALLOWED_PREFIXES)
    if not allowed:
        return (
            f"⚠️ 命令 '{cmd[:50]}' 不在白名单中，已阻断。\n"
            f"允许的命令前缀：{', '.join(SHELL_ALLOWED_PREFIXES[:8])}…"
        )

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=input.timeout,
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\n[stderr]: {result.stderr}"
        return output or "(命令无输出)"
    except subprocess.TimeoutExpired:
        return f"超时（{input.timeout}s）：命令未完成"
    except Exception as e:
        return f"执行失败：{e}"


# ── 工具 4：web_search ─────────────────────────────────────────────────────────
# 使用 DuckDuckGo Instant Answer API（无需 API Key，免费）
# 生产场景可替换为 Brave Search API / Tavily API 获得更好的结果质量

class WebSearchInput(BaseModel):
    query: str = Field(description="搜索关键词")
    max_results: int = Field(default=5, description="返回结果数，最多 10")


@registry.tool(
    description="搜索互联网。使用 DuckDuckGo，无需 API Key。返回摘要和链接。",
    is_read_only=True,
    is_destructive=False,
    is_concurrency_safe=True,  # 网络请求可并发
    max_result_size_chars=3000,
)
def web_search(input: WebSearchInput) -> str:
    import urllib.parse
    import urllib.request
    import json as _json

    max_results = min(input.max_results, 10)

    try:
        # DuckDuckGo Instant Answer API（JSON 格式）
        encoded_query = urllib.parse.quote(input.query)
        url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_redirect=1&no_html=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Lena/0.4"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode("utf-8"))

        results = []

        # AbstractText — 摘要段落
        if data.get("AbstractText"):
            results.append(f"📖 摘要：{data['AbstractText']}")
            if data.get("AbstractURL"):
                results.append(f"   来源：{data['AbstractURL']}")

        # RelatedTopics — 相关话题
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                text = topic["Text"][:200]
                url_val = topic.get("FirstURL", "")
                results.append(f"• {text}")
                if url_val:
                    results.append(f"  🔗 {url_val}")

        if not results:
            # Fallback：提示用户改用浏览器
            return (
                f"DuckDuckGo 没有找到 '{input.query}' 的即时答案。\n"
                "建议：尝试更具体的关键词，或使用 shell 工具调用命令行工具。"
            )

        return f"🔍 搜索结果：{input.query}\n\n" + "\n".join(results)

    except Exception as e:
        return f"搜索失败：{e}\n提示：检查网络连接，或考虑配置代理。"
