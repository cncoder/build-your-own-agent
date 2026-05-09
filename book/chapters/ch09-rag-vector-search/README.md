# 第 9 章：RAG 与向量检索——教 Lena 读懂你的文档

```
Ch1 → Ch2 → Ch3 → Ch4 → Ch5 → Ch6 → Ch7 → Ch8 → [Ch9 ← 你在这里] → Ch10 → ...
Lena v0.1   v0.3   v0.6   ──   ──   v0.6   v0.7   v0.8                    v0.9
```

**本章把 Lena 从 v0.8（具备上下文管理和规划能力）升级到 v0.9（能回答关于 200 页 PDF 的问题）。**

本章 arc：从"把 200 页技术文档全塞进 prompt"这一具体失败出发 → 发现解法是五个独立的工程决策叠加在一起 → 以 pgvector 为后端逐层搭建 → 最终以 `search_knowledge_base` 作为 Lena 的第五个工具，执行 `docker compose up` 即可运行。

途中会遇到一个大多数 RAG 教程都忽略的洞见：Anthropic 的情境检索（Contextual Retrieval）技术——在嵌入前为每个文本块附加一段简短的定位上下文，通过 prompt 缓存以极低成本将检索失败率降低约 35%。

> 这不是一个非常健壮的实现——改进空间很大。但它能运行，端到端跑通，并且能给你足够的直觉，在出问题时调试失败。
> （仿 Simon Willison，*Python ReAct Pattern*）

---

## Beat 1 — 路线图

```
Beat 1  路线图                （本节）
Beat 2  动机                  原始方案在 3 秒内崩溃
Beat 3  理论                  RAG 的真正含义（5 个决策，不是 1 件事）
Beat 4  脚手架                pgvector 表结构 + 最小摄入骨架
Beat 5  渐进组装              分块 → 嵌入 → 存储 → 检索 → 重排
Beat 6  运行验证              docker-compose up，摄入 PDF，提问
Beat 7  Design Note ×2        为什么不直接塞满上下文窗口 / 为什么 agent+RAG 是默认形态
```

本章结束时，Lena 能回答"API 规范第 4.3 节关于速率限制说了什么？"并引用精确的文本块。工具定义只有 12 行 Python，整个后端只需一个 Docker 服务。

**Lena v0.9 新增能力：** `search_knowledge_base(query, top_k=5)` — 从 pgvector 检索相关文本块，可选地用 BGE-Reranker 重排，返回格式化的上下文。

> **🧠 聪明度增量（v0.8 → v0.9）**：Lena 第一次能读取外部知识——pgvector 向量检索让她不必把 200 页 PDF 全塞进 context，而是按需召回相关段落，回答"文档第 4.3 节说了什么"时引用精确文本块。这一章教读者把 RAG 检索能力长在自己 agent 上的方法。

---

## Beat 2 — 动机

"RAG is not dead" —— Simon Willison 在 2025 PyCon 演讲中明确回应了"context window 够大就不需要 RAG"的论调：

> "无论 context 多长，你的数据总比它多。"（No matter how big the context window gets, your data is always bigger.）

200K tokens 的 context window ≈ 一本书。但一个企业知识库可能有几万本书。所以 RAG 不是"旧方案"——它是**结构化地选出该喂给 LLM 的那一小段**的唯一方案。

最直觉的做法是：读取 PDF，把所有内容塞进 system prompt。

让我们验证这会多快崩溃：

```python
# BAD — 不要这样做
import anthropic, pathlib

pdf_text = pathlib.Path("api_spec.txt").read_text()  # 200 页 ~ 150,000 tokens

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system=f"这是完整的 API 规范：\n\n{pdf_text}",
    messages=[{"role": "user", "content": "/v2/completions 的速率限制是多少？"}]
)
```

这会同时撞上三堵墙：

| 问题 | 发生原因 | 代价 |
|------|---------|------|
| **上下文溢出（Context overflow）** | 150K tokens 超过很多模型的 200K 限制；即使到 1M tokens，每次调用都要为**所有** token 付费 | 每次提问 $0.15–$3.00 |
| **上下文腐烂（Context Rot）** | Anthropic 研究显示随着上下文增长召回率下降：一个事实藏在 10 万 token prompt 的第 8 万 token 处，召回准确率仅为该事实在第 5000 token 处的约 60% | 无声的质量损失 |
| **延迟** | 15 万 token 的 prompt 需要 3–8 秒才能出首字 | 用户流失 |

最后一个问题——上下文腐烂——是在生产环境中不知不觉咬你一口的那种。你上线了，用户问的问题答案在长文档的中间位置，模型自信地给出错误答案。你看不到崩溃，只有质量悄悄下滑。

Convention：**上下文腐烂（Context Rot）** = Transformer 模型对信息的召回能力随着该信息在上下文窗口中的位置远离开头和结尾而下降的现象。来源：Anthropic Engineering Blog，*Effective Context Engineering for AI Agents*（2026）。

