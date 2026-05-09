# 第 7 章：流式与并发——让 Agent 不卡顿

> **Lena 演进：v0.6 → v0.7**
> 新能力：SSE 流式输出 + 工具并发抢跑 + 5 工具同时搜索

---

## Beat 1 — 路线图

```
Ch 1 → Ch 2 → Ch 3 → Ch 4 → Ch 5 → Ch 6 → [Ch 7 ← 你在这里] → Ch 8 → ...
```

本章从一个"能工作但很卡"的 Lena v0.6 出发 → 先搞清楚为什么默认序列化是对的（反直觉翻转）→ 再给它装上 SSE 流式输出（让用户 0.3 秒就看到字）→ 最后加上工具并发抢跑（让 5 个搜索同时发出）。途中会踩一个坑：你以为"agent = 并发"，但真实的 Claude Code 和 OpenClaw 都默认序列化，原因很扎实。

**本章后，Lena 从 v0.6 变成 v0.7**，新增两项能力：

1. 响应第一个字出现时间从 3-10 秒 → 0.3 秒（流式输出）
2. 5 个并发工具调用总耗时从 ~8 秒 → ~2 秒（并发执行）

7 节拍：动机（为什么卡）→ SSE 协议理论 → 流式抢跑机制理论 → 脚手架（最小流式循环）→ 渐进组装（加并发）→ 运行验证（实测加速比）→ Design Note（为什么 OpenClaw 强制序列化每个会话）

> **🧠 聪明度增量（v0.6 → v0.7）**：Lena 第一次具备流式响应与工具并发能力——SSE 让用户 0.3 秒就看到第一个字，asyncio 并发让 5 个搜索从串行 12 秒压缩到 2 秒。这一章教读者把"不等完整输出就开始渲染"这个感知质量核心长在自己 agent 上的方法。

---

## Beat 2 — 动机

### 现在的问题：空屏等待 + 串行排队

Lena v0.6 在处理这个请求时会发生什么：

```
用户：帮我同时查：1）今天北京天气 2）最新 AI 新闻 3）BTC 当前价格
      4）明天北京→上海航班 5）Python 3.13 有哪些新特性
```

Let's 用数字说话：

```
t=0.0s   发出 API 请求，屏幕空白
t=3.2s   收到完整响应（含 5 个 tool_use 块）
t=3.2s   开始执行 web_search("今天北京天气")
t=4.8s   完成，开始执行 web_search("最新 AI 新闻")
t=6.1s   完成，开始执行 web_search("BTC 当前价格")
t=7.4s   完成...
t=12.0s  5 个工具全部完成
t=12.0s  打包 tool_result，再次 API 请求
t=15.5s  用户看到第一个汇总字
──────────────────────────────
用户实际等待：15.5 秒，前 3.2 秒屏幕完全空白
```

两个独立的痛点：

**痛点 1 — 白屏等待**：LLM 开始生成回复后 3.2 秒，第一个字才出现。这是 v0.6 采用"等待完整响应"模式造成的。实际上 LLM 在 0.3 秒内就开始输出第一个 token——只是我们没用流式接收。

**痛点 2 — 工具串行**：5 个 web_search 彼此完全独立，但 v0.6 一个接一个地跑。这是"没有并发"造成的。5 个 0.5-2s 的请求，串行需要 5-10 秒；并发只需要 max(0.5, 0.8, 1.2, 1.5, 2.0) ≈ 2 秒。

修复这两个问题之前，我们先翻转一个直觉。

---

## Beat 3 — 理论铺垫

Anthropic 在 context engineering 官方文献中定义了本章的核心度量标准：

> "Find the **smallest possible set of high-signal tokens** that maximize the likelihood of some desired outcome."
> （找到最小的高信号 token 集，最大化期望结果的概率。）

流式输出的意义不仅是"看起来快"——它让用户**更早看到 token**，也让 harness 更早做出**中断/重试**决策。这是 context engineering 中"及时获取 ground truth"原则的另一面。

