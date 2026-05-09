"""
lena-v0.21/judge.py
LLM-as-judge — Haiku 初判 + Sonnet 边界区复判

运行时：AWS Bedrock Converse API（boto3）
本书代码默认 Bedrock。OpenAI/Anthropic 直连映射见附录 D。
"""
import json
import os

import boto3

BEDROCK_REGION = os.getenv("AWS_REGION", "us-west-2")

JUDGE_PROMPT = """你是一个严格的 AI Agent 输出质量评审员。

## 测试用例
输入：{input}
评分标准（rubric）：{rubric}
Agent 实际输出：{actual}

## 评分要求
- 用结构化 rubric 逐维度独立评分（不要整体主观打分）
- 每个维度评分范围 0.0–1.0
- 如果某个维度无法判断，该维度返回 "unknown"，不要猜测
- overall 是各维度的算术平均（跳过 "unknown" 维度）
- 返回合法 JSON，格式如下：

{{"dimensions": {{"dim_name": 0.0}}, "overall": 0.0, "reason": "..."}}

不要在 JSON 外输出任何文字。"""

BOUNDARY_LOW = 0.40
BOUNDARY_HIGH = 0.60

# Haiku-4-5 允许（快且便宜），边界区升级 Sonnet-4-6
_JUDGE_MODELS = [
    ("us.anthropic.claude-haiku-4-5", "haiku"),
    ("us.anthropic.claude-sonnet-4-6", "sonnet (boundary review)"),
]


async def model_grade(
    input_text: str,
    rubric: str,
    actual: str,
    client=None,
) -> dict:
    """
    LLM-as-judge，返回 {"dimensions": {...}, "overall": float, "reason": str}

    边界区策略：
    - Haiku 初判：快、便宜
    - overall 在 [BOUNDARY_LOW, BOUNDARY_HIGH] 时升级到 Sonnet 复判
    - Sonnet 结果为最终判断
    """
    if client is None:
        client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

    prompt = JUDGE_PROMPT.format(input=input_text, rubric=rubric, actual=actual)

    last_result = None
    for model_id, label in _JUDGE_MODELS:
        try:
            resp = client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 512},
            )
            raw = resp["output"]["message"]["content"][0]["text"]
            result = json.loads(raw)
            result["judge_model"] = label
            last_result = result

            # 如果是 Haiku 且分数在边界区，升级到 Sonnet 复判
            if label == "haiku" and BOUNDARY_LOW <= result.get("overall", 0) <= BOUNDARY_HIGH:
                print(f"  boundary score {result['overall']:.2f} → escalating to Sonnet")
                continue
            return result

        except json.JSONDecodeError as e:
            raw_text = resp["output"]["message"]["content"][0]["text"]
            print(f"  judge JSON parse error ({label}): {e}")
            print(f"  raw output: {raw_text[:200]}")
            last_result = {"dimensions": {}, "overall": 0.5, "reason": f"parse error: {e}", "judge_model": label}

    return last_result