RAG 存在的意义就是对抗上下文腐烂。与其喂入整篇文档，不如每次提问只检索 3–5 个最相关的文本块，让活跃上下文窗口保持小且信号密集。

---

## Beat 3 — 理论铺垫

*本节无代码。*

### 3.1 RAG 是五个决策，不是一件事

Lena 即将获得一项描述起来出奇简单——"搜索文档"——而实现好出奇复杂的新能力。在写代码之前，先明确 RAG 究竟是什么。

"直接加个 RAG"是无意义的建议。RAG 是一条流水线，包含五个独立阶段，每个阶段都有自己的设计选择：

```
文档 → [1. 分块（Chunk）] → [2. 嵌入（Embed）] → [3. 存储/索引（Store/Index）] → [4. 检索（Retrieve）] → [5. 重排？（Rerank?）] → LLM
```

每个阶段可以独立地做对或做错。优秀的嵌入模型放在糟糕的分块上结果照样糟糕。完美的分块配上弱检索策略照样失败。你需要对每个阶段单独推理。

Convention：**分块（chunking）** = 将文档切割成可检索的单元；**嵌入（embedding）** = 将文本转换为稠密浮点向量；**检索（retrieval）** = 找到与查询向量最相近的向量；**重排（reranking）** = 用更昂贵的交叉编码器模型对已检索候选项重新打分。

朴素的心智模型认为 RAG 就是"语义搜索"。那只是检索阶段。其余四个阶段决定了你的系统在生产中是否真的能工作。

### 3.2 分块：影响所有下游的决策

分块做差了，没有哪个嵌入模型能救你。三种策略覆盖了 95% 的使用场景：

| 策略 | 机制 | 何时使用 | 何时失效 |
|------|------|---------|---------|
| **固定大小（Fixed-size）** | 每 N tokens 切一刀，重叠 M tokens | 首个原型；同质文本（日志、转写稿） | 在句子中间切断；破坏段落结构 |
| **语义分块（Semantic）** | 在句子边界切割，合并直到达到 token 上限 | 大多数结构化文档；保留意义单元 | 摄入时略贵；需要好的分句器 |
| **延迟分块（Late Chunking）** | 嵌入完整文档上下文后再切割所得嵌入 | 有大量交叉引用和指代的长技术文档 | 需要支持该特性的模型（jina-embeddings-v3）；流水线更复杂 |

**if/then 决策表——选择你的策略：**

```
IF 文档有结构（有清晰的标题、章节、编号条款）
    → 先按标题切，再在每节内做语义分块
    → 最适合 API 文档、法律合同、技术规范

IF 文档是纯散文（文章、书籍、报告）
    → 语义分块，256–512 tokens，约 20% 重叠
    → 重叠很重要：检索在文本块级别发生，但答案往往跨越文本块边界

IF 需要逐字引用或页码标注
    → 固定大小，在元数据中记录（页码, char_offset）
    → 文本块边界对检索无关紧要，只要你引用了来源

IF 文档是代码
    → 按函数/类/模块边界切割，而非 token 数量
    → 一个 200 行的函数是一个语义单元；从中间切开会破坏检索

IF 每篇文档有 100万+ tokens（书级长度）
    → 研究延迟分块（jina-embeddings-v3）或层级分块
    → 对本章的使用场景，语义分块已足够
```

本章后续使用**语义分块**，目标 400 tokens、80 token 重叠。这能处理你会遇到的绝大多数 PDF 和文本文档。

一个值得记住的数字：超过约 512 tokens 的文本块会被大多数嵌入模型静默截断。BGE-M3 用正确的设置支持最多 8,192 tokens，但更小的文本块能给出更好的检索精度——关键句子周围的无关文本更少。

### 3.3 嵌入模型：选择合适的向量空间

嵌入模型将一段文本转换为稠密向量——一列浮点数。含义相似的文本块最终得到相似的向量（在余弦空间中距离相近）。这种映射的质量决定了你检索质量的上限。

三个模型覆盖了大多数团队的现实决策空间：

| 模型 | 维度 | 成本 | 多语言 | 最大 tokens | 何时使用 |
|------|------|------|--------|------------|---------|
| **OpenAI `text-embedding-3-large`** | 3072 | $0.13/M tokens（API） | 是 | 8,191 | 已在使用 OpenAI 且想要托管 API 时 |
| **BAAI/bge-m3** | 768 | 免费（本地） | 是（100+ 语言） | 8,192 | 默认选择：性能强、免费、能跑在 CPU 上 |
| **Voyage AI `voyage-3`** | 1024 | $0.06/M tokens（API） | 部分 | 32,000 | 需要长文档支持或 RAG 优化检索时 |

**if/then 决策表——选择你的嵌入模型：**

