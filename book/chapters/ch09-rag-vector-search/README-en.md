# Chapter 9: RAG and Vector Search — Teaching Lena to Read Your Documents

```
Ch1 → Ch2 → Ch3 → Ch4 → Ch5 → Ch6 → Ch7 → Ch8 → [Ch9 ← you are here] → Ch10 → ...
Lena v0.1   v0.3   v0.6   ──   ──   v0.6   v0.7   v0.8                    v0.9
```

**This chapter upgrades Lena from v0.8 (with context management and planning capabilities) to v0.9 (able to answer questions about a 200-page PDF).**

This chapter's arc: starting from the concrete failure of "stuff a 200-page technical document entirely into the prompt" → discovering the solution is five independent engineering decisions stacked together → building layer by layer with pgvector as the backend → arriving at `search_knowledge_base` as Lena's fifth tool, runnable with a single `docker compose up`.

Along the way we'll encounter an insight most RAG tutorials miss: Anthropic's Contextual Retrieval technique — prepending a short positioning context to each text chunk before embedding, using prompt caching to reduce retrieval failure rate by about 35% at near-zero cost.

> This is not a particularly robust implementation — there's plenty of room for improvement. But it runs, it works end-to-end, and it gives you enough intuition to debug failures when they happen.
> (After Simon Willison, *Python ReAct Pattern*)

---

## Beat 1 — Roadmap

```
Beat 1  Roadmap              (this section)
Beat 2  Motivation           the naive approach collapses in 3 seconds
Beat 3  Theory               what RAG really means (5 decisions, not 1 thing)
Beat 4  Scaffold             pgvector table structure + minimal ingestion skeleton
Beat 5  Incremental assembly chunk → embed → store → retrieve → rerank
Beat 6  Run verification     docker-compose up, ingest PDF, ask a question
Beat 7  Design Note ×2       why not just fill the context window / why agent+RAG is the default pattern
```

By the end of this chapter, Lena can answer "What does section 4.3 of the API spec say about rate limits?" and cite precise text chunks. The tool definition is 12 lines of Python; the entire backend is one Docker service.

**Lena v0.9 new capability:** `search_knowledge_base(query, top_k=5)` — retrieves relevant text chunks from pgvector, optionally reranks with BGE-Reranker, returns formatted context.

> **Intelligence increment (v0.8 → v0.9)**: Lena can read external knowledge for the first time — pgvector vector retrieval means she doesn't have to stuff a 200-page PDF into the context; she recalls relevant passages on demand, citing exact text blocks when answering "what does section 4.3 say." This chapter teaches you how to build RAG retrieval capability directly into your own agent.

---

## Beat 2 — Motivation

"RAG is not dead" — Simon Willison said this explicitly at PyCon 2025, pushing back on the argument that "a big enough context window makes RAG unnecessary":

> "No matter how big the context window gets, your data is always bigger."

A 200K-token context window ≈ one book. But an enterprise knowledge base might have tens of thousands of books. So RAG isn't an "old approach" — it's the only approach for **structurally selecting the right passage to feed the LLM**.

The most intuitive approach is: read the PDF, stuff everything into the system prompt.

Let's verify how quickly that breaks:

```python
# BAD — don't do this
import anthropic, pathlib

pdf_text = pathlib.Path("api_spec.txt").read_text()  # 200 pages ~ 150,000 tokens

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system=f"Here is the complete API specification:\n\n{pdf_text}",
    messages=[{"role": "user", "content": "What is the rate limit for /v2/completions?"}]
)
```

This hits three walls simultaneously:

| Problem | Why it happens | Cost |
|---------|---------------|------|
| **Context overflow** | 150K tokens exceeds the 200K limit on many models; even at 1M tokens, you pay for **all** tokens on every call | $0.15–$3.00 per question |
| **Context rot** | Anthropic research shows recall degrades as context grows: a fact buried at token 80,000 in a 100K-token prompt is retrieved with only about 60% the accuracy of the same fact at token 5,000 | Silent quality loss |
| **Latency** | A 150K-token prompt takes 3–8 seconds to first token | User churn |

The last problem — context rot — is the kind that bites you quietly in production. You ship it, users ask questions whose answers sit in the middle of long documents, and the model confidently gives wrong answers. No crash, just quality silently degrading.

