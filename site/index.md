---
layout: home
title: 从零构建通用 AI Agent

hero:
  name: "从零构建通用 AI Agent"
  text: "用 Python 打造能自主做任何事的 Agent Runtime"
  tagline: "26 章 · 全程 Python · 每章可运行 · 通用 Agent Runtime 从零到生产"
  image:
    src: /hero-glow.svg
    alt: Agent Runtime
  actions:
    - theme: brand
      text: 开始阅读 →
      link: /chapters/ch00-intelligence-map/
    - theme: alt
      text: 查看全部章节
      link: /chapters/ch01-hello-agent/

features:
  - icon:
      html: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#00d4ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 22 7 22 17 12 22 2 17 2 7"/><polygon points="12 7 17 9.5 17 14.5 12 17 7 14.5 7 9.5"/></svg>'
    title: 贯穿六大支柱
    details: 工具通用性 / 自主规划 / 长时程执行 / 记忆世界模型 / 安全可控 / 专用化派生——从通用 Runtime 派生任何专用 Agent

  - icon:
      html: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#00d4ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>'
    title: Lena 逐章演进
    details: 同一个项目贯穿全书，每章有可运行产物。从 v0.1 的 30 行骨架，到 v1.0 的生产级通用 Agent Runtime

  - icon:
      html: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#00d4ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>'
    title: 三形态学习
    details: 每章配：文字版（精读）+ 播客版（通勤可听）+ 视频版（PPT 配音讲解）。一套内容，三种节奏

  - icon:
      html: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#00d4ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><polyline points="9 9 12 12 9 15"/><line x1="15" y1="12" x2="9" y2="12"/></svg>'
    title: 交互 Demo
    details: 核心概念配可交互 UI Demo，无需 API Key 扫码体验，看得见的 Agent 行为

  - icon:
      html: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#00d4ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>'
    title: 直接 API，无黑盒
    details: 不用 LangChain 框架，直接调 Anthropic / OpenAI / Bedrock API。你知道每一行代码在做什么

  - icon:
      html: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#00d4ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>'
    title: 安全专章
    details: 通用 = 危险。输入安全 + 执行沙箱 + 审批门控，专章讲解，不是附录

---

<div class="chapter-roadmap">

## 全书路线图

<RoadmapChart />

</div>

<style>
.chapter-roadmap {
  margin: 3rem auto;
  max-width: 1000px;
  padding: 2rem 1.5rem;
  background: rgba(12, 18, 32, 0.5);
  border: 1px solid rgba(0, 212, 255, 0.12);
  border-radius: 16px;
  backdrop-filter: blur(10px);
}

.chapter-roadmap h2 {
  background: linear-gradient(135deg, #00d4ff, #00ffd1);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  text-align: center;
  margin-bottom: 1.5rem;
}
</style>