```
IF 文档全是英文且有预算
    → Voyage AI voyage-3 或 OpenAI text-embedding-3-large
    → Anthropic 自己的 RAG cookbook 使用 Voyage AI（他们为 Claude 推荐它）

IF 需要零成本或本地部署
    → BAAI/bge-m3（本章的选择）
    → 768 维比 3072 维小，但质量有竞争力

IF 文档是多语言（中文、日文、欧洲语言）
    → bge-m3 是免费档中最强的多语言选项
    → Voyage AI voyage-multilingual-2 用于托管多语言 API

IF 嵌入模型的 max_tokens < 典型文本块大小
    → 问题：超出的 tokens 被静默截断，破坏文本块质量
    → 解法：用更小的文本块，或切换到支持更长上下文的模型
```

Convention：**余弦相似度（cosine similarity）** = 两个归一化向量的点积；取值范围 -1（含义相反）到 1（含义相同）。pgvector 的 `<=>` 运算符计算余弦**距离**（1 - 相似度）；结果 0.15 意味着相似度 = 0.85。

一个容易被低估的属性：相似度分数在不同模型间没有校准。OpenAI 嵌入下的 0.80 分和 BGE-M3 下的 0.80 分质量不同。你的"低置信度"阈值必须针对每个模型通过实验确定，不能套用你在网上看到的数字。

### 3.4 向量数据库：三路决策树

你需要一个地方存储向量并高效查询。对于 Lena 目前开发阶段的团队，现实的选择如下：

| 选项 | 基础设施 | 延迟 | 规模 | 何时选择 |
|------|---------|------|------|---------|
| **pgvector**（我们的选择） | Docker，或已有 PostgreSQL | 5–50ms | 不调优可到约 100 万行 | 已在用 Postgres；想要简单运维 |
| **Chroma** | 进程内或 Docker 服务 | 2–20ms | 10 万行内表现好，50 万+ 开始变慢 | 原型阶段；想要零配置 |
| **Qdrant** | Docker 或托管云 | 1–10ms | 专为 1000 万+ 向量设计 | 规模化生产；需要过滤 + 量化 |

**决策树：**

```
你已经有 PostgreSQL 数据库吗？
  有  → 用 pgvector。无新基础设施，ACID 事务，熟悉的 SQL。
  没有 → 这是原型还是长期系统？
          原型  → Chroma（pip install chromadb，零配置，内存模式）
          长期  → 向量数量可能超过 50 万吗？
                   会超过 → Qdrant（托管云或自部署）
                   不会   → pgvector（从简单开始，必要时迁移）
```

本章使用 **pgvector**——一个 Docker 容器，标准 SQL，无新服务。`pgvector/pgvector:pg16` 镜像已预装该扩展。

我们在 schema.sql 中创建的 IVFFlat 索引通过将向量划分为 `lists` 个分区（质心）来加速搜索。对于小数据集（1000 行以下），pgvector 自动回退到精确搜索——索引不会有害。对于超过 10 万行的数据集，将 `lists` 设置为 `sqrt(行数)` 并在批量插入后运行 `VACUUM ANALYZE chunks;`。

### 3.5 Anthropic 的情境检索：35% 的提升

在嵌入之前，有一个大多数 RAG 教程都会错过的技术。它来自 Anthropic 的 *Contextual Retrieval*（情境检索）博客文章（2024 年 9 月）。

核心洞见：当你孤立地嵌入一个文本块时，向量只捕获文本块**内部**的内容，而不是该文本块在**上下文中的含义**。一个写着"参数设置为 `max_retries=3`"的文本块在语义上是模糊的——它可能来自任何文档的任何章节。当你查询"针对 /v2/completions 的重试配置"时，查询向量和该文本块向量之间的余弦相似度低于应有水平，因为两个向量都缺少上下文信息"这是关于 /v2/completions 端点的"。

解法是让 Claude 在嵌入前为每个文本块附加一段简短的定位句：

```
嵌入前：
  "参数设置为 max_retries=3。"

嵌入后（加入情境检索）：
  "[来自 API 规范的 /v2/completions 端点配置章节]
   参数设置为 max_retries=3。"
```

Anthropic 在九个代码库上的评估量化结果：**top-20 文本块检索失败率降低 35%**（Pass@20 从约 87% 提升到约 95%，基于 Anthropic 自己的 cookbook 数据集）。

成本问题是真实存在的，但 prompt 缓存解决了它：你将完整文档发送给 Claude 并标记为 `cache_control: ephemeral`。第一个文本块时，Anthropic 将文档写入 KV 缓存（小额溢价）。同一文档的每个后续文本块从缓存读取，享受 90% 折扣。对于一个 10,000 token 的文档，包含 25 个文本块：

```
不使用缓存：
  25 次调用 × 10,100 tokens = 252,500 tokens @ $0.25/MTok = $0.063

使用 prompt 缓存（Haiku 定价）：
  1 次缓存写入：10,000 × $0.30/MTok = $0.003
  24 次缓存读取：24 × 10,000 × $0.03/MTok = $0.0072
  25 次生成输出：约 125 tokens × 25 × $1.25/MTok = $0.004
  合计：约 $0.014（便宜 78%）
```

