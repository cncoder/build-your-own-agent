"""
Ch1 示例 3：AWS Bedrock Converse API — 10 行打印模型回复
依赖：pip install boto3==1.38.0
环境变量：AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION

血泪教训（案例 1.1）：
  modelId 必须用 inference profile ID（us.anthropic.claude-sonnet-4-6）
  不是基础模型 ID（anthropic.claude-sonnet-4-6-20250219-v1:0）
  否则报错："model identifier is invalid"
  参考：Bedrock Converse API 文档 inference profile 章节
"""
import boto3  # pip install boto3==1.38.0

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

response = bedrock.converse(
    modelId="us.anthropic.claude-sonnet-4-6",  # ← inference profile ID，不是 model ID！
    system=[{"text": "你是一个有用的 AI 助手，名字叫 Lena。"}],
    messages=[{"role": "user", "content": [{"text": "你好，Lena！你能做什么？"}]}],
    inferenceConfig={"maxTokens": 1024},
)

print(response["output"]["message"]["content"][0]["text"])  # 打印模型回复
