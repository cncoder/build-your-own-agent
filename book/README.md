# 从零构建你的 AI Agent

> **手写一个能在 Telegram 跟你说话、自己会学习、能上网、能跑代码的 AI 助理——24 章，从第一次 API 调用到生产级 Browser Agent。**

---

## 读者画像

这本书写给**会写 Python、想搞清楚"Agent 到底怎么做出来的"的工程师**。不需要 ML 背景，不需要读论文。你只需要能跑 `pip install anthropic` 并对"LLM 底层是怎么工作的"有好奇心。

---

## 全书地图

```
Part 0 · 心智模型（Ch 1-3）
────────────────────────────
Ch 1  你好，Agent        Lena v0.1  ─── API 调用打通
Ch 2  ReAct 循环         Lena v0.2  ─── 手绘状态机
Ch 3  Lena 诞生          Lena v0.3  ─── 50 行，第一个工具

Part 1 · 六大支柱（Ch 4-10）
────────────────────────────
Ch 4  Tool 系统          Lena v0.4  ─── Tool 统一性
Ch 5  流式与并发         Lena v0.5  ─── 工具注册表
Ch 6  记忆与上下文       Lena v0.6  ─── SSE + 并发执行
Ch 7  Context Engineering Lena v0.7 ─── SQLite 会话历史
Ch 8  Planning & Subagent Lena v0.8 ─── Context 压缩
Ch 9  Skills             Lena v0.9  ─── 子任务并发
Ch 10 安全专章           Lena v1.0  ─── Skills 加载

Part 2 · Always-on 助理（Ch 11-16）
────────────────────────────────────
Ch 11 Gateway & Channel  Lena v1.1  ─── 输入层安全
Ch 12 MessageBus         Lena v1.2  ─── 执行层安全
Ch 13 Heartbeat          Lena v1.3  ─── Gateway + Telegram
Ch 14 Cron & Long-task   Lena v1.4  ─── MessageBus 热插拔
Ch 15 MCP 协议           Lena v1.5  ─── Heartbeat 主动推送
Ch 16 Docker Sandbox     Lena v1.6  ─── Cron + 断点续传

Part 3 · 生产化（Ch 17-20）
────────────────────────────
Ch 17 Evals              Lena v1.7  ─── MCP 工具生态
Ch 18 可观测性 & 部署    Lena v1.8  ─── Docker 安全沙箱
Ch 19 Specialization     Lena v1.9  ─── Evals + CI 门控
Ch 20 Browser Agent      Lena v2.0  ─── 生产部署 7×24

Part 4 · 深化专题（Ch 21-24）
────────────────────────────
Ch 21 Evals（深化）      Lena v0.21 ─── pass@k + LLM-judge
Ch 22 可观测性（深化）   Lena v0.22 ─── OTel + 预算熔断
Ch 23 Specialization（深化）Lena v0.23─── 一键派生 N 个 Agent
Ch 24 Browser Agent（终章）Lena v2.0 ─── 六大支柱压力测试
```

---

## 目录卡片

### Part 0 · 心智模型

| | |
|---|---|
| **Ch 1** | **你好，Agent——从一次 API 调用开始** |
| 一句话 | LLM 是函数，Agent 是程序，工具调用是两者之间的桥梁 |
| Lena 版本 | v0.0 → v0.1 |
| 本章产物 | 能打印一次模型回复的最小骨架 |
| 配套资料 | [Demo](chapters/ch01-hello-agent/demo/index.html) · [Slides](chapters/ch01-hello-agent/slides/index.html) · [Podcast](chapters/ch01-hello-agent/podcast.md) |

| | |
|---|---|
| **Ch 2** | **从 Chat 到 Agent：ReAct 循环的秘密** |
| 一句话 | 把推理和行动交织在同一个调用流程里，这就是 agent 区别于 chatbot 的本质 |
| Lena 版本 | v0.1 → v0.2 |
| 本章产物 | 手绘 Thought/Action/Observation 状态机图 |
| 配套资料 | [Demo](chapters/ch02-react-loop/demo/index.html) · [Podcast](chapters/ch02-react-loop/podcast.md) |