这项技术不是 LangChain 抽象——它是一个 prompt 模式。我们在 Beat 5 中用 20 行代码实现它。

---

## Beat 4 — 脚手架

先搭建能运行的最小骨架。后端是 Docker 里的 pgvector；Python 代码使用 `psycopg`（官方 PostgreSQL 驱动，psycopg3 API）和 `sentence-transformers` 做嵌入。

首先是数据库表结构：

```sql
-- schema.sql（通过 docker compose 运行一次）
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    doc_id      TEXT NOT NULL,           -- 例如 "api-spec-v2.pdf"
    chunk_index INTEGER NOT NULL,        -- 在文档中的位置
    content     TEXT NOT NULL,           -- 原始文本块内容
    context     TEXT,                    -- Anthropic 情境前缀（可为空）
    embedding   VECTOR(768),             -- BGE-M3 输出 768 维向量
    metadata    JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);                  -- 调参：lists ≈ sqrt(num_rows)
```

现在是最小 Python 摄入骨架：

```python
# ingest.py — 骨架（Beat 4：能运行但还没有实际功能）
import psycopg
import os

DB_URL = os.getenv("DATABASE_URL", "postgresql://lena:lena@localhost:5432/lena_rag")

def get_conn():
    return psycopg.connect(DB_URL)

def ingest_document(doc_id: str, text: str) -> None:
    """摄入文档。Beat 4：仅骨架——还没有分块和嵌入。"""
    with get_conn() as conn:
        # 占位符：将在 Beat 5 填充
        print(f"[scaffold] would ingest {len(text)} chars as doc_id={doc_id!r}")

if __name__ == "__main__":
    ingest_document("test.txt", "Hello, this is a test document.")
    print("Scaffold OK — no DB writes yet, just verifying structure.")
```

增加复杂性之前先验证骨架能运行：

```bash
python ingest.py
# 预期输出：[scaffold] would ingest 31 chars as doc_id='test.txt'
#           Scaffold OK — no DB writes yet, just verifying structure.
```

好。骨架确认了导入链是干净的。现在来逐步扩展它。

---

## Beat 5 — 渐进组装

每次只添加一个能力。每一步之后，代码都能运行并打印有意义的内容。

### 扩展 1 — 分块

| 扩展点 | 为何需要 | 如何添加 |
|--------|---------|---------|
| 语义分块 | 固定大小切割会破坏句子边界；模型嵌入碎片效果差 | `nltk.tokenize.sent_tokenize` + 贪心合并 |
| 400 token 目标，80 token 重叠 | 在上下文丰富度和检索精度间取得平衡 | 对句子列表做简单滑动窗口 |

```python
# 分块逻辑（添加到 ingest.py）
import nltk
nltk.download("punkt", quiet=True)

def chunk_text(text: str, target_tokens: int = 400, overlap_tokens: int = 80) -> list[str]:
    """语义分块：按句子切割，合并到约 target_tokens，带重叠。"""
    sentences = nltk.tokenize.sent_tokenize(text)

    # 粗略 token 估算：1 token ≈ 4 字符
    def tok_count(s: str) -> int:
        return len(s) // 4

    chunks, current, current_len = [], [], 0
    for sent in sentences:
        sent_len = tok_count(sent)
        if current_len + sent_len > target_tokens and current:
            chunks.append(" ".join(current))
            # 保留重叠：回退直到移除 (target - overlap) 个 token
            overlap_budget = overlap_tokens
            tail = []
            for s in reversed(current):
                if overlap_budget <= 0:
                    break
                tail.insert(0, s)
                overlap_budget -= tok_count(s)
            current, current_len = tail, sum(tok_count(s) for s in tail)
        current.append(sent)
        current_len += sent_len
    if current:
        chunks.append(" ".join(current))
    return chunks
```

中间验证——添加此函数后运行：

```python
# 快速冒烟测试
sample = "Sentence one. Sentence two. Sentence three. " * 50  # 约 150 句
chunks = chunk_text(sample)
print(f"Chunked into {len(chunks)} chunks, first chunk length: {len(chunks[0])} chars")
# 预期：Chunked into 5-8 chunks, first chunk length: ~1600-1800 chars
```

### 扩展 2 — 情境嵌入（Anthropic 技术）

| 扩展点 | 为何需要 | 如何添加 |
|--------|---------|---------|
| 情境前缀 | 孤立文本块丢失交叉引用；加入情境后检索失败率降低 35% | `anthropic.messages.create` 在完整文档上使用 `cache_control` |
| Prompt 缓存 | 为 500 个文本块生成情境如果不缓存要花 $5–15 | 在文档内容块上设置 `{"type": "ephemeral"}` |

