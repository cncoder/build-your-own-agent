"""
lena-v0.1 — 最小 LLM 骨架
唯一运行时：AWS Bedrock Converse API

用法：
  python3 lena.py

依赖：
  pip install boto3==1.38.0

环境变量：
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION  — Bedrock 用

版本迭代：
  v0.1（本章）— 打印回复，无记忆，无工具
  v0.3（Ch3）  — 第一个工具（get_time），while 循环
  v0.6（Ch6）  — SQLite 会话历史
  ...
  v2.0（Ch20） — Browser Agent

本书代码默认 Bedrock。OpenAI/Anthropic 直连的映射放附录 D 速查。
"""

import os
import sys

import boto3

BEDROCK_REGION = os.getenv("AWS_DEFAULT_REGION", "us-west-2")
MODEL_ID = "us.anthropic.claude-sonnet-4-6"  # inference profile ID（必须带 us. 前缀）

_client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


def chat(prompt: str) -> str:
    """
    AWS Bedrock Converse API 调用。
    文档：https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html
    SDK：boto3==1.38.0

    血泪教训（案例 1.1，来源：smart-agent/api/services/llm.py）：
    - modelId 必须用 inference profile ID（us.anthropic.claude-sonnet-4-6）
    - 不是基础模型 ID（anthropic.claude-sonnet-4-6-20250219-v1:0）
    - 否则报错：ValidationException: model identifier is invalid
    """
    resp = _client.converse(
        modelId=MODEL_ID,  # ← inference profile ID，不是 model ID！
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 1024},
    )
    return resp["output"]["message"]["content"][0]["text"]


def main():
    print(f"[lena-v0.1] Bedrock / {MODEL_ID}")
    print("输入 prompt（Ctrl+C 退出）：")
    print()

    while True:
        try:
            prompt = input(">>> ").strip()
            if not prompt:
                continue
            reply = chat(prompt)
            print(f"\n{reply}\n")
        except KeyboardInterrupt:
            print("\nBye！")
            break
        except Exception as e:
            print(f"\n[错误] {e}\n")


if __name__ == "__main__":
    main()
