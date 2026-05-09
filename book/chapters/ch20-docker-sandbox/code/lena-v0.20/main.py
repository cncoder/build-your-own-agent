"""
main.py — lena-v1.6 主入口

本章产物：Lena 能在 Docker 容器里执行任意 shell
新增能力（相对 v1.5）：
- DockerSandbox：每次独立容器，docker socket 隔离，seccomp 校验
- ExecApprovals：session 级批准记忆

运行：python main.py
前提：Docker Desktop 已启动（docker info 验证）

运行时：AWS Bedrock Converse API（boto3）
本书代码默认 Bedrock。OpenAI/Anthropic 直连映射见附录 D。
"""

import os
import uuid

import boto3

from docker_sandbox import DockerSandbox, ExecutionResult
from exec_approvals import ApprovalStore, ask_user_approval
from sandbox_validator import SecurityError

# ── 配置 ──────────────────────────────────────────────────────────────────
BEDROCK_REGION = os.getenv("AWS_REGION", "us-west-2")
MODEL = os.getenv("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6")
SANDBOX_TIMEOUT = int(os.getenv("SANDBOX_TIMEOUT", "30"))

SYSTEM_PROMPT = """你是 Lena，一个能在 Docker 沙箱里安全执行代码的 AI Agent。

你拥有 execute_code 工具，可以在隔离容器中运行 Python/Shell/JavaScript。
每次执行都在独立容器里，执行完毕容器立即销毁。

安全原则：
1. 代码在完全隔离的容器里运行，无法访问宿主机文件系统
2. 容器断网（network=none），代码无法联网
3. 资源有限（CPU 0.5 core，内存 256MB，超时 30 秒）
4. 执行前用户需要审批（同一 session 内同类命令自动通过）

回答时结论先行，直接给出执行结果分析。"""

TOOLS = [
    {
        "toolSpec": {
            "name": "execute_code",
            "description": "在 Docker 沙箱里执行代码。每次独立容器，执行后立即销毁。支持 Python/Shell/JavaScript。",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "要执行的代码"
                        },
                        "language": {
                            "type": "string",
                            "enum": ["python", "shell", "javascript"],
                            "description": "代码语言",
                            "default": "python"
                        }
                    },
                    "required": ["code"]
                }
            }
        }
    }
]


def run_tool(
    tool_name: str,
    tool_input: dict,
    sandbox: DockerSandbox,
    approvals: ApprovalStore,
    session_id: str,
) -> str:
    """执行工具调用，返回结果字符串"""

    if tool_name == "execute_code":
        code = tool_input["code"]
        language = tool_input.get("language", "python")
        display = f"{language}: {code[:100]}{'...' if len(code) > 100 else ''}"

        # exec-approvals 检查
        if approvals.is_approved(session_id, display):
            print(f"[exec-approvals] 自动通过（session 已批准过同类命令）")
            approved = True
            remember = False
        else:
            approved, remember = ask_user_approval(code, language)
            if remember:
                approvals.approve(session_id, display)

        if not approved:
            return "用户拒绝执行。"

        print(f"[sandbox] 启动容器执行 {language} 代码…")
        try:
            result: ExecutionResult = sandbox.execute(code, language)
            print(f"[sandbox] 容器已销毁，exit_code={result.exit_code}")
            return str(result)
        except SecurityError as e:
            return f"[安全拦截] {e}"
        except Exception as e:
            return f"[执行错误] {e}"

    return f"未知工具：{tool_name}"


def chat(
    messages: list[dict],
    client,
    sandbox: DockerSandbox,
    approvals: ApprovalStore,
    session_id: str,
) -> str:
    """单轮对话（含工具调用循环）"""
    while True:
        response = client.converse(
            modelId=MODEL,
            system=[{"text": SYSTEM_PROMPT}],
            toolConfig={"tools": TOOLS},
            messages=messages,
            inferenceConfig={"maxTokens": 4096},
        )

        stop_reason = response.get("stopReason", "end_turn")
        msg = response["output"]["message"]

        # 收集文本和工具调用
        text_parts = []
        tool_calls = []

        for block in msg.get("content", []):
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tool_calls.append(block["toolUse"])

        # 如果有工具调用，执行并继续循环
        if tool_calls:
            # 把 assistant 回复加入历史
            messages.append({"role": "assistant", "content": msg["content"]})

            # 执行所有工具
            tool_results = []
            for call in tool_calls:
                result_text = run_tool(
                    call["name"], call["input"],
                    sandbox, approvals, session_id
                )
                tool_results.append({
                    "toolResult": {
                        "toolUseId": call["toolUseId"],
                        "content": [{"text": result_text}],
                    }
                })

            messages.append({"role": "user", "content": tool_results})
            continue  # 让 Lena 处理工具结果后继续

        # 没有工具调用，返回最终文本
        return "\n".join(text_parts)


def main():
    client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
    sandbox = DockerSandbox(timeout=SANDBOX_TIMEOUT)
    approvals = ApprovalStore()
    session_id = uuid.uuid4().hex

    print("="*60)
    print("lena-v1.6 — Docker Sandbox")
    print(f"模型：{MODEL}")
    print(f"session：{session_id[:8]}…")
    print("="*60)
    print("Lena 已就绪。代码将在 Docker 沙箱中执行（网络隔离，每次独立容器）。")
    print("输入 'exit' 退出，'status' 查看已批准命令\n")

    messages = []

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        if user_input.lower() == "exit":
            approvals.clear_session(session_id)
            print("Bye.")
            break

        if user_input.lower() == "status":
            patterns = approvals.approved_patterns(session_id)
            if patterns:
                print(f"[exec-approvals] 已批准 {len(patterns)} 个命令模式：")
                for p in patterns:
                    print(f"  • {p}")
            else:
                print("[exec-approvals] 本 session 尚无已批准命令")
            continue

        messages.append({"role": "user", "content": [{"text": user_input}]})
        response = chat(messages, client, sandbox, approvals, session_id)
        messages.append({"role": "assistant", "content": [{"text": response}]})
        print(f"\nLena: {response}\n")


if __name__ == "__main__":
    main()