```python
# 情境生成（添加到 ingest.py）
import anthropic

_anthropic = anthropic.Anthropic()

DOCUMENT_PROMPT = """<document>
{doc_content}
</document>"""

CHUNK_PROMPT = """以下是我们想在整篇文档中定位的文本块：
<chunk>
{chunk_content}
</chunk>

为该文本块提供简短精炼的上下文（1-2 句话），以便在整篇文档中定位该文本块，
从而改善搜索检索效果。只回答上下文内容，不需要前言。"""

def generate_context(doc_content: str, chunk_content: str) -> str:
    """使用 Anthropic 情境检索为文本块附加定位上下文。

    使用 prompt 缓存：文档在每批次写入缓存一次，
    然后每个文本块调用以 90% 折扣从缓存读取。
    """
    response = _anthropic.messages.create(
        model="claude-haiku-4-5",  # Haiku：生成情境快且便宜
        max_tokens=200,
        temperature=0.0,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": DOCUMENT_PROMPT.format(doc_content=doc_content),
                    "cache_control": {"type": "ephemeral"},  # 将完整文档写入缓存
                },
                {
                    "type": "text",
                    "text": CHUNK_PROMPT.format(chunk_content=chunk_content),
                },
            ],
        }],
    )
    context = response.content[0].text.strip()
    cache_hits = response.usage.cache_read_input_tokens
    return context, cache_hits
```

一个文档的第一个文本块之后，`cache_read_input_tokens` 会跳升到文档长度——确认缓存生效。对于一个 10,000 token 的文档包含 25 个文本块，你只需支付一次完整文档价格，其余 24 次调用只付 10%。

### 扩展 3 — 嵌入 + pgvector 插入

| 扩展点 | 为何需要 | 如何添加 |
|--------|---------|---------|
| BGE-M3 嵌入 | 免费、本地运行、768 维、强多语言性能 | `sentence_transformers.SentenceTransformer("BAAI/bge-m3")` |
| 批量插入 | 逐条 INSERT 比批量 `executemany` 慢 10 倍 | `psycopg.copy()` 或 `executemany` |

```python
# 嵌入 + 插入（添加到 ingest.py）
from sentence_transformers import SentenceTransformer
import numpy as np

_model = SentenceTransformer("BAAI/bge-m3")

def embed(texts: list[str]) -> list[list[float]]:
    """嵌入一组文本。返回 768 维向量列表。"""
    vectors = _model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()

def insert_chunks(doc_id: str, chunks: list[dict]) -> int:
    """将一批文本块插入 pgvector。

    每个 chunk dict：{"content": str, "context": str, "index": int}
    返回插入的行数。
    """
    texts_to_embed = [
        f"{c['context']}\n\n{c['content']}" if c.get("context") else c["content"]
        for c in chunks
    ]
    vectors = embed(texts_to_embed)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO chunks (doc_id, chunk_index, content, context, embedding)
                   VALUES (%s, %s, %s, %s, %s::vector)""",
                [
                    (doc_id, c["index"], c["content"], c.get("context"), str(v))
                    for c, v in zip(chunks, vectors)
                ]
            )
        conn.commit()
    return len(chunks)
```

添加后的中间验证——插入一个测试文本块并确认：

```python
# 快速 DB 冒烟测试（先运行 docker compose up）
result = insert_chunks("smoke-test", [{"content": "test chunk", "context": None, "index": 0}])
print(f"Inserted {result} chunks")  # 预期：Inserted 1 chunks
```

### 扩展 4 — 检索策略：Top-K、MMR 以及何时使用混合检索

写检索代码之前，我们需要选择检索策略。三种主导策略：

| 策略 | 机制 | 优势 | 弱点 |
|------|------|------|------|
| **Top-K 余弦** | 返回 K 个最近向量 | 快速、简单、易理解 | 即使结果冗余也会返回相似文本块 |
| **MMR（最大边际相关度）** | 平衡相关性与多样性：惩罚与已选文本块相似的候选项 | 减少结果冗余 | 约 2 倍复杂度；轻微召回损失 |
| **混合检索：BM25 + 向量** | 通过 RRF（倒数排名融合）组合关键词匹配分和余弦分 | 捕获纯语义搜索遗漏的精确关键词匹配 | 需要 BM25 基础设施（Elasticsearch 或 pg_bm25） |

**if/then 决策表——选择你的检索策略：**

```
IF 文档是密集散文（报告、规范、文档）
    → Top-K 足够；语义相似度能很好地捕获含义

IF 文档包含精确技术术语、模型名称、错误码
    → 添加混合检索（BM25 + 向量）
    → 示例："GPT-4o-2024-05-13 速率限制"——查询精确模型版本字符串的用户
      需要关键词匹配，而不仅仅是语义相似度

IF Top-K 结果高度冗余（多个文本块说同样的话）
    → 考虑 MMR 增加多样性
    → 对宽泛探索性查询（"给我概述一下 X"）比精确事实性问题
      （"/v2/completions 的速率限制是多少"）更有用
```

本章主流水线实现 **Top-K 余弦相似度**——对结构化文档已足够，且不需要额外基础设施。混合检索作为扩展展示。

**混合检索：BM25 重要的时候**

Anthropic 的*情境检索*评估显示，在情境嵌入上加入 BM25 将代码库查询的 Pass@20 从约 95% 提升到约 95.2%——提升有限。更明显的收益在于包含精确技术标识符的查询：

