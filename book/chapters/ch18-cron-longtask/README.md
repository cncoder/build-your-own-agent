# 第 18 章：Cron 与长耗时任务

> **Lena 演进**：v0.17（网关 + 心跳）→ **v0.18**（cron 调度器 + SQLite 断点续传 + 崩溃恢复）
> **支柱**：Long-horizon 执行

---

## Beat 1 — 路线图

```
Ch 15 网关 ─► Ch 16 MessageBus ─► Ch 17 心跳 ─► [Ch 18 ← 你在这里] ─► Ch 19 MCP
                                                    ↑
                                       lena-v0.17 → lena-v0.18
```

Lena 现在可以在后台常驻，每天早上打个招呼。但"打招呼"是一次性动作——耗时不到一秒，失败了明天重试，什么都不会丢。

本章要解决一类不同的任务：**运行数小时的工作**。Lena 将要每小时抓取一次新闻，持续整整一天，积累 24 批次，最后在午夜汇总所有内容。这是 24 个顺序步骤跨越 24 小时。如果进程在第 17 步崩溃，正确行为是从第 18 步恢复——而不是从第 1 步重来。

本章 arc：从 `croniter` 开始，这是一个不产生时钟漂移的 10 行调度器，在墙钟时间精确触发 → 然后加入 SQLite 断点引擎，让每个步骤都具备崩溃安全性 → 再把两者拼接成完整的新闻摘要流水线 → 接着考察内容哈希缓存，这是让断点思想自然延伸到任何昂贵重复计算的技术 → 最后看看这个想法的生产版本为什么需要 30+ 个模块，以及这些复杂性是不是必要的。

本章结束后，Lena v0.18 在任何时刻被 `kill -9` 都能从断点处精确恢复。让每小时新闻抓取具备韧性的断点原则，与 LangGraph、Temporal 以及每一个持久化工作流引擎使用的原则完全相同——我们实现的是核心思想，不是它的玩具近似。

> **🧠 聪明度增量（v0.17 → v0.18）**：Lena 第一次能跨天持续干活——croniter 无漂移调度 + SQLite 断点引擎让 24 步跨越 24 小时的流水线在 kill -9 后从断点精确恢复，不再从头重来。这一章教读者把长任务韧性与 checkpoint 模式长在自己 agent 上的方法。

---

## Beat 2 — 动机

下面是一个 24 小时流水线的朴素实现：

```python
# BAD：没有断点——一次崩溃清零 11 小时的工作  [错误示例]
def daily_news_pipeline():
    articles = []
    for hour in range(24):
        batch = fetch_news(hour)   # 每次调用约 2 秒
        articles.extend(batch)
        time.sleep(3600)
    summarize(articles)            # 只有全部 24 次成功才能到达这里
```

在午夜启动这个脚本。上午 11 点——已经跑了 11 小时、收集了 11 批次——机器因内核更新重启。进程重启时，`articles` 在内存中是空列表。已完成的 11 次抓取全部丢失。流水线从第 0 小时重新开始。

浪费的总工作量：11 次 API 调用、约 22 秒网络时间，以及——因为流水线现在还要再跑 24 小时——摘要晚了 11 个小时。

在付费新闻 API 上的具体成本：如果每次 `fetch_news` 调用花 $0.005，从午夜到中午的单次崩溃浪费 $0.055 并把摘要延迟 24 小时。一年中有 10 天容易崩溃（内核更新、电源闪动、OOM kill、其他进程的内存压力），那就是 $0.55 的直接成本和 10 次错过的摘要。对于每步花 $0.50 API 调用的 LLM 密集型流水线，这些数字变成每次崩溃 $5 和真实的信息损失。

`sleep(3600)` 还有第二个更隐蔽的问题：时钟漂移。如果 `fetch_news` 耗时 4 秒，流水线在午夜、凌晨 1:00:04、凌晨 2:00:08 运行……到中午，调度已经从预定的每小时节奏漂移了 1.6 分钟。第二天进程重启时，没有"上次什么时候运行"的记录——所以没有办法知道错过的那次是否应该补跑。`croniter` 在墙钟分钟精确触发，并提供 `get_prev()` 来回答"我宕机期间本应运行什么？"

---

## Beat 3 — 理论铺垫

### 3.1 Cron 表达式（本节无代码）

Cron 表达式是五个空格分隔的字段，描述一个周期性时间点。每个字段约束墙钟的一个组件：

```
 ┌─ 分钟 (0–59)
 │  ┌─ 小时 (0–23)
 │  │  ┌─ 月中第几天 (1–31)
 │  │  │  ┌─ 月份 (1–12)
 │  │  │  │  ┌─ 星期几 (0–6, 0=周日)
 *  *  *  *  *
```

`*` 通配符表示"该字段的任何有效值"。`/N` 修饰符表示"从下界开始每第 N 个值"。`,` 运算符列举特定值。几个值得记住的表达式：

