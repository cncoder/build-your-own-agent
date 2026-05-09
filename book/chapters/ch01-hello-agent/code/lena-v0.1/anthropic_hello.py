"""
Ch1 示例 1：Anthropic Messages API — 10 行打印模型回复
依赖：pip install anthropic==0.84.0
环境变量：ANTHROPIC_API_KEY
"""
import anthropic  # pip install anthropic==0.84.0

client = anthropic.Anthropic()  # 自动读取 ANTHROPIC_API_KEY 环境变量

response = client.messages.create(
    model="claude-opus-4-5-20251101",  # 2025-2026 稳定版
    max_tokens=1024,
    messages=[{"role": "user", "content": "你好，Lena！你能做什么？"}],
)

print(response.content[0].text)  # 打印模型回复
