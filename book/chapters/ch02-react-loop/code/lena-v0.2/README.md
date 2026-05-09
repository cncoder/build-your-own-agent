# Lena v0.2 — ReAct 循环理解版

**本章（Ch 02）是概念理解章节，无新代码。**

`lena-v0.2` 与 `lena-v0.1` 代码完全相同，但你读完本章后，看这份代码的眼光已经不同：

- `while continueLoop` 就是 ReAct 的循环主体
- `call_llm(messages, tools)` 对应 **Thought**（推理）+ **Action**（工具调用决策）
- `execute_tool(tool_call)` 对应 **Action**（工具执行）
- 把工具结果 append 回 `messages` 对应 **Observation**（真实反馈写入账本）

本章作业是**手绘状态机图**，不需要改代码。

---

## 可运行代码在哪

Ch 03 的 `lena-v0.3` 是第一个完整可运行的 agent，包含：
- 多家 API provider 适配
- 工具注册表
- REPL 交互界面

如果你已经完成了 Ch 01，可以先用 `lena-v0.1` 试跑，结合本章的 `demo/index.html` 可视化理解 ReAct 循环，Ch 03 再写第一个真正的 agent。

---

## 本章 Demo

打开 `../../demo/index.html`（相对于本文件的路径，也就是 `ch02-react-loop/demo/index.html`）：

1. 页面中央有 ReAct 状态机动画（三节点循环图）
2. 右侧面板显示预录的 "今天几号？" agent 对话
3. 点击"下一步"按钮，对应节点高亮
4. 底部有"导出为图片"按钮，可以保存你的作业

无需 API Key，全部 mock 数据。