- 模型版本字符串：`claude-opus-4-7-20260101`
- 错误码：`RATE_LIMIT_EXCEEDED`
- 参数名：`max_retries`
- API 端点路径：`/v2/completions`

对于这类查询，BM25 关键词匹配能找到精确文本块，即使语义嵌入是模糊的。如果你的知识库包含这类内容，添加混合检索。否则，坚持用纯向量检索。

现在写检索代码：

```python
# search_knowledge_base.py — Lena 的工具
import psycopg, os
from sentence_transformers import SentenceTransformer

DB_URL = os.getenv("DATABASE_URL", "postgresql://lena:lena@localhost:5432/lena_rag")
_model = SentenceTransformer("BAAI/bge-m3")

def search_knowledge_base(query: str, top_k: int = 5, doc_id: str | None = None) -> str:
    """在知识库中搜索与查询相关的文本块。

    Args:
        query: 自然语言问题
        top_k: 返回的文本块数量（默认 5；超过 10 通常只添加噪音）
        doc_id: 可选，过滤到特定文档

    Returns:
        格式化的字符串，包含 top-k 文本块及其来源。
    """
    query_vec = _model.encode([query], normalize_embeddings=True)[0].tolist()
    vec_str = str(query_vec)

    sql = """
        SELECT doc_id, chunk_index, content, context,
               1 - (embedding <=> %s::vector) AS similarity
        FROM chunks
        WHERE (%s IS NULL OR doc_id = %s)
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (vec_str, doc_id, doc_id, vec_str, top_k))
            rows = cur.fetchall()

    if not rows:
        return "知识库中未找到相关文本块。"

    # 当所有相似度分数偏低时发出警告——检索可能失败了
    max_sim = max(row[4] for row in rows)
    warning = ""
    if max_sim < 0.50:
        warning = (
            f"[warn] 最高相似度分数为 {max_sim:.3f}。"
            "检索到的文本块可能不相关。请考虑换个方式提问，"
            "或验证是否摄入了正确的文档。\n\n"
        )

    parts = []
    for doc_id_row, chunk_idx, content, context, similarity in rows:
        header = f"[{doc_id_row} §{chunk_idx} | similarity={similarity:.3f}]"
        text = f"{context}\n\n{content}" if context else content
        parts.append(f"{header}\n{text}")

    return warning + "\n\n---\n\n".join(parts)
```

中间验证——摄入示例文档后查询数据库：

```bash
python search_knowledge_base.py "每分钟速率限制是多少？"
# 预期：[sample §3 | similarity=0.81]
#       [来自 Lena API 参考的速率限制章节]
#       该 API 每个 API key 每分钟最多允许 1,000 个请求...
```

如果相似度分数全在 0.50 以下，这不是代码 bug——意味着查询在语义上与你摄入的内容相距甚远，或者你忘记先摄入文档了。

---

### 扩展 5 — RAG 评测：怎么知道它有没有工作？

本节故意写得简短，因为第 21 章会覆盖完整的评估流水线。但我们现在需要建立最小可行信号：在把 RAG 交给用户之前，你应该知道它是否在工作。

Convention：**Recall@K** = 相关文本块出现在 top-K 检索结果中的比例；**Precision@K** = top-K 结果中相关的比例。好的检索系统优化 Recall@K（不遗漏相关文本块）而非 Precision@K（不浪费上下文在不相关内容上）——LLM 可以过滤噪音，但无法凭空创造你没有检索到的信息。

按重要程度排序的三个指标：

| 指标 | 它告诉你什么 | 如何计算 |
|------|------------|---------|
| **Recall@K** | "我们找到了正确的文本块吗？" | 对每道测试题，检查黄金文本块是否出现在 top-K 结果中 |
| **答案忠实度** | "LLM 的回答有没有扎根于检索到的文本块？" | LLM 作为裁判：评分答案是否可以从检索到的上下文推导出来 |
| **答案正确性** | "最终答案对不对？" | 与参考答案对比；需要黄金数据集 |

你的 RAG 系统最小可行评测是 20–50 道带有已知正确文本块的测试题。运行方式如下：

```python
# minimal_eval.py — 检索质量冒烟测试
from search_knowledge_base import _embed_query, _retrieve

# 黄金数据集：(问题, 预期 doc_id, 预期 chunk_index) 列表
# 通过摄入一篇文档，然后手工识别哪个文本块回答了每道测试题来构建。
GOLDEN = [
    ("每分钟速率限制是多少？", "sample", 3),
    ("如何认证 API 请求？", "sample", 1),
    ("错误响应的格式是什么？", "sample", 5),
]

hits_at_5 = 0
for question, expected_doc, expected_chunk_idx in GOLDEN:
    qvec = _embed_query(question)
    results = _retrieve(qvec, top_k=5, doc_id=None)
    retrieved_keys = [(r["doc_id"], r["chunk_index"]) for r in results]
    if (expected_doc, expected_chunk_idx) in retrieved_keys:
        hits_at_5 += 1
        print(f"  HIT  '{question[:50]}'")
    else:
        top = results[0] if results else None
        top_sim = f"{top['similarity']:.3f}" if top else "n/a"
        print(f"  MISS '{question[:50]}' (top similarity: {top_sim})")

recall_at_5 = hits_at_5 / len(GOLDEN)
print(f"\nRecall@5: {recall_at_5:.1%} ({hits_at_5}/{len(GOLDEN)} 道题)")
print("目标：上线前 ≥80%。使用情境检索时通常 ≥90%。")
```