Convention: **Context Rot** = the phenomenon where a Transformer model's recall ability for information decreases as that information's position in the context window moves away from both ends. Source: Anthropic Engineering Blog, *Effective Context Engineering for AI Agents* (2026).

RAG exists to fight context rot. Instead of feeding the full document, each query retrieves just the 3–5 most relevant chunks, keeping the active context window small and signal-dense.

---

## Beat 3 — Theory

*This section contains no code.*

### 3.1 RAG is five decisions, not one thing

Lena is about to gain a capability that sounds deceptively simple — "search documents" — but is surprisingly hard to get right. Before writing code, let's be precise about what RAG actually is.

"Just add a RAG" is meaningless advice. RAG is a pipeline containing five independent stages, each with its own design choices:

```
Document → [1. Chunk] → [2. Embed] → [3. Store/Index] → [4. Retrieve] → [5. Rerank?] → LLM
```

Each stage can be independently right or wrong. A great embedding model on top of bad chunking still produces bad results. Perfect chunking with a weak retrieval strategy still fails. You need to reason about each stage separately.

Convention: **chunking** = splitting a document into retrievable units; **embedding** = converting text into a dense floating-point vector; **retrieval** = finding the vectors closest to a query vector; **reranking** = re-scoring retrieved candidates with a more expensive cross-encoder model.

The naive mental model treats RAG as just "semantic search." That's only the retrieval stage. The other four stages determine whether your system actually works in production.

### 3.2 Chunking: the decision that affects everything downstream

Bad chunking is something no embedding model can rescue you from. Three strategies cover 95% of use cases:

| Strategy | Mechanism | When to use | When it fails |
|----------|-----------|-------------|--------------|
| **Fixed-size** | Cut every N tokens, overlap M tokens | First prototype; homogeneous text (logs, transcripts) | Cuts in the middle of sentences; destroys paragraph structure |
| **Semantic** | Cut at sentence boundaries, merge until token limit | Most structured documents; preserves meaning units | Slightly more expensive at ingest time; needs a good sentence tokenizer |
| **Late chunking** | Embed full document context first, then cut the resulting embeddings | Long technical docs with heavy cross-referencing and anaphora | Needs a model that supports this (jina-embeddings-v3); more complex pipeline |

**If/then decision table — choosing your strategy:**

```
IF document is structured (clear headings, sections, numbered clauses)
    → cut at headings first, then semantic-chunk within each section
    → best for API docs, legal contracts, technical specs

IF document is pure prose (articles, books, reports)
    → semantic chunking, 256–512 tokens, ~20% overlap
    → overlap matters: retrieval happens at the chunk level,
      but answers often straddle chunk boundaries

IF you need verbatim citation or page number attribution
    → fixed-size, record (page, char_offset) in metadata
    → chunk boundaries don't matter for retrieval as long as you cite sources

IF document is code
    → cut at function/class/module boundaries, not token counts
    → a 200-line function is one semantic unit; cutting it in half destroys retrieval

IF each document is 1M+ tokens (book-length)
    → investigate late chunking (jina-embeddings-v3) or hierarchical chunking
    → for this chapter's use case, semantic chunking is sufficient
```

The rest of this chapter uses **semantic chunking**, targeting 400 tokens with 80-token overlap. This handles the vast majority of PDFs and text documents you'll encounter.

One number worth remembering: chunks longer than about 512 tokens get silently truncated by most embedding models. BGE-M3 with the right settings supports up to 8,192 tokens, but smaller chunks yield better retrieval precision — less irrelevant text surrounding the key sentences.

### 3.3 Embedding models: choosing the right vector space

An embedding model converts a piece of text into a dense vector — a list of floats. Text chunks with similar meaning end up with similar vectors (close in cosine space). The quality of this mapping sets the ceiling on your retrieval quality.

Three models cover most teams' realistic decision space:

| Model | Dimensions | Cost | Multilingual | Max tokens | When to use |
|-------|-----------|------|-------------|-----------|-------------|
| **OpenAI `text-embedding-3-large`** | 3072 | $0.13/M tokens (API) | Yes | 8,191 | Already on OpenAI and want a hosted API |
| **BAAI/bge-m3** | 768 | Free (local) | Yes (100+ languages) | 8,192 | Default choice: strong, free, runs on CPU |
| **Voyage AI `voyage-3`** | 1024 | $0.06/M tokens (API) | Partial | 32,000 | Need long-document support or RAG-optimized retrieval |

