# 从零构建通用 AI Agent：用 Python 打造能自主做任何事的 Agent Runtime

[![Chapters](https://img.shields.io/badge/chapters-Ch0%20+%2024%20+%20Ch25-blue?style=flat-square)](book/chapters/)
[![Language](https://img.shields.io/badge/language-%E4%B8%AD%E6%96%87-red?style=flat-square)](#)
[![Code](https://img.shields.io/badge/code-Python-3776AB?style=flat-square&logo=python)](#)
[![License](https://img.shields.io/badge/license-CC%20BY--NC--ND%204.0-orange?style=flat-square)](LICENSE)
[![Stars](https://img.shields.io/github/stars/cncoder/build-ai-agent?style=flat-square)](#)

<p align="center">
  <img src="book/cover/cover-3d-render.png" alt="Book Cover" width="400" />
</p>

> **Build Your Own General-Purpose AI Agent from Scratch**
>
> 一本书，带你从零写出能自主做任何事的通用 AI Agent。

---

## 这是什么

一本面向后端工程师的实战书，带你从第一行 API 调用开始，循序渐进构建一个 7×24 运行、能自主拆任务、记忆历史、扩展无限工具的通用 Agent，并最终派生出量化交易、新闻播报、DevOps、浏览器自动化等专用版本。

---

## 谁适合读

- 会至少一门编程语言（书中示例为 Python）
- 用过 ChatGPT，感觉"差点什么"
- 没写过 agent，但想真正搞清楚它是怎么工作的

不需要 AI/ML 学位，不需要读过论文，需要的只是好奇心和一台能跑 Python 的机器。

---

## 能学到什么

### 8 个维度让你的 Agent 越来越聪明

| 维度 | 代表章节 |
|------|---------|
| **推理** — 从单步回答到多步规划 | Ch 2、Ch 11 |
| **记忆** — 短期 / 长期 / 语义三层记忆 | Ch 8、Ch 9 |
| **规划** — ReAct / Plan Mode / Reflection | Ch 2、Ch 11 |
| **协作** — 主 Agent + 子 Agent 编排 | Ch 11、Ch 23 |
| **学习** — Skills 可复用能力单元 | Ch 12 |
| **安全** — Prompt Injection 到 Docker 沙箱 | Ch 13、Ch 14、Ch 20 |
| **自省** — Evals + 可观测性 | Ch 21、Ch 22 |
| **跨界** — MCP 协议万物皆可连接 | Ch 19 |

### 技术栈一览

| 项 | 选择 |
|---|---|
| 语言 | Python 3.10+ |
| LLM Provider | Anthropic Claude（主）/ OpenAI / AWS Bedrock（均支持） |
| API Key | 需要至少一个（Anthropic 免费 tier 可跑完前 3 章） |
| 框架 | 无（裸 API + 自建薄抽象，全书 <500 行核心代码） |
| 向量数据库 | ChromaDB（本地，零配置） |
| 容器 | Docker（Ch20 沙箱章需要，其余可选） |
| 操作系统 | macOS / Linux / WSL2 均可 |

### 读完可以派生的 5 种专用 Agent

- **量化交易 Agent** — 盯盘、回测、下单、推送日报
- **新闻播报 Agent** — 聚合、摘要、TTS 合成、定时推送
- **DevOps Agent** — 监控报警、自动扩缩容、PR Review
- **Browser Agent** — 打开网页、填表、截图、抓数据
- **个人助理 Agent** — Telegram 随叫随到，记住你的一切

---

## 目录

| 章节 | 标题 | 媒体 |
|------|------|------|
| [Ch 0](book/chapters/ch00-intelligence-map/README.md) | 序章：Agent 聪明度模型 — 本书地图 | 🎙️ 🕹️ |
| [Ch 1](book/chapters/ch01-hello-agent/README.md) | 你好，Agent：从一次 API 调用开始 | 🎙️ 🎨 🕹️ |
| [Ch 2](book/chapters/ch02-react-loop/README.md) | 从 Chat 到 Agent：ReAct 循环的秘密 | 🎙️ 🎨 |
| [Ch 3](book/chapters/ch03-lena-is-born/README.md) | Lena 诞生：50 行 Python 写出可跑的 Agent | 🎙️ 🎨 🕹️ |
| [Ch 4](book/chapters/ch04-llm-internals/README.md) | LLM 底层：Agent 工程师需要知道的最少内容 | 🎙️ 🎨 |
| [Ch 5](book/chapters/ch05-tech-selection/README.md) | 技术选型：Prompt / RAG / Agent / Fine-tune 怎么选 | 🎙️ 🎨 🕹️ |
| [Ch 6](book/chapters/ch06-tool-system/README.md) | 工具系统：每一项能力都是一个工具 | 🎙️ 🎨 🕹️ |
| [Ch 7](book/chapters/ch07-streaming-concurrent/README.md) | 流式与并发：让 Agent 不卡顿 | 🎙️ 🎨 |
| [Ch 8](book/chapters/ch08-memory/README.md) | 记忆与上下文：让 Agent 有昨天 | 🎙️ 🎨 🕹️ |
| [Ch 9](book/chapters/ch09-rag-vector-search/README.md) | RAG 与向量检索：教 Lena 读懂你的文档 | 🎙️ 🎨 🕹️ |
| [Ch 10](book/chapters/ch10-context-engineering/README.md) | 上下文工程：Token 经济学 | 🎙️ 🎨 |
| [Ch 11](book/chapters/ch11-planning-subagent/README.md) | Planning 与 Subagent：让 Agent 拆任务 | 🎙️ 🎨 🕹️ |
| [Ch 12](book/chapters/ch12-skills/README.md) | Skills：可复用的能力单元 | 🎙️ 🎨 |
| [Ch 13](book/chapters/ch13-input-safety/README.md) | 输入层安全：Prompt Injection 与权限边界 | 🎙️ 🎨 |
| [Ch 14](book/chapters/ch14-execution-safety/README.md) | 执行层安全：当 Agent 有真权力时 | 🎙️ 🎨 |
| [Ch 15](book/chapters/ch15-gateway-channel/README.md) | Gateway 与 Channel：让 Agent 住进你的 Telegram | 🎙️ 🎨 🕹️ |
| [Ch 16](book/chapters/ch16-messagebus/README.md) | MessageBus 与事件驱动：解耦 Channel 与 Agent | 🎙️ 🎨 |
| [Ch 17](book/chapters/ch17-heartbeat/README.md) | Heartbeat：让 Agent 主动找你 | 🎙️ 🎨 🕹️ |
| [Ch 18](book/chapters/ch18-cron-longtask/README.md) | Cron 与长耗时任务：断点续传 | 🎙️ 🎨 |
| [Ch 19](book/chapters/ch19-mcp-protocol/README.md) | MCP 协议：万物皆可连接 | 🎙️ 🎨 🕹️ |
| [Ch 20](book/chapters/ch20-docker-sandbox/README.md) | Docker Sandbox：代码执行的安全边界 | 🎙️ 🎨 |
| [Ch 21](book/chapters/ch21-evals/README.md) | Evals：如何知道 Agent 变好了还是变坏了 | 🎙️ 🎨 🕹️ |
| [Ch 22](book/chapters/ch22-observability-deploy/README.md) | 可观测性与部署：让 Lena 上线 7×24 | 🎙️ 🎨 |
| [Ch 23](book/chapters/ch23-specialization/README.md) | Specialization Pattern：一个 Runtime 派生 N 个 Agent | 🎙️ 🎨 🕹️ |
| [Ch 24](book/chapters/ch24-browser-agent/README.md) | 实战大结局：Browser Agent | 🎙️ 🎨 🕹️ |
| [Ch 25](book/chapters/ch25-from-general-to-specialized/README.md) | 终章：从聪明到自主 — 派生你自己的专用 Agent | 🎙️ 🕹️ |

图例：🎙️ TTS 播客 · 🎨 PPT 幻灯片 · 🕹️ 交互式 HTML Demo

---

## 亮点

### 正文

约 59 万字符（~40 万中文字）Markdown，纯中文，无需注册即可阅读。每章结构统一：动机 → 理论铺垫 → 最小代码 → 完整实现。

### 每章 TTS 播客 (mp3)

涛哥 + 小周对话风格，通勤路上听完全书。文件位于各章 `audio/ch-NN.mp3` 目录下（ch-00 至 ch-25，共 26 章），部分章节同步镜像至 `assets/tts/`。

### 每章 PPT (pptx)

架构图 + 关键概念 + 代码分解，字体 ≥ 28pt，可直接用于分享或教学。文件位于 `assets/ppt/ch-NN.pptx`。

### 每章 HTML 交互 Demo

深空霓虹风格（`#050810` 底色），点开即玩，不需要 API Key。位于各章 `demo/index.html` 及 `assets/ui-demos/`。

### 动手练习

部分章节包含"章末挑战题"——Karpathy 风格的实战练习，做完才算真懂。

---

## 如何阅读

### 速读路径（约 20 小时）

只读每章 README.md 正文，跳过代码实现。适合想先建立全局认知的读者。

```
Ch 0 → Ch 1 → Ch 2 → Ch 3 → (跳 4-5) → Ch 6 → Ch 8 → Ch 11 → Ch 13 → Ch 15 → Ch 21 → Ch 25
```

### 精读路径（100-150 小时）

按顺序阅读，每章跟着写代码。Lena 从 v0.1 一路演进到 v0.24 再到专用派生版。

### 听觉路径（通勤听播客）

`assets/tts/` 下按章序播放 mp3，每集约 30-45 分钟。开车、跑步时听理论章效果最佳。

### 视觉路径（看视频）

`assets/video/` 下有 PPT + 解说音频合成的 mp4。适合希望看到架构图动画演示的读者。

### 手感路径（玩 Demo）

打开各章 `demo/index.html`，无需安装任何依赖，直接在浏览器里与 Agent 概念互动。

---

## 目录结构

```
abelagent/
├── book/
│   ├── chapters/               # 每章子目录：README + 代码 + 媒体
│   │   ├── ch00-intelligence-map/
│   │   ├── ch01-hello-agent/
│   │   │   ├── README.md       # 章节正文
│   │   │   ├── code/           # 可运行的 Python 代码
│   │   │   ├── demo/           # 交互式 HTML Demo
│   │   │   ├── audio/          # 本章播客 mp3
│   │   │   ├── podcast.md      # 播客脚本
│   │   │   └── ppt.md          # PPT 内容稿
│   │   └── ...（ch02 ~ ch25）
│   └── appendix/               # 附录：参考资料、智能度演进、本书构建过程
├── assets/
│   ├── tts/                    # 章节播客 mp3 镜像（ch-01.mp3 ~ ch-20.mp3，完整版见各章 audio/）
│   ├── ppt/                    # 全部章节 PPT（ch-01.pptx ~ ch-24.pptx）
│   ├── video/                  # 视频合成输出（mp4）
│   └── ui-demos/               # 独立 HTML Demo 合集
├── book/cover/                 # 封面图（Gemini 生成）
├── docs/
│   ├── specs/                  # 书骨架、评分 rubric、设计决策
│   └── research/               # 4 份背景调研报告
├── scripts/                    # 生产流水线：TTS / PPT / 评分 / 发布
├── team-configs/               # Agent team 配置与编辑铁律
└── gitbook/                    # VitePress 静态学习网站
```

---

## 如何贡献

欢迎以下形式的贡献：

- **勘误**：发现技术错误或笔误，提 Issue 或 PR
- **补充案例**：有更好的实战案例，遵循"一句话融入"原则提 PR
- **翻译**：英文版已完成（全部 26 章），欢迎联系

提 PR 前请阅读本仓库的编辑规范，特别注意案例密度和证据层级要求（无本机路径、无作者姓名、每章最多 1 个案例）。

---

## License

本书正文、播客脚本、PPT 内容以 [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/) 授权发布（署名-非商业-禁止演绎）。

代码部分以 MIT License 授权发布。

---

## 致谢

本书的写作范式和方法论深受以下作者影响：

- **Andrej Karpathy** — zero-to-hero 系列的小台阶范式和数字验证习惯
- **Sebastian Raschka** — 每章 2-3 节纯理论铺垫 + Convention 消歧法
- **Simon Willison** — 诚实标注局限性、场景先于术语
- **Robert Nystrom** — *Crafting Interpreters* 的"每章可运行产物"和 Design Note 侧栏
- **Anthropic** — *Building Effective Agents*、*Effective Context Engineering for AI Agents* 等官方文档