| | |
|---|---|
| **Ch 3** | **Lena 诞生——50 行 Python 写出可跑的 Agent** |
| 一句话 | 从空骨架到真实工具调用，每步都能运行，每步都打印有意义的输出 |
| Lena 版本 | v0.1 → v0.3 |
| 本章产物 | `lena-v0.3`：终端里问"现在几点"，Lena 会调工具回答你 |
| 配套资料 | [Demo](chapters/ch03-lena-is-born/demo/index.html) · [Podcast](chapters/ch03-lena-is-born/podcast.md) |

### Part 1 · 六大支柱

| | |
|---|---|
| **Ch 4** | **Tool 系统——任何能力都是工具** |
| 一句话 | 工具注册表统一管理所有能力，加工具不改核心循环 |
| Lena 版本 | v0.3 → v0.4 |
| 本章产物 | `lena-v0.4`：read_file / write_file / shell / web_search 四个工具 |
| 配套资料 | [Demo](chapters/ch04-tool-system/demo/index.html) · [Podcast](chapters/ch04-tool-system/podcast.md) |

| | |
|---|---|
| **Ch 5** | **流式与并发——让 Agent 不卡顿** |
| 一句话 | 并发不是奢侈品，是长任务可用的基础设施 |
| Lena 版本 | v0.4 → v0.5 |
| 本章产物 | `lena-v0.5`：SSE 流式输出，终端里看 Lena"边想边说" |
| 配套资料 | [Demo](chapters/ch05-streaming-concurrent/demo/index.html) · [Podcast](chapters/ch05-streaming-concurrent/podcast.md) |

| | |
|---|---|
| **Ch 6** | **记忆与上下文——让 Agent 有昨天** |
| 一句话 | 没有记忆的 agent，每次对话都是陌生人 |
| Lena 版本 | v0.5 → v0.6 |
| 本章产物 | `lena-v0.6`：SQLite 会话历史，跨会话记住你的偏好 |
| 配套资料 | [Demo](chapters/ch06-memory/demo/index.html) · [Podcast](chapters/ch06-memory/podcast.md) |

| | |
|---|---|
| **Ch 7** | **Context Engineering——Token 经济学** |
| 一句话 | Context 管理是 memory 系统的容量维度，不炸 context 才能活到第 50 轮 |
| Lena 版本 | v0.6 → v0.7 |
| 本章产物 | `lena-v0.7`：Context 压缩 + Prompt Caching，50 轮对话不炸 |
| 配套资料 | [Demo](chapters/ch07-context-engineering/demo/index.html) · [Podcast](chapters/ch07-context-engineering/podcast.md) |

| | |
|---|---|
| **Ch 8** | **Planning 与 Subagent——让 Agent 拆任务** |
| 一句话 | 一个人做三件事需要三倍时间，三个人各做一件事只需一倍时间 |
| Lena 版本 | v0.7 → v0.8 |
| 本章产物 | `lena-v0.8`：接到"调研 X"→ 并发派 3 个子 agent，汇总返回 |
| 配套资料 | [Demo](chapters/ch08-planning-subagent/demo/index.html) · [Podcast](chapters/ch08-planning-subagent/podcast.md) |

| | |
|---|---|
| **Ch 9** | **Skills——可复用的能力单元** |
| 一句话 | 工具解决"能不能做"，Skills 解决"怎么做得好" |
| Lena 版本 | v0.8 → v0.9 |
| 本章产物 | `lena-v0.9`：Markdown 文件驱动的 Skills 系统，可热加载 |
| 配套资料 | [Demo](chapters/ch09-skills/demo/index.html) · [Podcast](chapters/ch09-skills/podcast.md) |

| | |
|---|---|
| **Ch 10** | **安全专章——Prompt Injection 与失控** |
| 一句话 | 常驻 agent 不是更聪明的工具，是一个随时可能被劫持的自主行动者 |
| Lena 版本 | v0.9 → v1.0 |
| 本章产物 | `lena-v1.0`：输入层安全护栏，权限边界，审计日志 |
| 配套资料 | [Demo](chapters/ch10-safety/demo/index.html) · [Podcast](chapters/ch10-safety/podcast.md) |

### Part 2 · Always-on 助理

