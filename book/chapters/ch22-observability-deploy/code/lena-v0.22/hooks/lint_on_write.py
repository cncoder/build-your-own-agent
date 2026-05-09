"""PostToolUse hook：每次 Write 工具写 .py 文件后自动 ruff check。

触发条件：matcher = "Write"（在 .claude/settings.json 中配置）
输入格式（stdin）：
    {
      "tool_name": "Write",
      "tool_input": {"file_path": "/path/to/file.py", "content": "..."},
      "tool_response": {"type": "text", "text": "OK"}
    }

输出格式（stdout）：
    {"decision": "approve"}           # 放行
    {"decision": "block", "reason": "Ruff lint 失败:\n..."}  # 阻止（让 agent 修复）

局限性：
  - block 返回会让 Claude Code 把 reason 注入 agent 消息，agent 会尝试修复并重新 Write
  - 如果 ruff 不在 PATH 里，hook 会静默放行（不阻断），避免 hook 工具缺失导致 agent 无法工作
  - 这个 hook 是"给 agent 自动修复机会"的反馈循环，不是强制门控

安装：
    ruff 需要单独安装：pip install ruff
"""
import json
import subprocess
import sys


def main() -> None:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 无法解析 stdin，静默放行
        print(json.dumps({"decision": "approve"}))
        return

    file_path: str = data.get("tool_input", {}).get("file_path", "")

    if not file_path.endswith(".py"):
        print(json.dumps({"decision": "approve"}))
        return

    try:
        result = subprocess.run(
            ["ruff", "check", "--fix", file_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # ruff 不存在或超时，静默放行
        print(json.dumps({"decision": "approve"}))
        return

    if result.returncode != 0:
        reason = f"Ruff lint 失败，请修复后重新提交：\n{result.stdout[:800]}"
        print(json.dumps({"decision": "block", "reason": reason}))
    else:
        print(json.dumps({"decision": "approve"}))


if __name__ == "__main__":
    main()
