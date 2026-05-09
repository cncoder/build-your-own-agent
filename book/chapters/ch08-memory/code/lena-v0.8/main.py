"""
main.py — Lena v0.8 CLI demo

Usage:
    python main.py              # new session
    python main.py sess_abc123  # resume an existing session

Cross-session memory demo:
    Session 1: "我叫 Bob，我偏好 Python"
    Session 2 (new process): "帮我写个 hello world"
    → Lena should reply in Python without asking
"""
import sys
from core.agent import LenaAgent


def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else None
    agent = LenaAgent(session_id=session_id)

    memories = agent.memdir.load_all()
    print(f"[Session: {agent.session_id}]")
    print(f"[Memories loaded: {len(memories)}]")
    if memories:
        for m in memories:
            print(f"  - [{m.get('type','?')}] {m.get('subject','?')}: "
                  f"{m.get('content','')[:60]}...")
    print()

    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not user:
            continue

        reply = agent.chat(user)
        print(f"Lena: {reply}\n")


if __name__ == "__main__":
    main()