| | |
|---|---|
| **Ch 11** | **Gateway 与 Channel——让 Agent 住进你的 Telegram** |
| 一句话 | CLI agent 关掉就消失，真正有用的 agent 住在后台、随时可达 |
| Lena 版本 | v1.0 → v1.1 |
| 本章产物 | `lena-v1.1`：Gateway 常驻进程，Telegram 收发消息 |
| 配套资料 | [Demo](chapters/ch11-gateway-channel/demo/index.html) · [Podcast](chapters/ch11-gateway-channel/podcast.md) |

| | |
|---|---|
| **Ch 12** | **MessageBus 与事件驱动——解耦 Channel 与 Agent** |
| 一句话 | 任何 channel 崩溃，Lena 照样跑 |
| Lena 版本 | v1.1 → v1.2 |
| 本章产物 | `lena-v1.2`：MessageBus，channel 热插拔 |
| 配套资料 | [Demo](chapters/ch12-messagebus/demo/index.html) · [Podcast](chapters/ch12-messagebus/podcast.md) |

| | |
|---|---|
| **Ch 13** | **Heartbeat——让 Agent 主动找你** |
| 一句话 | 被动等待命令的是工具，主动告知状态的才是助理 |
| Lena 版本 | v1.2 → v1.3 |
| 本章产物 | `lena-v1.3`：Heartbeat，每天 8 点主动推送晨报 |
| 配套资料 | [Demo](chapters/ch13-heartbeat/demo/index.html) · [Podcast](chapters/ch13-heartbeat/podcast.md) |

| | |
|---|---|
| **Ch 14** | **Cron 与 Long-running Task——跨天任务不丢失** |
| 一句话 | 定时任务加崩溃恢复，才是真正的生产级 Lena |
| Lena 版本 | v1.3 → v1.4 |
| 本章产物 | `lena-v1.4`：Cron 定时任务，崩溃恢复，跨天断点续传 |
| 配套资料 | [Demo](chapters/ch14-cron-longtask/demo/index.html) · [Podcast](chapters/ch14-cron-longtask/podcast.md) |

| | |
|---|---|
| **Ch 15** | **MCP 协议——万物皆可连接** |
| 一句话 | MCP 是给 agent 接上世界的万能接口，任何服务只要实现 MCP 就能被调用 |
| Lena 版本 | v1.4 → v1.5 |
| 本章产物 | `lena-v1.5`：接入 filesystem / github / brave-search 三个 MCP server |
| 配套资料 | [Demo](chapters/ch15-mcp-protocol/demo/index.html) · [Podcast](chapters/ch15-mcp-protocol/podcast.md) |

| | |
|---|---|
| **Ch 16** | **Docker Sandbox——给 Agent 真沙箱** |
| 一句话 | 正则过滤是一道门，Docker 是一堵墙 |
| Lena 版本 | v1.5 → v1.6 |
| 本章产物 | `lena-v1.6`：容器化代码执行，工具调用隔离 |
| 配套资料 | [Demo](chapters/ch16-docker-sandbox/demo/index.html) · [Podcast](chapters/ch16-docker-sandbox/podcast.md) |

### Part 3 · 生产化

| | |
|---|---|
| **Ch 17** | **Evals——如何知道 Agent 变好了还是变坏了** |
| 一句话 | 跑完没报错不等于质量合格，你需要一套能测量的指标 |
| Lena 版本 | v1.6 → v1.7 |
| 本章产物 | `lena-v1.7`：golden dataset + pass@k + LLM-as-judge eval pipeline |
| 配套资料 | [Demo](chapters/ch17-evals/demo/index.html) · [Podcast](chapters/ch17-evals/podcast.md) |

| | |
|---|---|
| **Ch 18** | **可观测性与部署——让 Lena 上线 7×24** |
| 一句话 | 部署不是终点，可观测才是起点，不能看见的系统不算上线 |
| Lena 版本 | v1.7 → v1.8 |
| 本章产物 | `lena-v1.8`：结构化日志 + OTel + 三种部署方式 |
| 配套资料 | [Demo](chapters/ch18-deploy-observability/demo/index.html) · [Podcast](chapters/ch18-deploy-observability/podcast.md) |