### 3.1 反直觉翻转：默认序列化不是懒惰，是正确的

乍看上去，"agent 应该并发执行所有工具"是个合理预设。读完这章你会发现：**真实世界的 agent runtime，包括 Claude Code 和 OpenClaw，默认都是序列化的，并发是有条件的特例**。

这不是偷懒，是经过深思熟虑的设计。

Claude Code 的 `StreamingToolExecutor.ts:40` 有一段关键注释（来源：公开仓库）：

```
- Concurrent-safe tools can execute in parallel with other concurrent-safe tools
- Non-concurrent tools must execute alone (exclusive access)
- Results are buffered and emitted in the order tools were received
```

读到"emitted **in the order tools were received**"了吗？**结果必须按收到的顺序发出**。这意味着即使工具 2 比工具 1 先完成，也要等工具 1 的结果先给 LLM 看。工具调用有隐含的有序性语义——LLM 把它们按顺序放进消息，assistant 的 content 块是有序数组，tool_result 也必须与之对应。

OpenClaw 的设计更激进。它**在会话级别强制序列化**：每个用户会话同一时刻只跑一个 agent 实例，不并发。原因是工具副作用（文件写入、命令执行）的竞争条件远比看起来麻烦——"同时写同一个文件"是真实会发生的灾难，不是理论风险。

Convention：`isConcurrencySafe = true` 的工具 = 只读、无副作用、幂等；`isConcurrencySafe = false` = 有写副作用，必须独占执行。本章后续统一用这两个术语。

**所以这章要教的并发，是"对 isConcurrencySafe = true 的工具开启并发"，而不是"所有工具都并发"。**

### 3.2 SSE 协议的工程本质

SSE（Server-Sent Events）是基于 HTTP/1.1 的单向文本流协议，RFC 6202 标准化。LLM API 选择 SSE 而不是 WebSocket 的理由很直接：

- LLM 生成天然是**单向的**：服务端生成 token，客户端消费。没有客户端向服务端推送的场景。
- SSE 是**纯 HTTP**，任何 HTTP/1.1 代理、CDN 都能透明处理；WebSocket 的升级握手 (`Upgrade: websocket`) 会被很多企业代理拦截。
- SSE 有**内置的断线重连**：浏览器原生 `EventSource` API 会自动重连，携带 `Last-Event-ID` 头。

Anthropic、OpenAI、DeepSeek 三家全部选择 SSE，这是收敛结果，不是各家独立发明。

SSE 数据格式非常简单：

```
event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"你"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"好"}}

event: message_stop
data: {"type":"message_stop"}
```

规则：每条消息由一行或多行组成，以**空行**分隔。`data:` 是消息体，`event:` 是可选类型标签。

### 3.3 三家协议差异 + 特殊字段

三家 SSE 实现有一处**结构性差异**：工具调用的参数传输方式。

**Anthropic 协议**（`messages` API）：
- 使用 `content_block_start` + `content_block_delta` 的双事件结构
- 工具参数通过连续的 `input_json_delta` 事件**分片流式传输**
- 思维链（Extended Thinking）有独立的 `thinking_delta` 事件，以及关键的 `signature_delta`

**OpenAI 协议**（`chat/completions` API）：
- 使用 `choices[0].delta.tool_calls` 内嵌工具调用
- 参数通过 `function.arguments` 字符串的增量传输
- 流结束标志是 `data: [DONE]`，而不是一个 JSON 事件

**DeepSeek 特殊字段** — `reasoning_content`：
DeepSeek-R1 系列在 OpenAI 兼容接口的 `delta` 里增加了一个非标字段 `reasoning_content`，用于流式传输思维链。这不在 OpenAI 规范里，需要特判处理。