**If/then decision table — choosing your embedding model:**

```
IF documents are all English and you have budget
    → Voyage AI voyage-3 or OpenAI text-embedding-3-large
    → Anthropic's own RAG cookbook uses Voyage AI (they recommend it for Claude)

IF you need zero cost or local deployment
    → BAAI/bge-m3 (this chapter's choice)
    → 768 dimensions smaller than 3072, but competitive quality

IF documents are multilingual (Chinese, Japanese, European languages)
    → bge-m3 is the strongest free multilingual option
    → Voyage AI voyage-multilingual-2 for hosted multilingual API

IF the embedding model's max_tokens < typical chunk size
    → Problem: excess tokens get silently truncated, degrading chunk quality
    → Fix: use smaller chunks, or switch to a longer-context model
```

Convention: **cosine similarity** = the dot product of two normalized vectors; ranges from -1 (opposite meanings) to 1 (identical meanings). pgvector's `<=>` operator computes cosine **distance** (1 - similarity); a result of 0.15 means similarity = 0.85.

One often-underestimated property: similarity scores are not calibrated across models. A score of 0.80 under OpenAI embeddings and a score of 0.80 under BGE-M3 are not the same quality. Your "low confidence" threshold must be determined experimentally for each model — don't borrow numbers you see online.

### 3.4 Vector databases: the three-way decision tree

You need somewhere to store vectors and query them efficiently. For a team at Lena's current development stage, the realistic options are:

| Option | Infrastructure | Latency | Scale | When to choose |
|--------|---------------|---------|-------|---------------|
| **pgvector** (our choice) | Docker, or existing PostgreSQL | 5–50ms | ~1M rows without tuning | Already using Postgres; want simple ops |
| **Chroma** | In-process or Docker service | 2–20ms | Good to 100K rows, starts slowing at 500K+ | Prototyping; want zero config |
| **Qdrant** | Docker or managed cloud | 1–10ms | Designed for 10M+ vectors | Production at scale; need filtering + quantization |

**Decision tree:**

```
Do you already have a PostgreSQL database?
  Yes → Use pgvector. No new infrastructure, ACID transactions, familiar SQL.
  No  → Is this a prototype or a long-term system?
          Prototype  → Chroma (pip install chromadb, zero config, in-memory mode)
          Long-term  → Could vector count exceed 500K?
                        Yes → Qdrant (managed cloud or self-hosted)
                        No  → pgvector (start simple, migrate if necessary)
```

This chapter uses **pgvector** — one Docker container, standard SQL, no new services. The `pgvector/pgvector:pg16` image has the extension pre-installed.

The IVFFlat index we create in schema.sql speeds up search by partitioning vectors into `lists` clusters (centroids). For small datasets (under 1,000 rows), pgvector automatically falls back to exact search — the index isn't harmful. For datasets over 100K rows, set `lists = sqrt(num_rows)` and run `VACUUM ANALYZE chunks;` after bulk inserts.

### 3.5 Anthropic's Contextual Retrieval: a 35% improvement

Before embedding, there's a technique most RAG tutorials miss. It comes from Anthropic's *Contextual Retrieval* blog post (September 2024).

The core insight: when you embed a chunk in isolation, the vector only captures what's **inside** the chunk, not what the chunk **means in context**. A chunk that reads "the parameter is set to `max_retries=3`" is semantically ambiguous in isolation — it could come from any section of any document. When you query "retry configuration for /v2/completions," the cosine similarity between the query vector and this chunk's vector is lower than it should be, because both vectors are missing the context "this is about the /v2/completions endpoint."

The fix is having Claude prepend a short positioning sentence to each chunk before embedding:

```
Before Contextual Retrieval:
  "The parameter is set to max_retries=3."

After Contextual Retrieval:
  "[From the /v2/completions endpoint configuration section of the API specification]
   The parameter is set to max_retries=3."
```

Anthropic's evaluation across nine code repositories: **top-20 chunk retrieval failure rate reduced by 35%** (Pass@20 from ~87% to ~95%, based on Anthropic's own cookbook dataset).

The cost concern is real, but prompt caching addresses it: you send the full document to Claude marked as `cache_control: ephemeral`. For the first chunk, Anthropic writes the document to KV cache (small premium). Every subsequent chunk from the same document reads from cache at a 90% discount. For a 10,000-token document with 25 chunks:

