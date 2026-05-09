# Lena v0.3 — 最小可运行 Agent

本章产物：50 行核心代码的 agent REPL，能回答"现在几点"。

## 文件说明

```
lena.py         # 主入口，核心 while 循环（AgentLoop）
tools.py        # 工具定义（get_time）+ 工具注册表
provider.py     # Anthropic / OpenAI / Bedrock 三家适配
requirements.txt
.env.example    # API Key 配置模板
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

### 3. 运行

```bash
# 使用 Anthropic Claude（默认）
python lena.py

# 使用 OpenAI
python lena.py --provider openai

# 使用 AWS Bedrock
python lena.py --provider bedrock
```

## 真实终端输出（2026-05-06 Bedrock 实测）

```
$ echo -e "现在几点了？\n今天是星期几？\nexit" | python lena.py --provider bedrock

Lena v0.3 ✦ provider=bedrock
输入 'exit' 或按 Ctrl-C 退出

你：  [工具] get_time({}) → 当前时间是 2026年05月06日 00:24:31（local）
Lena：现在是 **2026年5月6日 00:24**，已经是深夜了哦！🌙 注意休息，有什么需要帮助的尽管告诉我！😊

你：Lena：根据刚才获取的时间，**2026年5月6日** 是**星期三**！📅

有什么我可以帮你的吗？😊

你：再见！
```

可以看到：
1. 用户问"现在几点" → LLM 决定调用 `get_time` 工具
2. `[工具]` 行显示工具被执行，返回真实时间
3. LLM 拿到工具结果，组合成自然语言回复
4. 第二个问题"星期几"：LLM 复用上下文里的时间，无需再调用工具

## 架构说明

6 模块 MVA（Minimum Viable Agent）骨架：

```
用户输入
   │
   ▼
[Memory] messages[] ─────────────────────────┐
   │                                          │
   ▼                                          │
[Provider] LLM API                            │
   │                                          │
   ▼                                          │
有 tool_use? ──是──▶ [ToolRegistry] 执行工具  │
   │                        │                 │
   │否                      ▼                 │
   │              [Memory] 回填结果 ──────────┘
   │
   ▼
返回文字答复
```

## 扩展

- 加更多工具：在 `tools.py` 的 `TOOLS` 列表里添加条目
- 加记忆持久化：把 `messages[]` 替换成 SQLite（Ch 6）
- 加技能（Skills）：Ch 9 展开
