"""
Ch1 示例 2：OpenAI Chat Completions API — 10 行打印模型回复
依赖：pip install openai==2.30.0
环境变量：OPENAI_API_KEY
"""
from openai import OpenAI  # pip install openai==2.30.0

client = OpenAI()  # 自动读取 OPENAI_API_KEY 环境变量

response = client.chat.completions.create(
    model="gpt-4o",  # 2025 主力模型
    messages=[
        {"role": "system", "content": "你是一个有用的 AI 助手，名字叫 Lena。"},
        {"role": "user",   "content": "你好，Lena！你能做什么？"},
    ],
)

print(response.choices[0].message.content)  # 打印模型回复