| 表达式 | 触发时机 | 典型用途 |
|--------|---------|---------|
| `0 * * * *` | 每小时第 0 分 | 每小时数据抓取 |
| `0 8 * * *` | 每天 08:00 | 早间摘要 |
| `0 0 * * *` | 每天午夜 | 每日汇总 |
| `*/15 * * * *` | 每 15 分钟 | 健康检查 |
| `0 0 * * 0` | 每周日午夜 | 每周报告 |
| `0 2 1 * *` | 每月 1 日 02:00 | 月度账单 |
| `0 8-18 * * 1-5` | 工作日每天 08:00–18:00 每小时 | 工作时间轮询 |

`croniter` 是一个解析这些表达式的 Python 库，提供两个方法。`get_next(datetime)` 返回给定时刻之后的下一个计划时间——在任务触发后用于设置 `next_run`。`get_prev(datetime)` 返回给定时刻之前最近的计划时间——在进程重启时用于检查宕机期间是否错过了某次运行。两个方法都会推进内部迭代器，所以你可以反复调用 `get_next` 来枚举完整的未来计划。

Convention：**cron 表达式（cron expression）** = 描述周期性计划的 5 字段字符串；**cron 触发（cron trigger）** = 基于该表达式任务实际触发的具体 datetime；**错过的触发（missed trigger）** = 进程未运行期间发生的 cron 触发。

### 3.2 持久化执行与断点原则（本节无代码）