```
Without caching:
  25 calls × 10,100 tokens = 252,500 tokens @ $0.25/MTok = $0.063

With prompt caching (Haiku pricing):
  1 cache write: 10,000 × $0.30/MTok = $0.003
  24 cache reads: 24 × 10,000 × $0.03/MTok = $0.0072
  25 generated outputs: ~125 tokens × 25 × $1.25/MTok = $0.004
  Total: ~$0.014 (78% cheaper)
```

This technique is not a LangChain abstraction — it's a prompt pattern. We implement it in 20 lines of code in Beat 5.

---

## Beat 4 — Scaffold

Build the minimal runnable skeleton first. The backend is pgvector in Docker; the Python code uses `psycopg` (official PostgreSQL driver, psycopg3 API) and `sentence-transformers` for embedding.

First, the database schema:

```sql
-- schema.sql (run once via docker compose)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    doc_id      TEXT NOT NULL,           -- e.g. "api-spec-v2.pdf"
    chunk_index INTEGER NOT NULL,        -- position in document
    content     TEXT NOT NULL,           -- raw chunk text
    context     TEXT,                    -- Anthropic contextual prefix (nullable)
    embedding   VECTOR(768),             -- BGE-M3 output: 768-dimensional vector
    metadata    JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);                  -- tune: lists ≈ sqrt(num_rows)
```

Now the minimal Python ingestion skeleton:

```python
# ingest.py — scaffold (Beat 4: runs but no real functionality yet)
import psycopg
import os

DB_URL = os.getenv("DATABASE_URL", "postgresql://lena:lena@localhost:5432/lena_rag")

def get_conn():
    return psycopg.connect(DB_URL)

def ingest_document(doc_id: str, text: str) -> None:
    """Ingest a document. Beat 4: skeleton only — no chunking or embedding yet."""
    with get_conn() as conn:
        # Placeholder: will be filled in Beat 5
        print(f"[scaffold] would ingest {len(text)} chars as doc_id={doc_id!r}")

if __name__ == "__main__":
    ingest_document("test.txt", "Hello, this is a test document.")
    print("Scaffold OK — no DB writes yet, just verifying structure.")
```

Verify the scaffold runs before adding complexity:

```bash
python ingest.py
# Expected: [scaffold] would ingest 31 chars as doc_id='test.txt'
#           Scaffold OK — no DB writes yet, just verifying structure.
```

Good. The scaffold confirms the import chain is clean. Now let's extend it step by step.

---

## Beat 5 — Incremental Assembly

Add one capability at a time. After each step, the code runs and prints something meaningful.

### Extension 1 — Chunking

| Extension | Why needed | How to add |
|-----------|-----------|------------|
| Semantic chunking | Fixed-size cuts break sentence boundaries; models embed fragments poorly | `nltk.tokenize.sent_tokenize` + greedy merge |
| 400-token target, 80-token overlap | Balance between context richness and retrieval precision | Simple sliding window over sentence list |

```python
# Chunking logic (add to ingest.py)
import nltk
nltk.download("punkt", quiet=True)

def chunk_text(text: str, target_tokens: int = 400, overlap_tokens: int = 80) -> list[str]:
    """Semantic chunking: cut at sentence boundaries, merge to ~target_tokens with overlap."""
    sentences = nltk.tokenize.sent_tokenize(text)

    # Rough token estimate: 1 token ≈ 4 characters
    def tok_count(s: str) -> int:
        return len(s) // 4

    chunks, current, current_len = [], [], 0
    for sent in sentences:
        sent_len = tok_count(sent)
        if current_len + sent_len > target_tokens and current:
            chunks.append(" ".join(current))
            # Preserve overlap: back off until we've removed (target - overlap) tokens
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

Intermediate verification — run after adding this function:

```python
# Quick smoke test
sample = "Sentence one. Sentence two. Sentence three. " * 50  # ~150 sentences
chunks = chunk_text(sample)
print(f"Chunked into {len(chunks)} chunks, first chunk length: {len(chunks[0])} chars")
# Expected: Chunked into 5-8 chunks, first chunk length: ~1600-1800 chars
```

### Extension 2 — Contextual embedding (Anthropic technique)

| Extension | Why needed | How to add |
|-----------|-----------|------------|
| Contextual prefix | Isolated chunks lose cross-references; adding context reduces retrieval failure rate by 35% | `anthropic.messages.create` on the full document with `cache_control` |
| Prompt caching | Generating context for 500 chunks without caching costs $5–15 | Set `{"type": "ephemeral"}` on the document content block |

```python
# Context generation (add to ingest.py)
import anthropic