摄入文档后运行此脚本。如果 Recall@5 低于 70%，问题几乎总是在分块上（文本块太大、语义边界被破坏）或文档质量上（扫描 PDF 有 OCR 错误、无法提取文本）。在这个规模下，嵌入模型和检索策略很少是瓶颈。

这是最小评测。第 21 章将展示如何构建带 CI 集成的完整回归测试套件。

---

## Beat 6 — 运行完整流水线

### docker-compose.yml

```yaml
# docker-compose.yml
version: "3.9"
services:
  pgvector:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: lena
      POSTGRES_PASSWORD: lena
      POSTGRES_DB: lena_rag
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./code/lena-v0.9-rag/schema.sql:/docker-entrypoint-initdb.d/schema.sql
volumes:
  pgdata:
```

### 运行示例

```bash
# 1. 启动 pgvector
docker compose up -d

# 2. 安装 Python 依赖
pip install psycopg[binary] sentence-transformers anthropic nltk pypdf

# 3. 摄入示例 PDF（包含在 code/lena-v0.9-rag/sample_data/ 中）
python code/lena-v0.9-rag/ingest.py --pdf sample_data/sample.pdf --doc-id sample

# 预期输出（耗时约为参考值）：
# [ingest] Loaded 12 pages, extracted 8,421 chars
# [chunk] Split into 22 chunks (avg 383 tokens)
# [context] Generating context for 22 chunks...
#   chunk 1/22: cache_creation=2847 tokens (第一个文本块，写入缓存)
#   chunk 2/22: cache_read=2847 tokens (90% 折扣生效)
#   ...
#   chunk 22/22: cache_read=2847 tokens
# [embed] Embedding 22 chunks with BAAI/bge-m3...
# [insert] Inserted 22 chunks into pgvector in 0.31s
# Done. Total time: 18.4s

# 4. 提一个问题
python code/lena-v0.9-rag/search_knowledge_base.py "每分钟最大请求速率是多少？"

# 预期输出：
# [sample §4 | similarity=0.847]
# [来自 API 参考的速率限制章节]
#
# 该 API 每个 API key 每分钟最多允许 1,000 个请求...
```

**常见失败模式：**

- `psycopg.OperationalError: connection refused` — docker compose 还没启动；`docker compose up -d` 后等 5 秒再运行摄入脚本。
- `ERROR: type "vector" does not exist` — schema.sql 没有执行；手动运行 `psql -U lena lena_rag < schema.sql`。
- `SentenceTransformer: model not found` — 第一次运行会下载 BGE-M3（约 560MB）；允许网络访问，等待 2–3 分钟。
- 相似度分数全在 0.5 以下 — 通常意味着文档没有相关内容，或文本块太大（文本被 BGE-M3 的 512 token 输入限制截断；用更小的文本块或带 `max_length=8192` 的 `BAAI/bge-m3`）。

### 集成进 Lena

`search_knowledge_base` 成为 Lena 的第五个工具。Anthropic 工具定义：

```python
SEARCH_KB_TOOL = {
    "name": "search_knowledge_base",
    "description": (
        "在向量知识库中搜索与查询相关的信息。"
        "当需要回答关于已摄入文档的问题时使用此工具。"
        "返回带有相似度分数的最匹配文本块。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "自然语言问题或搜索查询"
            },
            "top_k": {
                "type": "integer",
                "description": "检索的文本块数量（默认 5，最大 15）",
                "default": 5
            },
            "doc_id": {
                "type": "string",
                "description": "可选：将搜索限制在特定文档 ID"
            }
        },
        "required": ["query"]
    }
}
```

注册了这个工具后，Lena 能处理："根据我们摄入的 API 规范，`metadata` 字段的格式是什么？"——她会调用 `search_knowledge_base(query="metadata 字段格式 API 规范")`，拿回相关文本块，在不把任何文档放进 system prompt 的情况下综合出答案。

---

## Beat 7 — Design Note

### Design Note 1：为什么不直接塞满上下文窗口？

显然的替代方案：把整篇文档放进 Claude 的 200K 上下文窗口。有些场景（单篇短文档、一次性问答）实际上应该这样做——它更简单，避免了基础设施开销。

权衡：

