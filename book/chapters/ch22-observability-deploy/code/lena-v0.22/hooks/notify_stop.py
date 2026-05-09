"""Stop hook：agent 正常停止时发 Discord webhook 通知。

触发条件：matcher = ".*"（所有 Stop 事件）
输入格式（stdin）：
    {
      "session_id": "sess_abc123...",
      "stop_reason": "end_turn" | "max_turns" | "tool_limit" | ...
    }

输出格式（stdout）：
    {}                              # 允许正常退出
    {"blockingErrors": ["原因"]}   # 阻止退出，让 loop 继续（本 hook 不使用此特性）

重要区别：
  Stop   = agent 正常完成退出（本 hook 覆盖）
  StopFailure = agent 异常退出（需要单独的 StopFailure hook 做告警）

环境变量：
    DISCORD_WEBHOOK_URL  Discord Incoming Webhook URL（不设则静默，不报错）

局限性：
    - httpx 不在所有环境里，如果 import 失败，hook 静默退出（不阻断 agent）
    - 网络超时（默认 5s）时不重试，通知失败不应影响 agent 退出流程
"""
import json
import os
import sys


def main() -> None:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({}))
        return

    session_id: str = data.get("session_id", "unknown")
    stop_reason: str = data.get("stop_reason", "unknown")

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook_url:
        try:
            import httpx  # pip install httpx

            short_id = session_id[:8] if len(session_id) >= 8 else session_id
            msg = f"✅ Lena session `{short_id}` 完成 | reason: `{stop_reason}`"
            httpx.post(webhook_url, json={"content": msg}, timeout=5)
        except Exception:
            # 通知失败不阻断 agent 退出
            pass

    # 空响应 = 允许正常退出
    print(json.dumps({}))


if __name__ == "__main__":
    main()