| | |
|---|---|
| **Ch 19** | **Specialization Pattern——一个 Runtime 派生 N 个 Agent** |
| 一句话 | 通用 agent 是地基，专用 agent 是楼层，你只需要打好一次地基 |
| Lena 版本 | v1.8 → v1.9 |
| 本章产物 | `lena-v1.9`：Specialization，一行命令派生专用 agent 骨架 |
| 配套资料 | [Demo](chapters/ch19-specialization/demo/index.html) · [Podcast](chapters/ch19-specialization/podcast.md) |

| | |
|---|---|
| **Ch 20** | **实战大结局（20 章版）— Browser Agent** |
| 一句话 | Browser Agent 是通用 agent 的极限考场，每一个能力在这里都被逼到边界 |
| Lena 版本 | v1.9 → v2.0 |
| 本章产物 | `lena-v2.0`：能真正上互联网的 Browser Agent |
| 配套资料 | [Demo](chapters/ch20-browser-agent/demo/index.html) · [Podcast](chapters/ch20-browser-agent/podcast.md) |

### Part 4 · 深化专题

| | |
|---|---|
| **Ch 21** | **Evals 深化——pass@k、LLM-judge、CI 门控** |
| 一句话 | 75% 单次成功率在 3 步 pipeline 后变成 42%，你需要真正测量，不只是感觉 |
| Lena 版本 | v0.20 → v0.21 |
| 本章产物 | CI 每次 PR 自动评分，退化阻断合并 |
| 配套资料 | [章节](chapters/ch21-evals/README.md) |

| | |
|---|---|
| **Ch 22** | **可观测性深化——OTel、预算熔断、生产部署** |
| 一句话 | 没有可观测性的 agent 上线，是把盲人派去驾驶飞机 |
| Lena 版本 | v0.21 → v0.22 |
| 本章产物 | `lena-v0.22`：每次 LLM 调用有结构化日志，预算四状态机 |
| 配套资料 | [章节](chapters/ch22-observability-deploy/README.md) |

| | |
|---|---|
| **Ch 23** | **Specialization 深化——Agent Squad、CrewAI、派生框架对比** |
| 一句话 | 一套 runtime，一个命令，N 个专用 agent |
| Lena 版本 | v0.22 → v0.23 |
| 本章产物 | `lena-v0.23`：Lena-SpecKit，一键派生任意专用 agent |
| 配套资料 | [章节](chapters/ch23-specialization/README.md) |

| | |
|---|---|
| **Ch 24** | **实战大结局（24 章版）— Browser Agent** |
| 一句话 | 前 23 章建立的全部能力，在 Browser Agent 这里都被逼到边界 |
| Lena 版本 | v1.9 → v2.0 |
| 本章产物 | `lena-v2.0`：DOM 感知 + 登录态 + 三层 fallback 的完整 Browser Agent |
| 配套资料 | [章节](chapters/ch24-browser-agent/README.md) |

---

## 如何读这本书

### 路径一：线性读（推荐新手）

从 Ch 1 开始，按顺序读到 Ch 20（标准版）或 Ch 24（深化版）。每章都有可运行的代码，建议边读边跑。预计时间：每章 1-2 小时，全书 30-40 小时。

**→ [从 Ch 1 开始](chapters/ch01-hello-agent/README.md)**

### 路径二：主题跳读（有经验的工程师）

按六大支柱直接跳到感兴趣的章节：

| 支柱 | 章节 |
|------|------|
| Tool 统一性 | Ch 3, 4, 15 |
| Memory / 世界模型 | Ch 6, 7 |
| Planning | Ch 8 |
| Long-horizon 执行 | Ch 5, 11, 12, 13, 14 |
| Safety / 可控性 | Ch 10, 16 |
| Specialization | Ch 9, 19, 23 |
| Quality Guard | Ch 17, 21 |

### 路径三：查漏速查

用 [TOC.md](TOC.md) 快速定位章节，或用 [FULL-BOOK.md](FULL-BOOK.md) 全文搜索。

---

## 配套资源

- **[全书目录](TOC.md)** — 24 章简表，快速导航
- **[Lena 版本演进图](lena-journey.md)** — 每章新增能力可视化
- **[UI Demo 导航](../assets/ui-demos/index.html)** — 每章可交互 Demo
- **[导出全书](../scripts/export_book.sh)** — 生成 PDF / EPUB

---

## 致谢

本书由 Claude Code + OpenClaw 协作完成，历经多轮 review 和 fact-check。
