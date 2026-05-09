#!/usr/bin/env python3
"""
lena.py — Lena v0.3：50 行核心的最小 agent loop

用法：
  python lena.py                         # 默认 anthropic
  python lena.py --provider openai
  python lena.py --provider bedrock

架构：6 个模块（MVA 共识，源自 R2）
  Config      → argparse + .env
  Provider    → AnthropicProvider / OpenAIProvider / BedrockProvider
  Memory      → messages[] 列表（本章用简单列表，Ch 6 升级为 SQLite）
  ToolRegistry→ tools.py（get_tool_schemas / execute_tool）
  AgentLoop   → 本文件核心 while 循环
  Skills      → 本章暂不使用（Ch 9 展开）

参考源码：
  nano-claw AgentLoop  nano-claw/src/agent/loop.ts:91
  nanoClaw Agent.run() nanoClaw/nanoclaw/core/agent.py:155
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from provider import create_provider
from tools import execute_tool, get_tool_schemas

# ── 1. Config ──────────────────────────────────────────────────────────────────
load_dotenv()

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lena v0.3 — 最小 agent")
    p.add_argument("--provider", default="anthropic",
                   choices=["anthropic", "openai", "bedrock"],
                   help="LLM provider（默认 anthropic）")
    p.add_argument("--max-turns", type=int, default=10,
                   help="最大工具调用轮次（默认 10）")
    return p.parse_args()

# ── 2. Memory ──────────────────────────────────────────────────────────────────
# 本章用最简单的列表。Ch 6 会升级为带 SQLite 持久化的 MemoryStore。
messages: list[dict] = []

# ── 3. AgentLoop ───────────────────────────────────────────────────────────────
def agent_loop(user_input: str, provider, max_turns: int) -> str:
    """
    核心 agent 循环。

    状态机：
      用户消息 → LLM → [tool_use?]
                          ↓ 是
                       执行工具 → tool_result → LLM → …（最多 max_turns 轮）
                          ↓ 否
                       返回文字答复

    关键设计：
    - messages[] 是唯一的状态。每轮 LLM 看完整历史（Memory 模块）。
    - 工具结果必须以正确格式回填，否则 LLM 报错。
      Anthropic 用 user/tool_result；OpenAI 用 role=tool。
      这是两家最大的格式差异 —— provider.py 封装了这个差异。
    """
    messages.append({"role": "user", "content": [{"text": user_input}]})
    tools = get_tool_schemas()

    for turn in range(max_turns):
        # ── 调用 LLM ──────────────────────────────────────────────────────────
        response = provider.chat(messages, tools)

        if response.tool_calls:
            # ── 有工具调用：先把 assistant 消息（含 tool_use block）存入 messages
            messages.append(provider.make_assistant_with_tool_use(response))

            # ── 执行每个工具，把结果回填 messages ──────────────────────────────
            for tc in response.tool_calls:
                result = execute_tool(tc["name"], tc["inputs"])
                print(f"  [工具] {tc['name']}({tc['inputs']}) → {result}")
                messages.append(provider.make_tool_result_message(tc["id"], result))

            # 继续循环，让 LLM 看到工具结果后给出最终回复
            continue

        # ── 无工具调用：LLM 直接给出文字答复，循环结束 ─────────────────────────
        messages.append({"role": "assistant", "content": [{"text": response.content}]})
        return response.content

    return "（已达最大工具调用轮次）"


# ── 4. REPL ────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()

    try:
        provider = create_provider(args.provider)
    except Exception as e:
        print(f"初始化 provider 失败：{e}", file=sys.stderr)
        sys.exit(1)

    print(f"Lena v0.3 ✦ provider={args.provider}")
    print("输入 'exit' 或按 Ctrl-C 退出\n")

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
