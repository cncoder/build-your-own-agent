#!/usr/bin/env python3
"""
lena.py — Lena v0.4：ToolRegistry 驱动的四工具 agent

用法：
  python lena.py                         # 默认 anthropic
  python lena.py --provider bedrock
  python lena.py --provider openai

v0.4 vs v0.3 的差异：
  v0.3：tools.py 硬编码 TOOLS 列表，加工具要改 tools.py + lena.py
  v0.4：registry.py ToolRegistry + @tool 装饰器，加工具只改 tools.py

核心：lena.py 的 agent_loop() 没有任何变化，完全不知道有哪些工具。
      工具的增删只影响 tools.py，不影响核心循环。

架构：
  Config   → argparse + .env
  Provider → provider.py（与 v0.3 完全相同）
  Memory   → messages[] 列表（本章保持简单）
  Registry → registry.py ToolRegistry（v0.4 新增）
  Tools    → tools.py（四个 @tool 装饰的函数）
  Loop     → 本文件 agent_loop()（与 v0.3 完全相同！）

参考：
  R1 §2 buildTool(def) Tool.ts:783
  R2 §2 ToolRegistry 行 R2-openclaw-nanoclaw-comparison.md
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from provider import create_provider

# 导入 tools.py 会触发所有 @tool 装饰器，完成注册
import tools  # noqa: F401  — 副作用导入，不要删！
from registry import registry

# ── 1. Config ──────────────────────────────────────────────────────────────────
load_dotenv()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lena v0.4 — 四工具 agent")
    p.add_argument(
        "--provider",
        default="anthropic",
        choices=["anthropic", "openai", "bedrock"],
        help="LLM provider（默认 anthropic）",
    )
    p.add_argument("--max-turns", type=int, default=10, help="最大工具调用轮次")
    p.add_argument("--debug", action="store_true", help="打印工具注册表")
    return p.parse_args()


# ── 2. Memory ──────────────────────────────────────────────────────────────────
messages: list[dict] = []


# ── 3. AgentLoop ───────────────────────────────────────────────────────────────
def agent_loop(user_input: str, provider, max_turns: int) -> str:
    """
    核心 agent 循环。与 v0.3 完全相同，不知道有哪些工具。

    唯一的变化：
      v0.3: tools = get_tool_schemas()    ← 直接返回 TOOLS 列表
      v0.4: tools = registry.get_schemas() ← 从 ToolRegistry 动态获取

      v0.3: result = execute_tool(name, inputs)    ← 直接查 TOOLS
      v0.4: result = registry.execute(name, inputs) ← 通过 ToolRegistry
    """
    messages.append({"role": "user", "content": user_input})
    tools = registry.get_schemas()  # 动态获取，不 hardcode

    for turn in range(max_turns):
        response = provider.chat(messages, tools)

        if response.tool_calls:
            messages.append(provider.make_assistant_with_tool_use(response))

            for tc in response.tool_calls:
                result = registry.execute(tc["name"], tc["inputs"])
                print(f"  [工具] {tc['name']}({_fmt_inputs(tc['inputs'])}) → {result[:100]}…")
                messages.append(provider.make_tool_result_message(tc["id"], result))

            continue

        messages.append({"role": "assistant", "content": response.content})
        return response.content

    return "（已达最大工具调用轮次）"


def _fmt_inputs(inputs: dict) -> str:
    """格式化工具输入，截断长字符串。"""
    parts = []
    for k, v in inputs.items():
        v_str = str(v)
        if len(v_str) > 40:
            v_str = v_str[:40] + "…"
        parts.append(f"{k}={repr(v_str)}")
    return ", ".join(parts)


# ── 4. REPL ────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()

    try:
        provider = create_provider(args.provider)
    except Exception as e:
        print(f"初始化 provider 失败：{e}", file=sys.stderr)
        sys.exit(1)

    print(f"Lena v0.4 ✦ provider={args.provider}")

    if args.debug:
        print("\n已注册工具：")
        for t in registry.list_tools():
            flags = []
            if t["is_read_only"]:
                flags.append("只读")
            if t["is_destructive"]:
                flags.append("破坏性")
            if not t["is_concurrency_safe"]:
                flags.append("串行")
            size = t["max_result_size_chars"]
            size_str = "∞" if size is None else str(size)
            print(
                f"  • {t['name']:15} [{', '.join(flags) or '安全'}] "
                f"max={size_str}"
            )
        print()

    print("可用工具：read_file / write_file / shell / web_search")
    print("输入 'exit' 退出\n")

    while True:
        try:
            user = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user:
            continue
        if user.lower() in ("exit", "quit", "bye"):
            print("再见！")
            break

        reply = agent_loop(user, provider, args.max_turns)
        print(f"Lena：{reply}\n")


if __name__ == "__main__":
    main()