长耗时任务的可靠性完全取决于其断点策略。"持久化执行（durable execution）"这个术语——在 LangGraph（参见 [LangGraph persistence docs](https://langchain-ai.github.io/langgraph/concepts/persistence/)）和 Temporal 等系统中使用——描述一种运行时属性：**任务可以在任何时刻被中断，并从最后提交的状态恢复**，就好像中断从未发生过。

持久化执行的最小可行版本是：在开始下一步之前，将每一步的结果写入持久化存储。如果进程在第 N 步和第 N+1 步之间崩溃，下次启动时读取存储，发现步骤 0 到 N 已完成，从 N+1 开始。不重新计算，不丢失数据。

要使这一机制正确工作，必须满足三个不变式：

**不变式 1 — 幂等性（Idempotency）。** 重新运行一个已完成的步骤必须是安全的，不产生副作用。标准 SQL 技术是在 `(task_id, step_id)` 上加 `UNIQUE` 约束，结合 `INSERT OR IGNORE`。如果行已存在，插入是静默无操作。函数返回 `False`（表示"已存在"）而非 `True`（表示"新插入"），调用者知道跳过重新处理。

**不变式 2 — 原子性（Atomicity）。** 步骤结果和"步骤已完成"标记必须在同一个事务中一起落入存储。设想没有原子性会发生什么：你写了结果，进程在写完成标记前崩溃，重启后步骤再次运行——产生重复结果，并可能产生重复副作用（又一条 Slack 消息、又一行数据库记录、又一次扣款）。SQLite 的事务语义（WAL 模式支持并发读者）免费给你这个保障。

**不变式 3 — 确定性步骤标识（Deterministic step identity）。** 每个步骤需要一个稳定标识符，在重新运行时保持不变。最简单的选择是顺序名称（`"fetch_hn"`、`"fetch_github"`）。更强大的选择是内容哈希：`sha256(source_id + content)`。内容哈希把幂等性从"这个具名步骤"扩展到"这个确切内容，无论何时何地处理"。当同一篇新闻文章可能出现在两次不同的每小时抓取中，或者一个 TTS 合成任务可能在不同日期以相同文本重新提交时，这很重要。

Convention：**断点（checkpoint）** = 已完成步骤的持久化记录，包括其结果数据和完成时间戳；**续传（resume）** = 在进程启动时读取现有断点并跳过已完成步骤；**step_id** = 用于将运行中的步骤与其断点匹配的稳定标识符。

### 3.3 为什么是 SQLite，不是文件，不是 Redis（本节无代码）

SQLite 的明显替代方案值得明确排除。

**普通 JSON 文件**很诱人，因为它简单：`json.dump(state, f)`。问题：写一个大 JSON 文件不是原子操作。如果进程在写到一半时崩溃，你得到一个截断或格式错误的文件，在下次启动时无法解析——这比没有断点更糟糕，因为代码可能会静默地从头开始而不报错。你可以用"写临时文件再重命名"（`tmp` + `os.replace`）来规避，但那时你在重新实现 SQLite 已经提供的功能的一个子集，而且没有可查询性。

**Redis** 很快、支持原子操作、有内置过期。问题：它需要一个运行中的外部服务。断点存储可能在进程启动时不可用，这造成了复合失败模式——两个独立系统都可能失败，而不是一个。SQLite 是本地磁盘上的一个文件；它只在磁盘故障时失败，这与进程本身的失败模式相同。

**Python 标准库的 `shelve` 模块**底层使用 `dbm`。`dbm` 后端因平台而异（Linux 上是 `gdbm`，macOS 上是 `ndbm`），没有事务保障，不支持无锁并发读取。它适合简单的持久化字典，不适合有并发读取访问的多步骤断点表。

SQLite 胜出因为它：零配置（单文件）、默认崩溃安全（WAL 日志模式）、原生原子（事务）、Python 标准库自带（无需安装）、可用标准 SQL 查询（汇总任务可以直接 `SELECT * FROM task_results WHERE task_id = ?`，无需反序列化复杂数据结构）。

一个值得理解的细节：Python 的 `sqlite3.connect(path)` 返回一个连接对象。作为上下文管理器使用（`with sqlite3.connect(path) as conn:`）时，正常退出时提交，异常时回滚。这与关闭连接不同——如果你长时间持有连接，应该显式调用 `conn.close()`。对于本章的短生命周期操作，上下文管理器模式是正确的。

SQLite WAL 模式（`PRAGMA journal_mode=WAL`）提升并发读性能——写入者活跃时多个读取者可以同时访问数据库。对于单进程流水线不是必须的。如果你添加了一个独立的状态看板或监控进程，在调度器写入时查询断点表，再加上它。

---

## Beat 4 — 脚手架

先独立构建断点引擎，作为一个没有调度器依赖的独立模块。本节的目标是一个可以导入、调用、并立即隔离测试的模块。

以下骨架处理 Beat 3 中的三个不变式：通过 `PRIMARY KEY` 实现幂等性，通过单个 `sqlite3.connect` 上下文管理器（正常退出时提交）实现原子性，以及返回 Python `set` 以实现 O(1) 成员测试的查询函数。

```python
# core/checkpoint.py — 最小可行断点引擎（约 55 行）
import sqlite3, json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/lena.db")

def init_db():
    """
    如果表不存在则创建。每次重启都可安全调用。
    CREATE TABLE IF NOT EXISTS 模式使这完全幂等。
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_results (
                task_id      TEXT NOT NULL,
                step_id      TEXT NOT NULL,
                result_data  TEXT,             -- JSON blob
                completed_at TEXT NOT NULL,
                PRIMARY KEY (task_id, step_id) -- 幂等性键
            )
        """)
        conn.commit()

def save_step(task_id: str, step_id: str, data: dict) -> bool:
    """
    持久化一个已完成的步骤。
    返回 True 表示新插入，False 表示已存在（不是错误）。
    INSERT OR IGNORE 是"最多写一次"的 SQL 写法。
    """
    now = datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO task_results
               (task_id, step_id, result_data, completed_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, step_id, json.dumps(data), now),
        )
        conn.commit()
        return cursor.rowcount == 1   # 1 = 已插入；0 = 已存在

def completed_steps(task_id: str) -> set[str]:
    """
    返回该任务已持久化的 step_id 集合。
    如果任务未知，返回空集合（不抛出异常）。
    """
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT step_id FROM task_results WHERE task_id = ?",
            (task_id,),
        ).fetchall()
    return {row[0] for row in rows}
```

在添加任何东西之前先验证幂等性保障：

```python
>>> from core.checkpoint import init_db, save_step, completed_steps
>>> init_db()
>>> save_step("test-task", "step-0", {"value": 42})
True    # 新插入
>>> save_step("test-task", "step-0", {"value": 999})
False   # 已存在——数据未改变
>>> completed_steps("test-task")
{'step-0'}
```

第二次 `save_step` 返回了 `False`，没有覆盖原来的 `{"value": 42}`。这就是幂等性保障：步骤一旦保存，就不会被意外覆写。这是崩溃恢复所需的唯一保障——其余的都从这里推出来。

---

## Beat 5 — 渐进组装

我们有了断点引擎。现在逐一添加流水线需要的组件。

| 扩展点 | 为何需要 | 如何添加 |
|--------|---------|---------|
| `croniter` 调度器 | 在墙钟时间精确触发，不产生漂移；检测错过的运行 | 在 1 秒轮询循环中使用 `croniter(expr, now).get_next(datetime)` |
| 带续传的抓取任务 | 重启时跳过数据库中已有的步骤 | `if step_id in completed_steps(task_id): continue` |
| 内容哈希去重 | 不同日期出现的同一篇文章第二次无成本 | 用 `sha256(source + content)` 作为 step_id |
| 午夜汇总 | 把所有每小时步骤聚合成一次 LLM 调用 | 对 `task_results` 用 SQL 查询，过滤今天的 fetch task_id |

**扩展 1 — croniter 调度器**

调度器是一个紧凑循环：每秒检查是否有任务的 `next_run` 已过。如果已过，触发任务，捕获任何异常以防一个任务的失败影响其他任务，然后调用 `get_next()` 设置下一次触发时间。

```python
# scheduler.py
import time, logging
from croniter import croniter
from datetime import datetime

log = logging.getLogger(__name__)

class Scheduler:
    def __init__(self):
        self._jobs: list[dict] = []

    def add(self, expr: str, fn, name: str):
        it = croniter(expr, datetime.now())
        next_run = it.get_next(datetime)
        self._jobs.append({"name": name, "fn": fn, "next": next_run, "it": it})
        log.info(f"scheduled [{name}]  next_run={next_run.isoformat()}")

    def run_forever(self):
        log.info(f"scheduler started — {len(self._jobs)} job(s)")
        while True:
            now = datetime.now()
            for job in self._jobs:
                if now >= job["next"]:
                    log.info(f"firing [{job['name']}]")
                    try:
                        job["fn"]()
                    except Exception as exc:
                        log.error(f"[{job['name']}] error: {exc}", exc_info=True)
                    # 无论成功失败都推进
                    job["next"] = job["it"].get_next(datetime)
                    log.info(f"[{job['name']}] next_run={job['next'].isoformat()}")
            time.sleep(1)
```

两个任务在 12:00:47 注册时的预期输出：

```
12:00:47 INFO scheduled [fetch-news]  next_run=2026-05-05T13:00:00
12:00:47 INFO scheduled [summarize]   next_run=2026-05-06T00:00:00
12:00:47 INFO scheduler started — 2 job(s)
```

`croniter(expr, datetime.now())` 构造函数以"现在"为迭代器的锚点。第一次 `get_next()` 推进到当前秒之后，所以一个在 12:47 启动、表达式为 `"0 * * * *"` 的调度器会把第一次抓取安排在 13:00，而不是 12:00。这是预期行为——你想要下一个计划时间，而不是最近的过去时间。

**扩展 2 — 带断点续传的抓取任务**

抓取任务有一个结构性模式：每次运行开始时，加载已完成步骤的集合，然后遍历所有数据源，跳过已在集合中的任何步骤。

```python
# tasks/fetch_news.py
import hashlib, time, logging, random
from core.checkpoint import save_step, completed_steps

log = logging.getLogger(__name__)
SOURCES = [
    {"id": "hn",     "name": "Hacker News"},
    {"id": "github", "name": "GitHub Trending"},
    {"id": "arxiv",  "name": "arXiv ML"},
]

def run(task_id: str):
    done = completed_steps(task_id)
    log.info(f"[{task_id}] {len(done)}/{len(SOURCES)} 步骤已完成")

    for source in SOURCES:
        step_id = f"fetch_{source['id']}"
        if step_id in done:
            log.info(f"  [skip] {step_id}")
            continue

        articles = _fetch(source["id"])
        saved = save_step(task_id, step_id, {"count": len(articles), "items": articles})
        log.info(f"  [checkpoint] {step_id} — {len(articles)} 篇文章 (new_row={saved})")

def _fetch(source_id: str) -> list[dict]:
    """模拟实现。替换为真实的 RSS/API 调用。"""
    return [{"title": f"[mock] {source_id} #{i}", "url": f"https://example.com/{i}"}
            for i in range(random.randint(3, 8))]
```

通过在 `fetch_hn` 之后运行任务、然后终止进程（或抛出异常），再重新运行，来模拟崩溃：

```
第一次运行：
  [news-2026-05-05] 0/3 步骤已完成
  [checkpoint] fetch_hn     — 7 篇文章 (new_row=True)
  ← 在这里崩溃 →

第二次运行（重启后）：
  [news-2026-05-05] 1/3 步骤已完成
  [skip] fetch_hn           ← 没有网络调用
  [checkpoint] fetch_github — 5 篇文章 (new_row=True)
  [checkpoint] fetch_arxiv  — 4 篇文章 (new_row=True)
```

第二次运行恰好发起了 2 次网络调用，而不是 3 次。这就是断点保障在可观测输出中的体现。

**扩展 3 — 内容哈希 step ID**

基于顺序的 step ID（`"fetch_hn"`）在任务结构固定时有效。但考虑一个处理每篇文章正文的流水线——用 LLM 生成摘要或嵌入。不同日期可能在 Hacker News 顶部返回同一篇文章。用基于顺序的 ID，第 2 天重新处理了第 1 天已经处理过、数据库里已有结果的内容。用内容哈希 ID，第 2 天立刻找到现有结果并跳过 LLM 调用。

```python
import hashlib

def content_step_id(source: str, article_id: str) -> str:
    """
    由内容身份确定的确定性 step_id，而非位置。
    相同 source + 相同 article_id = 相同哈希，无论这篇文章
    在何时、以何种方式出现在抓取结果中。
    """
    return hashlib.sha256(f"{source}:{article_id}".encode()).hexdigest()[:16]

# 在逐篇文章的 LLM 处理循环中使用：
def process_articles(task_id: str, articles: list[dict], source: str):
    done = completed_steps(task_id)
    for article in articles:
        step_id = content_step_id(source, article["id"])
        if step_id in done:
            continue   # 确切内容已处理——LLM 结果已在数据库中
        summary = llm_summarize(article["body"])   # 每篇独特文章一次 LLM 调用
        save_step(task_id, step_id, {"summary": summary, "title": article["title"]})
```

内容哈希 ID 和顺序 ID 可以在同一个断点表中共存——它们只是字符串。当步骤由其在工作流中的位置定义时用顺序 ID（抓取第 N 个数据源，每个任务运行一次）。当步骤由它处理的数据定义时用内容哈希 ID（分析这篇特定文章，每个独特内容运行零次或一次）。

内容哈希 step ID 和顺序 step ID 可以共存——它们只是字符串。这就是**断点续传**原则在内容层而非顺序层的应用：顺序 ID 给你位置级别的续传；内容哈希 ID 给你身份级别的续传。

有一个重要限制：内容哈希缓存假设步骤的输入决定其输出。如果步骤结果依赖于外部状态（今天的股价、当前天气），昨天的缓存结果就过期了。对于这类步骤，加入 TTL：在结果旁边存储 `expires_at` 列，在 `completed_steps` 中将过期行视为不存在。

**插曲——三种调度原语对比**

在添加汇总任务之前，值得把 `croniter` 放在它之前的两种替代方案中定位。

`time.sleep(N)` 是调度的"Hello World"。对于需要运行一次然后等待固定间隔再下次运行的任务，它是正确的。它有两个失败模式：漂移（如果任务耗时非零，每次调用都比前一次晚）和失忆（进程重启时没有上次运行时间的记录）。

第 17 章 Lena 的 `Heartbeat` 使用了 `setTimeout` 风格的回调。这在简单情况下功能上等价于 `sleep`。心跳在启动时触发，然后把自己安排在 N 秒后再次触发。它避免了一些漂移，但仍然没有固定墙钟计划的概念，也没有崩溃后恢复的行为。

`croniter` 加墙钟轮询解决了两个问题。计划以绝对时间定义（`"0 * * * *"` 表示"每小时第 0 分"），而不是相对时间（"上次运行后 60 秒"）。`get_prev()` 方法回答"现在之前最后一次计划时间是什么？"，这实现了错过触发的补跑。

| 原语 | 漂移 | 错过触发感知 | 典型用途 |
|------|------|------------|---------|
| `time.sleep(N)` | 有——每次运行累积 | 无 | 重试循环、简单轮询 |
| 心跳回调 | 极小 | 无 | 主动通知 |
| `croniter` + 墙钟 | 无 | 有，通过 `get_prev()` | 调度流水线、每日报告 |

对于本章的流水线——应该在每小时整点精确触发的每小时抓取——croniter 是正确的选择。

**扩展 4 — 午夜汇总任务**

汇总任务聚合今天 `task_id` 下保存的所有步骤，把文章标题传给 Claude，并对结果做断点。开始时的幂等性检查确保 LLM 调用最多发生一次，即使进程在调用之后、断点写入之前重启。

```python
# tasks/summarize.py
import json, sqlite3, logging, os
from core.checkpoint import DB_PATH, save_step, completed_steps, all_steps

log = logging.getLogger(__name__)
MAX_ARTICLES = 40   # 成本控制：限制发给 Claude 的标题数量

def run(summary_task_id: str, fetch_task_id: str):
    done = completed_steps(summary_task_id)
    if "summary" in done:
        log.info(f"[{summary_task_id}] 已完成——跳过")
        return

    steps = all_steps(fetch_task_id)
    if not steps:
        log.warning(f"[{summary_task_id}] {fetch_task_id} 没有抓取数据")
        return

    all_articles = []
    for step in steps:
        all_articles.extend(step["data"].get("items", []))

    log.info(f"[{summary_task_id}] 来自 {len(steps)} 个数据源的 {len(all_articles)} 篇文章")

    titles = "\n".join(f"- {a['title']}" for a in all_articles[:MAX_ARTICLES])

    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content":
            f"用 3 条要点总结以下 {len(all_articles)} 条新闻标题：\n{titles}"}],
    )
    text = resp.content[0].text
    save_step(summary_task_id, "summary", {"text": text, "article_count": len(all_articles)})
    log.info(f"[{summary_task_id}] 已保存摘要（{len(text)} 字符）")
```

注意 `all_steps(fetch_task_id)` 是一个查询数据库并按顺序返回给定 `task_id` 所有行的辅助函数。这是 SQL 的自然用途，普通文件或内存字典无法同样干净地支持。

---

## Beat 6 — 运行验证

组装并验证完整流水线。完整的 `main.py` 把所有组件拼接在一起：

```python
# main.py
import logging
from datetime import date
from core.checkpoint import init_db
from scheduler import Scheduler
from tasks import fetch_news, summarize

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S")

def main():
    init_db()
    today = date.today().isoformat()
    fetch_task_id   = f"news-{today}"
    summary_task_id = f"summary-{today}"

    s = Scheduler()
    s.add("0 * * * *", lambda: fetch_news.run(fetch_task_id),                "fetch-news")
    s.add("0 0 * * *", lambda: summarize.run(summary_task_id, fetch_task_id), "summarize")
    s.run_forever()

if __name__ == "__main__":
    main()
```

安装并运行：

```bash
pip install croniter anthropic
export ANTHROPIC_API_KEY=sk-ant-...   # 模拟模式下可省略
python main.py
```

12:00:47 全新启动时的预期输出：

```
12:00:47  INFO  scheduled [fetch-news]  next_run=2026-05-05T13:00:00
12:00:47  INFO  scheduled [summarize]   next_run=2026-05-06T00:00:00
12:00:47  INFO  scheduler started — 2 job(s)
# ... 安静直到 13:00:00 ...
13:00:00  INFO  firing [fetch-news]
13:00:00  INFO  [news-2026-05-05] 0/3 步骤已完成
13:00:00  INFO    [checkpoint] fetch_hn     — 6 篇文章 (new_row=True)
13:00:00  INFO    [checkpoint] fetch_github — 8 篇文章 (new_row=True)
13:00:00  INFO    [checkpoint] fetch_arxiv  — 5 篇文章 (new_row=True)
13:00:00  INFO  [fetch-news] next_run=2026-05-05T14:00:00
```

要验证崩溃恢复而不用等一小时，使用完全绕过调度器的 `quick_test.py`：

```bash
python quick_test.py
```

预期输出（简化）：

```
=== 第一次运行 ===
  [checkpoint] fetch_hn     — 8 篇文章 (new_row=True)
  [checkpoint] fetch_github — 5 篇文章 (new_row=True)
  [checkpoint] fetch_arxiv  — 7 篇文章 (new_row=True)
第一次运行后已完成步骤：{'fetch_github', 'fetch_arxiv', 'fetch_hn'}

=== 第二次运行（模拟重启）===
  [skip] fetch_hn    — 已在数据库中
  [skip] fetch_github — 已在数据库中
  [skip] fetch_arxiv  — 已在数据库中
已完成步骤不变：{'fetch_github', 'fetch_arxiv', 'fetch_hn'}

=== 汇总 ===
  [summary-test] 来自 3 个数据源的 20 篇文章
  [mock summary] 20 篇文章来自 3 个数据源。

所有检查通过。
```

数字——8、5、7 篇文章——来自模拟的 `random.randint`。你的运行会有所不同，但结构应该一致。第一次运行三行 `[checkpoint]`，第二次运行三行 `[skip]`，没有浪费任何网络调用。

一整天中任务状态机的演变：

```
00:00  fetch_news.run("news-2026-05-05")
         [checkpoint] fetch_hn     — new_row=True
         [checkpoint] fetch_github — new_row=True
         [checkpoint] fetch_arxiv  — new_row=True

01:00  fetch_news.run("news-2026-05-05")
         [skip] fetch_hn           — 已在数据库中（这一天的每小时运行是幂等的）
         [skip] fetch_github
         [skip] fetch_arxiv
     ← 等等，这是错的——每小时运行应该抓取新的文章

     修法：在 task_id 中包含小时。
     fetch_task_id = f"news-{today}-hour-{hour}"
     每小时有自己的任务命名空间，所以每小时的抓取是独立的。

     或：在 step_id 中包含小时。
     step_id = f"fetch_{source}_{datetime.now().strftime('%H')}"
     两种方法都有效；任务级命名空间（第一种）更干净。

修法后，24 个独立的 task_id 在一天中累积：
  "news-2026-05-05-hour-00" → {fetch_hn, fetch_github, fetch_arxiv}
  "news-2026-05-05-hour-01" → {fetch_hn, fetch_github, fetch_arxiv}
  ...
  "news-2026-05-05-hour-23" → {fetch_hn, fetch_github, fetch_arxiv}

午夜：
  summarize.run("summary-2026-05-05")
    读取今天所有 24 个 task_id
    聚合所有文章
    调用 Claude
    [checkpoint] summary — new_row=True
```

为简单起见，本章代码每天使用一个 `task_id`，把三个数据源作为完整的步骤集。在真实流水线中，每小时粒度会如上所示在 `task_id` 或 `step_id` 中体现。无论如何，断点不变式是相同的。

**常见失败及其原因：**

- `sqlite3.OperationalError: no such table: task_results` — 第一次数据库操作之前没有调用 `init_db()`。修法：在进程启动时、启动调度器之前调用 `init_db()`。
- 第二次运行仍然显示 `[checkpoint]` 行 — `PRIMARY KEY (task_id, step_id)` 约束缺失，或者 `INSERT OR IGNORE` 写成了 `INSERT OR REPLACE`。`INSERT OR REPLACE` 会删除后重新插入，如果其他列有变化就不是幂等的。
- `croniter` 在启动时立即触发 — 你把 `start_time` 作为参数传给了构造函数，而不是作为锚点时间。`croniter(expr, datetime.now())` 以"现在"为锚点；`get_next()` 给你锚点之后的下一个未来触发时间。
- 多小时后内存增长 — `_fetch` 内的 `articles` 列表在调用间被累积在内存中。每次调用 `fetch_news.run()` 创建一个新作用域，所以这不应该发生。如果你看到增长，检查模块级可变状态（例如全局 `articles` 列表）。

---

### Context Reset vs Compaction：长任务的另一个维度

本章的断点续传解决了**外部状态**的持久化（磁盘上的 checkpoint）。但还有一个内部问题：**LLM 本身的 context window 在长任务中会爆掉**。

Anthropic 2026 年 3 月的 harness design 实验揭示了两种应对策略的优劣：

| 策略 | 做法 | 优势 | 代价 |
|---|---|---|---|
| **Compaction** | 把旧对话压缩成摘要，agent 继续跑 | 保持连续性 | context anxiety 未解——agent 仍感知"快满了" |
| **Context Reset** | 清空 context，启动新 agent，用结构化 artifact 交接状态 | 彻底消除 context anxiety | 需要设计 handoff artifact，多了编排复杂度 |

Anthropic 实测发现 Claude Sonnet 4.5 的 **context anxiety 足够强烈**——仅靠 compaction 不足以维持长任务性能，必须用 context reset。

> "Context resets—clearing the context window entirely and starting a fresh agent, combined with a structured handoff that carries the previous agent's state—addresses both context anxiety and coherence loss."
> （来源：Anthropic, *Harness design for long-running application development*, 2026-03-24）

对 Lena 的启示：Ch10 讲了 compaction（压缩）；本章讲了 checkpoint（断点）。但真正的生产级长任务 agent 需要**三者联动**：compaction 延缓 context 膨胀 → 到达阈值时 context reset → 用 checkpoint artifact 交接 → 新 agent 从断点恢复。这就是为什么 Ch17 Heartbeat + Ch18 Cron + Ch10 Context Engineering 三章是一个整体。

---

## Beat 7 — Design Note

> **为什么不把长耗时任务设计成可以从零重启？**

显然的替代方案是让每个任务无状态：如果进程在运行中途崩溃，删除所有部分结果并从头开始。在两种情况下这是合理策略：当每个步骤足够便宜，重新运行一切的成本低于构建和维护断点系统的成本；以及当每个步骤真正无副作用时（重新运行产生相同结果且没有外部后果）。

当任务具备以下三种属性之任意一种时，这种权衡就变得不利：

**昂贵的步骤。** 一个花 $0.02 耗时 8 秒的 LLM 调用，如果崩溃发生在调用完成 10 秒后，就不值得重跑。成本既有财务的也有时间的。一个 24 步流水线，每步花 $0.02，崩溃在第 23 步，零重启策略浪费 $0.46 和 3 分钟。有了断点，重启只花一步：$0.02 和 8 秒。

**有副作用的步骤。** 如果一个步骤发送了 Slack 通知、写入外部数据库、触发了支付或发布了消息到频道，无论成本如何，重新运行都不安全。"最多运行一次"语义需要幂等机制——而那个机制就是断点。内容哈希 ID 把这扩展到"每个独特内容在所有时间内最多处理一次"。

**步骤很多的长流水线。** 一个有 24 个步骤、每步崩溃概率 1% 的流水线，至少一步崩溃的概率是 21%。零重启策略下，每次崩溃平均浪费 12 步工作。有了断点，每次崩溃最多浪费 1 步。随着流水线变长，无状态方法的预期浪费线性增长；断点方法保持恒定。

建议：**当任何单步具有你不想不必要重复的成本（时间、金钱或副作用）时，添加断点**。发送一行问候语的 cron 任务不需要断点——它很快，重试也安全。发起 LLM API 调用、处理大文件或触发外部操作的 cron 任务需要断点。

用数字来说：如果你的流水线有 N 步，每步有独立的崩溃概率 p（例如每步 0.1% 的 OOM kill 概率，p = 0.001），一个 24 步流水线至少一步崩溃的概率是 `1 - (1-p)^24 ≈ 2.4%`。零重启策略下，每次崩溃的预期浪费工作是 N/2 步。有了断点，是 0 步（续传运行从断点处精确恢复）。随着 N 增大，断点变得越来越有价值。N=100 时，没有断点的预期浪费工作是 50 步——流水线的一半。

如果任务图复杂到需要分支逻辑、并行扇出或人在环路中的暂停，考虑用 [LangGraph 的断点/续传](https://langchain-ai.github.io/langgraph/concepts/persistence/) 代替本章的手写方案。LangGraph 实现相同原则——每个节点后写状态，从最后成功的节点续传——支持 SQLite、Redis 和 PostgreSQL 断点后端，以及可以在任意图节点检查完整状态的可视化调试界面。权衡：LangGraph 增加约 30MB 依赖和学习曲线；本章的 SQLite 方案增加 50 行代码。

---

## 生产版本：为什么复杂性是必要的

生产实现的核心入口函数 `runCronIsolatedAgentTurn` 在执行调度逻辑的第一行之前就导入了 30+ 个模块。这不是过度工程——每一个导入都是因为真实部署中遇到了生产边界情况：

- **模型降级（model-fallback）** 存在是因为凌晨 3 点的 Opus 配额错误曾经让整个夜间摘要静默失败。修法：先尝试 Opus，降级到 Sonnet，再降级到 Haiku。降级链现在可以按 agent 配置。
- **会话键（session-key）+ 会话（session）** 存在是因为 cron 任务在共享与交互式 agent 循环相同的会话上下文，导致上下文污染：一次漫长的午夜汇总运行会填满上下文窗口，破坏用户第二天早上的对话。
- **认证配置（auth-profiles/session-override）** 存在是因为多租户部署中有过一个 bug：为 Agent A 配置的任务在 Agent B 的 API key 下运行。修法是带显式验证的每会话认证配置隔离。
- **交付分发（delivery-dispatch）** 存在是因为早期实现把摘要作为原始日志消息发布。用户想要 Slack 格式、Telegram markdown 和飞书富文本——根据输出去向有三条不同的格式化管道。
- **技能快照（skills-snapshot）** 存在是因为 cron 任务需要确定性的技能集。交互式会话可以动态加载新技能；计划任务应该以任务定义时配置的技能集运行，而不是触发时恰好加载了哪些技能。

设计原则的核心——持久化每个步骤，重启时检查——在两个版本中是相同的。生产版本是叠加在 3 个不变式上的 30+ 个模块的运维经验。

如果你在为一个用户用一个模型构建个人 agent，lena-v0.18 已经完整。当你需要多用户、多模型、多频道的 cron 以及每任务隔离时，每个模块对应的生产失败都值得深入研究。

---

## Lena v0.18 完整模块地图

完整的 `lena-v0.18/` 目录：

```
lena-v0.18/
├── main.py            # 入口：初始化数据库，注册 2 个 cron 任务，run_forever()
├── scheduler.py       # croniter 封装——40 行，除 croniter 外零依赖
├── core/
│   └── checkpoint.py  # SQLite 引擎——init_db / save_step / completed_steps / all_steps
├── tasks/
│   ├── fetch_news.py  # 带断点续传的每小时抓取——替换 _fetch() 使用真实数据
│   └── summarize.py   # 午夜 LLM 汇总——读取 all_steps，写一行 "summary" 记录
├── quick_test.py      # 不用等一小时验证崩溃恢复
├── requirements.txt   # croniter>=3.0.0, anthropic>=0.25.0
└── data/              # 运行时创建——lena.db 在这里
```

模块边界是刻意设计的。`core/checkpoint.py` 对新闻或调度一无所知——它是通用的持久化步骤引擎。`tasks/fetch_news.py` 对调度一无所知——它只知道如何运行一次抓取并为每个数据源做断点。`scheduler.py` 对新闻或断点一无所知——它只知道如何在 croniter 定义的时间触发函数。`main.py` 是唯一知道三个组件的文件；它把它们拼接在一起。

这种分离意味着你可以完全隔离地测试 `checkpoint.py`（`quick_test.py` 就是这样做的），在不修改任务的情况下换掉调度器，以及在不修改断点引擎的情况下添加新任务类型。每个模块只有一个变更原因。

---

## 章末挑战

**挑战 1 — 错过触发补跑。** 当前调度器忽略进程宕机期间本应触发的任务。用 `croniter.get_prev()` 添加一个 `check_missed_run(expr: str, last_seen: datetime) -> bool` 函数，如果 `last_seen` 和 `now` 之间有任何触发发生则返回 True。把每个任务的 `last_seen` 存储在断点数据库中。

**挑战 2 — TTL 断点过期。** 给 `save_step` 添加一个 `valid_for_hours: int` 参数。修改 `completed_steps` 忽略超过 `valid_for_hours` 的行。这模拟了输入数据变化频繁、一天前的断点已经过期的情况。

**挑战 3 — 并行数据源抓取。** 当前的 `fetch_news.run()` 顺序抓取数据源。将其转换为使用 `asyncio.gather` 并发运行三个抓取协程。断点逻辑不变——幂等性仍然来自 `INSERT OR IGNORE`。但抓取步骤的墙钟时间从 3 倍单数据源延迟降到约 1 倍。

---

Lena 现在可以运行数天并在重启后恢复。她还不能做到的是*在运行时扩展自己的能力*——今天的工具集在启动时固定。下一章介绍 MCP，这是让 Lena 无需修改代码就能连接任何外部工具服务器的协议。

---

## 导航

➡️ **[Ch 19. MCP 协议](../ch19-mcp-protocol/README.md)** — 动态工具扩展

[← Ch 17. 心跳与常驻执行](../ch17-heartbeat/README.md) · [📘 回全书目录](../../README.md)