- **成本**：150K tokens × $3/MTok（Sonnet）= 每次提问 $0.45。每天 1,000 次提问，每天 $450，而用 RAG 检索 5 个文本块是 $0.02/天。
- **上下文腐烂**：Anthropic 研究记录了随着上下文增长召回率下降的现象。10 万 token 上下文中位于第 8 万 token 处的事实，召回准确率比位于第 3,000 token 处低约 40%。这不是硬性限制——而是一条梯度曲线。你不会看到崩溃，只有质量慢慢下滑。
- **延迟**：15 万 token 的 prompt 首字延迟 3–8 秒，而 5 个文本块的 RAG prompt 约 0.3 秒。

**建议**：如果你的文档不超过 20 页，用户每天只问几个问题，就把文档塞进上下文窗口。对于更大规模或更高流量的场景，RAG 的成本和质量优势是明确的。

本章的设计选择——pgvector 加嵌入检索——是最小可行版本。在生产中你会加上监控（追踪相似度分数分布；分数低说明你的查询出了分布外）、缓存（对重复查询缓存嵌入向量）以及降级方案（当检索置信度低时回退到全文档填充）。

---

### Design Note 2：为什么 Agent + RAG 是 LLM 应用的默认形态

RAG 单独不够用。RAG 单独只能回答"文档说了什么"——它无法决定*要搜索哪个*文档、*何时*搜索 vs 使用自身知识，或*检索到的答案是否可信到足以采取行动*。

Agent 外壳补上了缺失的一层：

```
用户问题
    → Agent 决定：这是知识库里的，还是常识性知识？
    → 如果是 KB：用正确的查询词调用 search_knowledge_base
    → 评估检索到的文本块：相关吗？相似度足够高吗？
    → 如果置信度低：要么要求澄清，要么回退到训练知识
    → 综合最终答案并引用来源
```

这就是为什么 75% 的 AI agent 职位（据对 15 家公司 32 份 JD 的分析）把 RAG 列为必备技能而非加分项。实践中，"构建 AI agent"几乎总是意味着"构建一个能对你的私有数据推理的 agent"。RAG 流水线是实现这一点的管道。

一句来自 Anthropic *Building Effective Agents*（2024-12-19）的忠告："从最简单的解决方案开始，只在必要时才增加复杂性。"本章的 pgvector + 单模型方案无需修改可处理最多约 10,000 页的文档。在你有证据证明简单版本不够用之前，不要添加专用重排器、向量数据库集群或 BM25 混合层。

---

## 附录：第 9 章——重排器

`rerank.py` 中的代码展示了如何添加第二阶段重排器。它不在主流水线里，因为对大多数文档来说它会增加 100–200ms 的延迟，只带来 2–5% 的精度提升。当你有证据表明需要它时再加。

决策规则很简单：

```
IF top-5 文本块的相似度分数全在 0.75 以上：
    → 跳过重排器（检索已经是高置信度）

IF top 文本块聚集在 0.55 到 0.70 之间（检索不确定）：
    → 添加重排器：它会把真正相关的文本块提升上来

IF top 文本块相似度 < 0.50：
    → 检索可能已完全失败；重排器救不了你
    → 考虑：你摄入的是正确文档吗？查询在分布内吗？
```

**何时用 Cohere vs BGE-Reranker：**

| 模型 | 成本 | 延迟 | 何时使用 |
|------|------|------|---------|
| Cohere `rerank-english-v3.0` | $2/1K 次查询 | 约 100ms | 纯英文文档；想要托管 API |
| `BAAI/bge-reranker-v2-m3` | 免费，本地运行 | CPU 上约 200ms | 多语言；成本敏感；本地部署需求 |

---

## 本章小结

Lena v0.9 现在能读一本 200 页的 PDF 并回答关于它的问题了。流水线：

1. **分块（Chunk）**：语义分块文档（400 tokens，80 token 重叠）
2. **生成情境（Generate context）**：使用 Anthropic 的情境检索技术为每个文本块生成上下文（检索失败率降低 35%，通过 prompt 缓存近乎免费）
3. **嵌入（Embed）**：用 BGE-M3 嵌入文本块 + 情境（免费，768 维）
4. **存储（Store）**：存入 pgvector（一个 Docker 服务，标准 PostgreSQL）
5. **检索（Retrieve）**：用余弦相似度检索，返回 top-K
6. **可选重排（Rerank）**：对不确定查询用 BGE-Reranker 重排

`search_knowledge_base` 工具 40 行代码。基础设施是一个如果你在跑 PostgreSQL 就已经有了的 Docker 服务。这不是框架——是三条 SQL 查询加一次嵌入调用。

下一章——上下文工程——将教你如何确保 Lena 检索到的文本块落在她上下文窗口的正确位置，以及当她检索的内容超出容量时如何压缩。

---

## 导航

➡️ **[Ch 10. 上下文工程：Token 经济学](../ch10-context-engineering/README.md)** — 三层压缩、prompt 缓存、TokenMonitor

[← Ch 8. 记忆与上下文](../ch08-memory/README.md) · [📘 回全书目录](../../README.md)
