# lena-v0.1

第 1 章产物：最小 LLM 骨架，支持三家 provider。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 运行

```bash
# 使用 Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
python3 lena.py anthropic

# 使用 OpenAI
export OPENAI_API_KEY="sk-..."
python3 lena.py openai

# 使用 AWS Bedrock（需要 AWS 凭证 + Bedrock 模型访问权限）
export AWS_DEFAULT_REGION="us-east-1"
python3 lena.py bedrock
```

## 真实终端输出（2026-05-05 实测）

```
$ python3 lena.py bedrock
[lena-v0.1] provider=bedrock
输入 prompt（Ctrl+C 退出）：

>>> 用一句话解释什么是大语言模型

大语言模型是一种通过海量文本数据训练、能够理解和生成自然语言的大规模人工智能模型。

>>> 今天是什么日子

我没有办法知道今天的确切日期，因为我无法访问实时信息或当前时间。
您可以查看手机、电脑或其他设备来确认今天的日期。

^C
Bye！
```

**注意**：`今天是什么日子` 这个问题的局限会在 Ch3 用 `get_time` 工具解决。

## 文件说明

| 文件 | 用途 |
|------|------|
| `lena.py` | 主程序，三家 provider 统一入口 |
| `anthropic_hello.py` | Anthropic 极简示例（10 行） |
| `openai_hello.py` | OpenAI 极简示例（10 行） |
| `bedrock_hello.py` | Bedrock 极简示例（10 行，含血泪教训注释） |
| `requirements.txt` | 依赖版本锁定 |

## 血泪教训

Bedrock `modelId` 必须用 **inference profile ID**（`us.anthropic.claude-sonnet-4-6`），
不是基础模型 ID（`anthropic.claude-sonnet-4-6-20250219-v1:0`）。
否则：`ValidationException: model identifier is invalid`

参考：Bedrock Converse API 官方文档 inference profile 章节。
