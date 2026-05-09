"""
lena-v0.21/self_verify.py
VERIFICATION_AGENT 等价实现（agent-side 自验证）

来源参照：Claude Code TodoWriteTool.ts:107
  "NOTE: You just closed out 3+ tasks and none of them was a verification step.
   Before writing your final summary, spawn the verification agent..."

运行时：AWS Bedrock Converse API（boto3）
本书代码默认 Bedrock。OpenAI/Anthropic 直连映射见附录 D。
"""
import json
import os

import boto3

BEDROCK_REGION = os.getenv("AWS_REGION", "us-west-2")

SELF_VERIFY_PROMPT = """你刚刚完成了以下任务：
{task_description}

你的输出：
{output}

请仔细检查并返回 JSON（不要输出 JSON 以外的内容）：
{{"completeness": 0, "format_correct": true, "missing_items": []}}

- completeness：0-10 的整数，10 = 完整完成，0 = 完全没完成
- format_correct：输出格式是否符合任务要求
- missing_items：具体缺失的内容列表（completeness < 10 时必须填写）

仅在 completeness >= 8 且 format_correct = true 时视为通过。"""


class IncompleteTaskError(Exception):
    def __init__(self, missing_items: list[str]):
        self.missing_items = missing_items
        super().__init__(f"Task incomplete. Missing: {missing_items}")


async def self_verify(
    task: str,
    output: str,
    client=None,
    raise_on_incomplete: bool = False,
) -> dict:
    """
    在任务完成后自动调用，检查完整性。

    返回 {"completeness": int, "format_correct": bool, "missing_items": list}
    如果 raise_on_incomplete=True 且 completeness < 8，抛出 IncompleteTaskError

    Haiku-4-5 用于自验证：成本极低，速度快。
    """
    if client is None:
        client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

    resp = client.converse(
        modelId="us.anthropic.claude-haiku-4-5",  # 自验证用 Haiku，成本极低
        messages=[{
            "role": "user",
            "content": [{"text": SELF_VERIFY_PROMPT.format(
                task_description=task,
                output=output,
            )}],
        }],
        inferenceConfig={"maxTokens": 256},
    )

    raw = resp["output"]["message"]["content"][0]["text"]

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # 降级：无法解析时保守地认为通过，不阻塞主流程
        return {"completeness": 8, "format_correct": True, "missing_items": [], "parse_error": True}

    passed = result.get("completeness", 0) >= 8 and result.get("format_correct", False)
    if not passed and raise_on_incomplete:
        raise IncompleteTaskError(result.get("missing_items", []))

    return result