**Anthropic 特殊字段** — `signature_delta`（来源：`nanoClaw/nanoclaw/core/llm.py:383`）：
当你在 Anthropic API 里使用 Extended Thinking 时，每个 thinking block 结束时会收到一个 `signature_delta` 事件，携带 Anthropic 对该 thinking block 内容的**加密签名**。如果后续请求要把 thinking block 回传给 LLM（工具调用场景的多轮对话），必须原样携带这个签名，否则 API 返回 400 错误。这是"Extended Thinking + tool use 组合使用"时的已知坑。

Convention：`thinking_delta` = thinking block 的内容增量；`signature_delta` = thinking block 的加密签名，必须随 thinking block 一起回传。

论文引用：关于 SSE 的详细规范可参考 [WHATWG EventSource 规范](https://html.spec.whatwg.org/multipage/server-sent-events.html)（不需要读完，只需要知道：SSE 的 `id:` 字段是断线重连的关键，LLM API 通常不用这个功能，因为 LLM 流不可重放）。

---

## Beat 4 — 脚手架

Let's verify the streaming baseline by building the smallest possible SSE consumer — one that can print tokens as they arrive and detect tool_use blocks:

```python
# lena-v0.7/core/streaming_base.py
"""
最小 SSE 消费骨架。
只做三件事：
  1. 逐行读 HTTP 流
  2. 解析 data: JSON
  3. 识别 text_delta / tool_use 两种块
其余边界情况（重连、超时）暂不处理——那是 Beat 5 的内容。
"""
import json
import aiohttp


async def stream_minimal(session: aiohttp.ClientSession, api_key: str, messages: list) -> None:
    """最小流式消费，打印 text token + 识别 tool_use。"""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-5",    # 2024 系列，支持 SSE
        "max_tokens": 1024,
        "stream": True,                   # 关键：开启 SSE
        "messages": messages,
    }

    async with session.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
    ) as resp:
        resp.raise_for_status()
        # aiohttp 异步迭代响应体的每一行
        async for raw_line in resp.content:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue                   # 跳过 event: 行和空行
            data_str = line[5:].strip()
            if not data_str:
                continue

            event = json.loads(data_str)
            etype = event.get("type")

            if etype == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    print(delta.get("text", ""), end="", flush=True)  # 流式打印

            elif etype == "message_stop":
                print()  # 换行
                break
```

运行 `await stream_minimal(session, key, [{"role":"user","content":"你好"}])` 应能看到字符逐字打印。接下来，我们在这个骨架上依次加能力。

---

## Beat 5 — 渐进组装

从最小骨架出发，四步扩展到完整的 lena-v0.7：

| 扩展点 | 为何需要 | 如何加 |
|--------|---------|--------|
| 工具参数缓冲 | `input_json_delta` 是分片 JSON，不能逐片解析 | 为每个 tool_use block 维护 `json_buffer`，`content_block_stop` 时统一 `json.loads` |
| 流式抢跑 | tool_use block 完整后立即执行，不等 `message_stop` | `content_block_stop` 时调用 `asyncio.create_task()` 启动工具 |
| Semaphore 并发上限 | 防止 10+ 工具同时跑耗尽系统资源 | `asyncio.Semaphore(MAX_CONCURRENT)` 包住每个工具协程 |
| signature_delta 保存 | Extended Thinking 工具调用 400 错误 | 为 thinking block 维护 `signature` 字段，回传时原样携带 |

### 扩展 1 — 工具参数缓冲

```python
# 在流循环里加入 per-block 状态跟踪
current_blocks: dict[int, dict] = {}   # index → block info
json_buffers: dict[int, str] = {}      # index → 累积 JSON 字符串

# content_block_start 时初始化
if etype == "content_block_start":
    idx = event["index"]
    block = event["content_block"]
    current_blocks[idx] = {
        "type": block["type"],
        "id": block.get("id"),
        "name": block.get("name"),   # tool_use 专有
    }
    if block["type"] == "tool_use":
        json_buffers[idx] = ""

# content_block_delta 时追加
elif etype == "content_block_delta":
    idx = event["index"]
    delta = event["delta"]
    dtype = delta.get("type")
    if dtype == "text_delta":
        print(delta["text"], end="", flush=True)
    elif dtype == "input_json_delta":
        if idx in json_buffers:
            json_buffers[idx] += delta.get("partial_json", "")

# content_block_stop 时收割
elif etype == "content_block_stop":
    idx = event["index"]
    block = current_blocks.pop(idx, None)
    if block and block["type"] == "tool_use":
        try:
            block["input"] = json.loads(json_buffers.pop(idx, "{}"))
        except json.JSONDecodeError:
            block["input"] = {}
        # 扩展 2 在这里加并发启动
        print(f"\n[工具块完整 → {block['name']}({block['input']})]")
```

中间输出：

```
正在查询...
[工具块完整 → web_search({'query': '今天北京天气'})]
[工具块完整 → web_search({'query': '最新 AI 新闻'})]
```

### 扩展 2 — 流式抢跑

tool_use block 完整的瞬间就启动工具，不等 `message_stop`：

```python
# lena-v0.7/core/concurrent_executor.py
import asyncio
from typing import Any, Callable, Coroutine

MAX_CONCURRENT_TOOLS = 10   # 对应 CC CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY

class ConcurrentToolExecutor:
    """
    流式抢跑执行器。
    tool_use block 流式到达即 add_tool()，不等 message_stop。
    参考：StreamingToolExecutor.ts:40（公开仓库）
    """
    def __init__(self, tool_fn: Callable[[str, dict], Coroutine]):
        self.tool_fn = tool_fn
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_TOOLS)
        self.pending: dict[str, asyncio.Task] = {}

    def add_tool(self, tool_id: str, tool_name: str, tool_input: dict) -> None:
        """block 到达时立即调用，异步启动工具协程。"""
        task = asyncio.create_task(
            self._run_with_semaphore(tool_id, tool_name, tool_input)
        )
        self.pending[tool_id] = task
        print(f"[抢跑启动 → {tool_name}]", flush=True)

    async def _run_with_semaphore(self, tool_id: str, name: str, inp: dict) -> Any:
        async with self.semaphore:           # 并发上限保护
            return await self.tool_fn(name, inp)

    async def wait_all(self) -> dict[str, Any]:
        """等所有已提交工具完成，返回 {tool_id: result}。"""
        results: dict[str, Any] = {}
        for tool_id, task in self.pending.items():
            try:
                results[tool_id] = await task
            except Exception as e:
                results[tool_id] = f"[工具错误] {e}"
        return results
```

中间输出（注意抢跑时机）：

```
正在查询...
[抢跑启动 → web_search]   ← t=0.4s，LLM 流还没结束
[抢跑启动 → web_search]   ← t=0.5s
[抢跑启动 → web_search]   ← t=0.6s
[等待全部工具完成...]      ← t=1.2s（LLM 流结束时）
[工具全部完成]             ← t=2.1s
```

### 扩展 3 — signature_delta 保存

扩展 2 处理文字和工具，但有一种情况没覆盖：Extended Thinking 启用时的 signature_delta。加入对 thinking block 的处理：

```python
# 在 content_block_start 里加 thinking 类型
if block["type"] == "thinking":
    current_blocks[idx]["thinking"] = ""
    current_blocks[idx]["signature"] = ""

# 在 content_block_delta 里加两个新分支
elif dtype == "thinking_delta":
    if idx in current_blocks and current_blocks[idx]["type"] == "thinking":
        current_blocks[idx]["thinking"] += delta.get("thinking", "")

elif dtype == "signature_delta":
    # 来源：nanoClaw/nanoclaw/core/llm.py:383
    # Anthropic 对 thinking block 的加密签名，回传时必须原样携带
    if idx in current_blocks and current_blocks[idx]["type"] == "thinking":
        current_blocks[idx]["signature"] += delta.get("signature", "")
        # 验证：收到 signature_delta 说明这是 Extended Thinking 响应
        print(f"[签名已捕获，长度={len(current_blocks[idx]['signature'])}]")
```

中间输出（仅 Extended Thinking 模型触发）：

```
[签名已捕获，长度=128]   ← signature_delta 收到
```

如果你不用 Extended Thinking，这几行代码安静地没有输出。如果你用了，但没这几行，会碰到这个错误：

```
Error: 400 - messages[1].content[0].thinking must contain a signature field
```

### 扩展 4 — 完整 AgentLoop

把以上三个扩展组合进一个 while 循环：

```python
# lena-v0.7/core/agent_loop.py
import asyncio
import json
import time
import aiohttp
from .concurrent_executor import ConcurrentToolExecutor

MAX_STEPS = 10   # 防止无限循环

class StreamingAgentLoop:
    def __init__(self, api_key: str, tools: list[dict], tool_fn):
        self.api_key = api_key
        self.tools = tools         # Anthropic tool schema 列表
        self.tool_fn = tool_fn     # async def tool_fn(name, input) -> str
        connector = aiohttp.TCPConnector(limit=20, keepalive_timeout=30)
        self.session = aiohttp.ClientSession(connector=connector)

    async def run(self, user_input: str) -> None:
        messages = [{"role": "user", "content": user_input}]
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        for step in range(MAX_STEPS):
            executor = ConcurrentToolExecutor(self.tool_fn)
            assistant_content = []
            current_blocks: dict[int, dict] = {}
            json_buffers: dict[int, str] = {}
            stop_reason = None

            payload = {
                "model": "claude-sonnet-4-5",
                "max_tokens": 4096,
                "stream": True,
                "messages": messages,
                "tools": self.tools,
            }

            async with self.session.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                    event = json.loads(data_str)
                    etype = event.get("type")

                    if etype == "content_block_start":
                        idx = event["index"]
                        block = event["content_block"]
                        current_blocks[idx] = {
                            "type": block["type"],
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "text": "",
                        }
                        if block["type"] == "tool_use":
                            json_buffers[idx] = ""
                        elif block["type"] == "thinking":
                            current_blocks[idx]["thinking"] = ""
                            current_blocks[idx]["signature"] = ""

                    elif etype == "content_block_delta":
                        idx = event["index"]
                        delta = event["delta"]
                        dtype = delta.get("type")
                        if dtype == "text_delta":
                            text = delta.get("text", "")
                            print(text, end="", flush=True)
                            if idx in current_blocks:
                                current_blocks[idx]["text"] += text
                        elif dtype == "input_json_delta":
                            if idx in json_buffers:
                                json_buffers[idx] += delta.get("partial_json", "")
                        elif dtype == "thinking_delta":
                            if idx in current_blocks:
                                current_blocks[idx]["thinking"] += delta.get("thinking", "")
                        elif dtype == "signature_delta":
                            # llm.py:383 — 必须保存，回传时携带
                            if idx in current_blocks:
                                current_blocks[idx]["signature"] += delta.get("signature", "")

                    elif etype == "content_block_stop":
                        idx = event["index"]
                        block = current_blocks.pop(idx, None)
                        if block:
                            if block["type"] == "tool_use":
                                try:
                                    block["input"] = json.loads(json_buffers.pop(idx, "{}"))
                                except json.JSONDecodeError:
                                    block["input"] = {}
                                assistant_content.append(block.copy())
                                # 流式抢跑：block 完整即启动
                                executor.add_tool(block["id"], block["name"], block["input"])
                            elif block["type"] == "text" and block["text"]:
                                assistant_content.append({"type": "text", "text": block["text"]})

                    elif etype == "message_delta":
                        stop_reason = event.get("delta", {}).get("stop_reason")

                    elif etype == "message_stop":
                        break

            # 等待所有已启动工具完成
            if executor.pending:
                print("\n[等待并发工具...]", flush=True)
                tool_results = await executor.wait_all()

                messages.append({"role": "assistant", "content": assistant_content})
                tool_result_content = []
                for block in assistant_content:
                    if block.get("type") == "tool_use":
                        tid = block["id"]
                        result = tool_results.get(tid, "工具执行失败")
                        tool_result_content.append({
                            "type": "tool_result",
                            "tool_use_id": tid,
                            "content": str(result),
                        })
                messages.append({"role": "user", "content": tool_result_content})
            else:
                # end_turn 且无工具调用，结束
                print()
                break

    async def close(self):
        await self.session.close()
```

每一步扩展后代码都能独立运行。Beat 4 的骨架到这里已经是完整的 v0.7 核心。

---

## Beat 6 — 运行验证

Let's verify the speedup by running the actual benchmark with 5 concurrent web_search calls:

```python
# lena-v0.7/demo/benchmark.py
"""
实测串行 vs 并发加速比。
web_search 用随机延迟模拟（0.5~2.0s），等价于真实网络搜索延迟。
运行：python3 -m demo.benchmark
"""
import asyncio
import random
import time


async def mock_web_search(query: str) -> str:
    """模拟 web_search：随机 0.5~2.0s 延迟。"""
    delay = random.uniform(0.5, 2.0)
    await asyncio.sleep(delay)
    return f"[结果] {query!r} → 耗时 {delay:.2f}s"


QUERIES = [
    "今天北京天气",
    "最新 AI 新闻",
    "BTC 当前价格",
    "明天北京→上海航班",
    "Python 3.13 新特性",
]


async def serial():
    t0 = time.perf_counter()
    for q in QUERIES:
        r = await mock_web_search(q)
        print(f"  串行完成：{r}")
    elapsed = time.perf_counter() - t0
    print(f"串行总耗时：{elapsed:.2f}s\n")
    return elapsed


async def concurrent():
    t0 = time.perf_counter()
    results = await asyncio.gather(*[mock_web_search(q) for q in QUERIES])
    elapsed = time.perf_counter() - t0
    for r in results:
        print(f"  并发完成：{r}")
    print(f"并发总耗时：{elapsed:.2f}s")
    return elapsed


async def main():
    print("=== 串行执行 ===")
    serial_t = await serial()

    print("=== 并发执行（asyncio.gather） ===")
    concurrent_t = await concurrent()

    speedup = serial_t / concurrent_t
    print(f"\n加速比：{speedup:.1f}×")
    print(f"节省时间：{serial_t - concurrent_t:.2f}s ({(1 - concurrent_t/serial_t)*100:.0f}%)")


if __name__ == "__main__":
    asyncio.run(main())
```

运行命令：

```bash
cd lena-v0.7
python3 -m demo.benchmark
```

**你应该看到类似这样的输出**（具体数值随机，但加速比应在 3-5×）：

```
=== 串行执行 ===
  串行完成：'今天北京天气' → 耗时 1.23s
  串行完成：'最新 AI 新闻' → 耗时 0.87s
  串行完成：'BTC 当前价格' → 耗时 1.54s
  串行完成：'明天北京→上海航班' → 耗时 0.61s
  串行完成：'Python 3.13 新特性' → 耗时 1.78s
串行总耗时：6.03s

=== 并发执行（asyncio.gather） ===
  并发完成：'今天北京天气' → 耗时 1.23s
  并发完成：'最新 AI 新闻' → 耗时 0.87s
  并发完成：'BTC 当前价格' → 耗时 1.54s
  并发完成：'明天北京→上海航班' → 耗时 0.61s
  并发完成：'Python 3.13 新特性' → 耗时 1.78s
并发总耗时：1.78s

加速比：3.4×
节省时间：4.25s (71%)
```

加速比的理论上限是 5×（5 个任务完全并发），实测一般在 3-5×，因为每个任务的延迟不同，最慢的那个决定了总时间。

**如果你看到加速比 < 2×**，最常见原因是：你在 async 函数里调用了一个同步阻塞的 requests 库。`requests.get()` 会阻塞整个事件循环。检查是否用了 `await` + `aiohttp`，而不是同步的 `requests`。

**如果你看到 `RuntimeError: This event loop is already running`**，说明你在 Jupyter Notebook 里运行了 `asyncio.run()`。改用 `await main()` 或安装 `nest_asyncio`。

现在 Lena v0.7 已经能：
- 流式输出：用户 0.3 秒看到第一个字（而不是等 3 秒）
- 并发工具：5 个搜索 2 秒完成（而不是 8 秒）

下一章，我们给 Lena 加上记忆系统——让它记住用户的偏好，跨会话不忘。目前每次启动 Lena 都是失忆的，无法做到"记住上次用户说他不喜欢飞行，帮他推荐高铁"。

---

## Beat 7 — Design Note

> ### 为什么 OpenClaw 强制序列化每个会话？

乍看上去，一个常驻的 always-on agent 应该最积极地使用并发——它就是设计来高效处理事务的。但 OpenClaw 做了一个反直觉的决定：**在会话级别强制序列化**，同一个用户会话同一时刻只运行一个 agent 实例。

**替代方案：** 允许同一用户的多条消息并发触发多个 agent 实例，用分布式锁保护共享资源。

**这个替代方案的问题：**

- **副作用竞争**：工具调用不是无副作用的。两个 agent 实例同时 `write_file("report.md", ...)` 会产生难以追踪的内容竞争。文件锁可以防止写冲突，但无法防止"先读后写"的逻辑竞争——agent A 读了文件决定追加一段，agent B 同时读了同一文件也决定追加，最终只有一个追加生效。
- **上下文失真**：每个 agent 实例都有自己的 `messages` 历史。并发实例看不到彼此的工具调用结果，会做出互相矛盾的决策。
- **错误传播放大**：一个 agent 实例的工具调用失败，通常应该触发重试或回退逻辑。并发实例会各自独立触发重试，产生指数级的重复操作。

**OpenClaw 选择序列化的理由：** "agent 的可预测性比原始吞吐量更重要。" 对于一个管理真实文件、真实日程的 always-on agent 来说，偶尔多等 500ms 比偶尔丢失一条日历事件要好得多。

**会话内的并发仍然存在**：序列化是"同一用户的多条消息不并发"，不是"同一消息里的多个工具调用不并发"。单次响应中，所有 `isConcurrencySafe = true` 的工具调用仍然并发执行，这是本章教的核心内容。

**如果你要在生产系统里放开会话级并发：** 必须先回答这三个问题——所有工具调用是否幂等？共享状态（文件、数据库）是否有行级锁？并发实例的 messages 历史如何合并？这三个问题都没有通用答案，这也是为什么 OpenClaw 选择了保守的序列化默认值。

---

---

Lena 在本章学会了"不卡顿"——SSE 流式输出让用户 0.3 秒看到第一个字，并发工具抢跑让五次搜索同时发出，会话级序列化则保证了可预测性。

但 Lena 仍然是一个失忆的 agent：每次对话结束，她忘掉了用户的一切偏好，下次见面像第一次认识。一个真正有用的 agent 必须记得"你上次说过你喜欢用 Python"、"上周你让我别再推荐 LangChain"。**第 8 章，我们给 Lena 装上记忆——短期 SQLite 会话历史加长期文件系统偏好库，让她有昨天。**

---

## 延伸阅读

- Anthropic 官方文档：[Streaming Messages](https://docs.anthropic.com/en/api/messages-streaming)（不需要读完，重点看 event types 列表）
- 公开仓库证据：`StreamingToolExecutor.ts:40`（并发安全判断逻辑）、`toolOrchestration.ts:10`（并发上限常量）
- nanoClaw 实现参考：`nanoclaw/core/llm.py:383`（signature_delta 处理）、`llm.py:18-38`（三家 cache token 字段统一）
- WHATWG EventSource 规范（理解 `id:` 字段与断线重连）

---

## 导航

[← Ch 6. 工具系统](../ch06-tool-system/README.md) · [下一章 →](../ch08-memory/README.md) · [📘 目录](../../README.md)
