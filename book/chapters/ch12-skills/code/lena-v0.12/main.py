#!/usr/bin/env python3
"""
main.py — Lena v0.12 CLI

Usage:
    python3 main.py               # 交互模式（设置 ANTHROPIC_API_KEY 启用真实 LLM）
    python3 main.py --demo        # 演示模式（自动运行示例，无需 API Key）
    python3 main.py --list-skills # 列出所有已加载 Skill
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.agent import LenaAgent


def interactive_mode() -> None:
    lena = LenaAgent()
    print("\nLena v0.12 — Skills 版本")
    print("输入 /skills 查看可用技能，Ctrl+C 退出\n")

    while True:
        try:
            user_input = input("你: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break
        if not user_input:
            continue
        print(f"Lena: {lena.chat(user_input)}\n")


def demo_mode() -> None:
    print("=" * 60)
    print("演示：Lena v0.12 Skills 动态加载")
    print("=" * 60)

    lena = LenaAgent()

    cases = [
        ("/skills", None),
        ("/weather 上海", None),
        ("/pdf-report 季度销售数据摘要", None),
        ("今天心情不错", None),
        ("/translate 你好", None),   # 不存在的 skill，验证错误提示
    ]

    for user_input, _ in cases:
        print(f"\n{'─' * 40}")
        print(f"你: {user_input}")
        print(f"Lena: {lena.chat(user_input)}")

    print(f"\n{'=' * 60}")
    print("演示完成。设置 ANTHROPIC_API_KEY 后重跑可使用真实 LLM。")


def list_skills_mode() -> None:
    lena = LenaAgent()
    print(f"\n已加载 {len(lena.skills)} 个 Skill（来自 skills/ 目录）\n")
    for skill in lena.skills.values():
        print(f"  /{skill.name}")
        print(f"    描述: {skill.description}")
        if skill.argument_hint:
            print(f"    参数: {skill.argument_hint}")
        if skill.allowed_tools:
            print(f"    工具: {', '.join(skill.allowed_tools)}")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lena v0.12 — Skills 动态加载 Agent")
    parser.add_argument("--demo", action="store_true", help="演示模式（无需 API Key）")
    parser.add_argument("--list-skills", action="store_true", help="列出所有已加载 Skill")
    args = parser.parse_args()

    if args.demo:
        demo_mode()
    elif args.list_skills:
        list_skills_mode()
    else:
        interactive_mode()