_anthropic = anthropic.Anthropic()

DOCUMENT_PROMPT = """<document>
{doc_content}
</document>"""

CHUNK_PROMPT = """Here is the chunk we want to situate within the whole document:
<chunk>
{chunk_content}
</chunk>

Please give a short succinct context (1-2 sentences) to situate this chunk within the overall document
for the purposes of improving search retrieval of the chunk. Answer only with the succinct context
and nothing else."""

def generate_context(doc_content: str, chunk_content: str) -> str:
    """Use Anthropic Contextual Retrieval to prepend a positioning context to each chunk.

    Uses prompt caching: the document is written to cache once per batch,
    then each subsequent chunk call reads from cache at a 90% discount.
    """
    response = _anthropic.messages.create(
        model="claude-haiku-4-5",  # Haiku: fast and cheap for context generation
        max_tokens=200,
        temperature=0.0,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": DOCUMENT_PROMPT.format(doc_content=doc_content),
                    "cache_control": {"type": "ephemeral"},  # write full document to cache
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

After the first chunk of a document, `cache_read_input_tokens` will jump to the document length — confirming the cache is working. For a 10,000-token document with 25 chunks, you only pay full document price once; the other 24 calls pay just 10%.

### Extension 3 — Embedding + pgvector insertion

| Extension | Why needed | How to add |
|-----------|-----------|------------|
| BGE-M3 embedding | Free, local, 768-dimensional, strong multilingual performance | `sentence_transformers.SentenceTransformer("BAAI/bge-m3")` |
| Batch insert | Row-by-row INSERT is 10× slower than batch `executemany` | `psycopg.copy()` or `executemany` |

```python
# Embedding + insertion (add to ingest.py)
from sentence_transformers import SentenceTransformer
import numpy as np

_model = SentenceTransformer("BAAI/bge-m3")

def embed(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts. Returns list of 768-dimensional vectors."""
    vectors = _model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()

def insert_chunks(doc_id: str, chunks: list[dict]) -> int:
    """Insert a batch of chunks into pgvector.

    Each chunk dict: {"content": str, "context": str, "index": int}
    Returns number of rows inserted.
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

Intermediate verification after adding this — insert a test chunk and confirm:

```python
# Quick DB smoke test (run docker compose up first)
result = insert_chunks("smoke-test", [{"content": "test chunk", "context": None, "index": 0}])
print(f"Inserted {result} chunks")  # Expected: Inserted 1 chunks
```

### Extension 4 — Retrieval strategy: Top-K, MMR, and when to use hybrid search

Before writing retrieval code, we need to choose a retrieval strategy. Three dominant strategies:

| Strategy | Mechanism | Strengths | Weaknesses |
|----------|-----------|-----------|-----------|
| **Top-K cosine** | Return K nearest vectors | Fast, simple, easy to understand | Returns similar chunks even when results are redundant |
| **MMR (Maximal Marginal Relevance)** | Balance relevance and diversity: penalize candidates similar to already-selected chunks | Reduces result redundancy | ~2× complexity; slight recall loss |
| **Hybrid: BM25 + vector** | Combine keyword match score and cosine score via RRF (Reciprocal Rank Fusion) | Captures exact keyword matches that pure semantic search misses | Requires BM25 infrastructure (Elasticsearch or pg_bm25) |

**If/then decision table — choosing your retrieval strategy:**

```
IF documents are dense prose (reports, specs, documentation)
    → Top-K is sufficient; semantic similarity captures meaning well

IF documents contain precise technical terms, model names, error codes
    → Add hybrid search (BM25 + vector)
    → Example: "GPT-4o-2024-05-13 rate limits" — users querying exact model
      version strings need keyword matching, not just semantic similarity

IF Top-K results are highly redundant (multiple chunks saying the same thing)
    → Consider MMR for diversity
    → More useful for broad exploratory queries ("give me an overview of X")
      than precise factual questions ("what is the rate limit for /v2/completions")
```

This chapter's main pipeline implements **Top-K cosine similarity** — sufficient for structured documents and requires no additional infrastructure. Hybrid search is shown as an extension.

**Hybrid search: when BM25 matters**

Anthropic's *Contextual Retrieval* evaluation shows that adding BM25 on top of contextual embeddings improves Pass@20 for code repository queries from ~95% to ~95.2% — a modest gain. The more noticeable benefit is in queries containing precise technical identifiers:

- Model version strings: `claude-opus-4-7-20260101`
- Error codes: `RATE_LIMIT_EXCEEDED`
- Parameter names: `max_retries`
- API endpoint paths: `/v2/completions`

For these queries, BM25 keyword matching finds the exact chunk even when the semantic embedding is ambiguous. If your knowledge base contains this kind of content, add hybrid search. Otherwise, stick with pure vector retrieval.

Now write the retrieval code:

```python
# search_knowledge_base.py — Lena's tool
import psycopg, os
from sentence_transformers import SentenceTransformer

DB_URL = os.getenv("DATABASE_URL", "postgresql://lena:lena@localhost:5432/lena_rag")
_model = SentenceTransformer("BAAI/bge-m3")

def search_knowledge_base(query: str, top_k: int = 5, doc_id: str | None = None) -> str:
    """Search the knowledge base for chunks relevant to the query.

    Args:
        query: natural language question
        top_k: number of chunks to return (default 5; above 10 usually just adds noise)
        doc_id: optional, filter to a specific document

    Returns:
        Formatted string with top-k chunks and their sources.
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
        return "No relevant chunks found in the knowledge base."

    # Warn when all similarity scores are low — retrieval may have failed
    max_sim = max(row[4] for row in rows)
    warning = ""
    if max_sim < 0.50:
        warning = (
            f"[warn] Highest similarity score is {max_sim:.3f}. "
            "Retrieved chunks may not be relevant. Consider rephrasing your query "
            "or verifying that the correct documents have been ingested.\n\n"
        )

    parts = []
    for doc_id_row, chunk_idx, content, context, similarity in rows:
        header = f"[{doc_id_row} §{chunk_idx} | similarity={similarity:.3f}]"
        text = f"{context}\n\n{content}" if context else content
        parts.append(f"{header}\n{text}")

    return warning + "\n\n---\n\n".join(parts)
```

Intermediate verification — query the database after ingesting a sample document:

```bash
python search_knowledge_base.py "what is the rate limit per minute?"
# Expected: [sample §3 | similarity=0.81]
#           [From the rate limits section of the Lena API reference]
#           The API allows a maximum of 1,000 requests per minute per API key...
```

If all similarity scores are below 0.50, that's not a code bug — it means the query is semantically far from what you ingested, or you forgot to ingest a document first.

---

### Extension 5 — RAG evaluation: how do you know it's working?

This section is deliberately brief because Chapter 21 covers the full evaluation pipeline. But we need to establish a minimum viable signal right now: before you hand RAG to users, you should know whether it's working.

Convention: **Recall@K** = fraction of relevant chunks appearing in the top-K retrieval results; **Precision@K** = fraction of top-K results that are relevant. Good retrieval systems optimize Recall@K (don't miss relevant chunks) rather than Precision@K (don't waste context on irrelevant content) — the LLM can filter noise, but it can't conjure information you failed to retrieve.

Three metrics in order of importance:

| Metric | What it tells you | How to compute |
|--------|------------------|----------------|
| **Recall@K** | "Did we find the right chunks?" | For each test question, check whether the gold chunk appears in top-K results |
| **Answer faithfulness** | "Is the LLM's answer grounded in the retrieved chunks?" | LLM-as-judge: score whether the answer can be derived from the retrieved context |
| **Answer correctness** | "Is the final answer right?" | Compare against reference answers; requires a gold dataset |

The minimum viable evaluation for your RAG system is 20–50 test questions with known correct chunks. Here's how to run it:

```python
# minimal_eval.py — retrieval quality smoke test
from search_knowledge_base import _embed_query, _retrieve

# Gold dataset: list of (question, expected doc_id, expected chunk_index)
# Build by ingesting a document, then manually identifying which chunk answers each test question.
GOLDEN = [
    ("what is the rate limit per minute?", "sample", 3),
    ("how do I authenticate API requests?", "sample", 1),
    ("what is the format of error responses?", "sample", 5),
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
print(f"\nRecall@5: {recall_at_5:.1%} ({hits_at_5}/{len(GOLDEN)} questions)")
print("Target: ≥80% before shipping. Typically ≥90% with Contextual Retrieval.")
```

Run this script after ingesting your document. If Recall@5 is below 70%, the problem is almost always chunking (chunks too large, semantic boundaries broken) or document quality (scanned PDFs with OCR errors, text extraction failures). At this scale, the embedding model and retrieval strategy are rarely the bottleneck.

This is the minimum viable evaluation. Chapter 21 will show how to build a full regression test suite with CI integration.

---

## Beat 6 — Running the Full Pipeline

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

### Run example

```bash
# 1. Start pgvector
docker compose up -d

# 2. Install Python dependencies
pip install psycopg[binary] sentence-transformers anthropic nltk pypdf

# 3. Ingest a sample PDF (included in code/lena-v0.9-rag/sample_data/)
python code/lena-v0.9-rag/ingest.py --pdf sample_data/sample.pdf --doc-id sample

# Expected output (timings are approximate):
# [ingest] Loaded 12 pages, extracted 8,421 chars
# [chunk] Split into 22 chunks (avg 383 tokens)
# [context] Generating context for 22 chunks...
#   chunk 1/22: cache_creation=2847 tokens (first chunk, writing to cache)
#   chunk 2/22: cache_read=2847 tokens (90% discount kicks in)
#   ...
#   chunk 22/22: cache_read=2847 tokens
# [embed] Embedding 22 chunks with BAAI/bge-m3...
# [insert] Inserted 22 chunks into pgvector in 0.31s
# Done. Total time: 18.4s

# 4. Ask a question
python code/lena-v0.9-rag/search_knowledge_base.py "what is the maximum request rate per minute?"

# Expected output:
# [sample §4 | similarity=0.847]
# [From the rate limits section of the API reference]
#
# The API allows a maximum of 1,000 requests per minute per API key...
```

**Common failure modes:**

- `psycopg.OperationalError: connection refused` — docker compose isn't up yet; run `docker compose up -d` and wait 5 seconds before running the ingest script.
- `ERROR: type "vector" does not exist` — schema.sql wasn't executed; run `psql -U lena lena_rag < schema.sql` manually.
- `SentenceTransformer: model not found` — first run downloads BGE-M3 (~560MB); allow network access and wait 2–3 minutes.
- Similarity scores all below 0.5 — typically means the document has no relevant content, or chunks are too large (text being silently truncated by BGE-M3's 512-token input limit; use smaller chunks or `BAAI/bge-m3` with `max_length=8192`).

### Integrating into Lena

`search_knowledge_base` becomes Lena's fifth tool. The Anthropic tool definition:

```python
SEARCH_KB_TOOL = {
    "name": "search_knowledge_base",
    "description": (
        "Search the vector knowledge base for information relevant to a query. "
        "Use this tool when you need to answer questions about ingested documents. "
        "Returns the most relevant chunks with similarity scores."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language question or search query"
            },
            "top_k": {
                "type": "integer",
                "description": "Number of chunks to retrieve (default 5, max 15)",
                "default": 5
            },
            "doc_id": {
                "type": "string",
                "description": "Optional: restrict search to a specific document ID"
            }
        },
        "required": ["query"]
    }
}
```

With this tool registered, Lena can handle: "Based on the API spec we ingested, what is the format of the `metadata` field?" — she calls `search_knowledge_base(query="metadata field format API spec")`, gets back the relevant chunks, and synthesizes an answer without putting any document into the system prompt.

---

## Beat 7 — Design Note

### Design Note 1: Why Not Just Fill the Context Window?

The obvious alternative: put the full document into Claude's 200K context window. For some scenarios (a single short document, a one-off Q&A session) this is actually the right call — it's simpler and avoids infrastructure overhead.

The trade-offs:

- **Cost**: 150K tokens × $3/MTok (Sonnet) = $0.45 per question. 1,000 questions a day is $450/day, versus about $0.02/day for RAG retrieving 5 chunks.
- **Context rot**: Anthropic research documents recall degradation as context grows. A fact located at token 80,000 in a 100K-token context has about 40% lower recall accuracy than the same fact at token 3,000. This isn't a hard cutoff — it's a gradient curve. You won't see a crash; you'll just see quality silently declining.
- **Latency**: a 150K-token prompt takes 3–8 seconds to first token; a RAG prompt with 5 chunks takes about 0.3 seconds.

**Recommendation**: if your document is under 20 pages and users ask only a handful of questions per day, stuff the document into the context window. For larger scale or higher traffic, the cost and quality advantages of RAG are clear.

This chapter's design choices — pgvector plus single-model retrieval — can handle up to about 10,000 pages without modification. Don't add a dedicated reranker, a vector database cluster, or a BM25 hybrid layer until you have evidence the simple version isn't sufficient.

---

### Design Note 2: Why Agent + RAG Is the Default Architecture for LLM Applications

RAG alone is not enough. RAG alone can only answer "what does the document say" — it can't decide *which* document to search, *when* to search versus using its own knowledge, or *whether* the retrieved answer is trustworthy enough to act on.

The agent wrapper supplies the missing layer:

```
User question
    → Agent decides: is this in the knowledge base, or common knowledge?
    → If KB: call search_knowledge_base with the right query terms
    → Evaluate retrieved chunks: relevant? similarity high enough?
    → If low confidence: either ask for clarification, or fall back to training knowledge
    → Synthesize final answer and cite sources
```

This is why 75% of AI agent job listings (based on an analysis of 32 job descriptions across 15 companies) list RAG as a required skill rather than a nice-to-have. In practice, "building an AI agent" almost always means "building an agent that can reason about your private data." The RAG pipeline is the plumbing that makes that possible.

A word from Anthropic's *Building Effective Agents* (2024-12-19): "Start with the simplest solution, and only add complexity when necessary." This chapter's pgvector + single-model approach can handle up to about 10,000 pages without modification. Don't add a dedicated reranker, a vector database cluster, or a BM25 hybrid layer until you have evidence the simple version isn't sufficient.

---

## Appendix: Chapter 9 — Reranker

The code in `rerank.py` shows how to add a second-stage reranker. It's not in the main pipeline because for most documents it adds 100–200ms of latency for only a 2–5% precision gain. Add it when you have evidence you need it.

The decision rule is simple:

```
IF top-5 chunk similarity scores are all above 0.75:
    → Skip the reranker (retrieval is already high-confidence)

IF top chunks cluster between 0.55 and 0.70 (retrieval is uncertain):
    → Add reranker: it will surface the truly relevant chunks

IF top chunk similarity is < 0.50:
    → Retrieval may have completely failed; a reranker can't save you
    → Ask yourself: did you ingest the right document? Is the query in-distribution?
```

**When to use Cohere vs. BGE-Reranker:**

| Model | Cost | Latency | When to use |
|-------|------|---------|-------------|
| Cohere `rerank-english-v3.0` | $2/1K queries | ~100ms | English-only documents; want a hosted API |
| `BAAI/bge-reranker-v2-m3` | Free, local | ~200ms on CPU | Multilingual; cost-sensitive; local deployment |

---

## Chapter Summary

Lena v0.9 can now read a 200-page PDF and answer questions about it. The pipeline:

1. **Chunk**: semantic chunking of the document (400 tokens, 80-token overlap)
2. **Generate context**: use Anthropic's Contextual Retrieval technique for each chunk (35% reduction in retrieval failure rate, near-free via prompt caching)
3. **Embed**: embed chunks + context with BGE-M3 (free, 768-dimensional)
4. **Store**: store in pgvector (one Docker service, standard PostgreSQL)
5. **Retrieve**: retrieve by cosine similarity, return top-K
6. **Rerank (optional)**: use BGE-Reranker for uncertain queries

The `search_knowledge_base` tool is 40 lines of code. The infrastructure is one Docker service that you already have if you're running PostgreSQL. This is not a framework — it's three SQL queries and one embedding call.

The next chapter — Context Engineering — will teach you how to ensure Lena's retrieved chunks land in the right position in her context window, and how to compress what she retrieves when it exceeds capacity.

---

## Navigation

➡️ **[Ch 10. Context Engineering: Token Economics](../ch10-context-engineering/README.md)** — three-layer compression, prompt caching, TokenMonitor

[← Ch 8. Memory and Context](../ch08-memory/README.md) · [📘 Back to full table of contents](../../README.md)
