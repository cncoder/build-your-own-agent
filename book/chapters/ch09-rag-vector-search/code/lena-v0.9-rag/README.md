# lena-v0.9-rag — How to Run

## What this is

Lena's `search_knowledge_base` tool. Ingest any PDF or text file into pgvector,
then query it with natural language. Lena uses this as her fifth tool.

Full pipeline: PDF → chunk → Anthropic contextual context → BGE-M3 embed → pgvector → retrieve → (optional) BGE-Reranker.

## Requirements

- Docker (for pgvector)
- Python 3.11+
- `ANTHROPIC_API_KEY` (for contextual retrieval; skip with `--no-context` if not available)

## Quick Start

```bash
# 1. Start pgvector
docker compose up -d

# Wait ~5 seconds for pgvector to initialize, then:

# 2. Install dependencies
pip install psycopg[binary] sentence-transformers anthropic nltk pypdf

# 3. Ingest the sample PDF
python ingest.py --pdf sample_data/sample.pdf --doc-id sample

# Expected output:
# [ingest] Extracting text from PDF: sample_data/sample.pdf
# [ingest] Extracted 8,421 chars
# [chunk] Split into 22 chunks (target 400 tokens)
# [context] Generating context for 22 chunks...
#   chunk 1/22: [cache_creation=2847 tokens]
#   chunk 2/22: [cache_read=2847 tokens]
#   ...
# [embed] Embedding 22 chunks with BAAI/bge-m3...
# [insert] Inserted 22 chunks into pgvector in 0.31s
# Done. doc_id='sample', chunks=22, total_time=18.4s

# 4. Ask a question
python search_knowledge_base.py "What is the maximum request rate per minute?"

# Expected output:
# [sample §4 | similarity=0.847]
# [From the rate limiting section of the API reference]
#
# The API enforces a maximum of 1,000 requests per minute per API key...
```

## Without ANTHROPIC_API_KEY

The contextual retrieval step is optional. Skip it with `--no-context`:

```bash
python ingest.py --pdf sample_data/sample.pdf --doc-id sample --no-context
```

Retrieval quality will be lower (~35% more failures at top-20), but the pipeline
still works. Use this for testing or if you don't have an Anthropic API key.

## With Reranking

For higher precision (useful when retrieval scores cluster in the 0.55–0.70 range):

```bash
python rerank.py "What is the rate limit?" --top-k 5 --backend bge
```

BGE-Reranker runs locally. First run downloads ~580MB.

## File Overview

| File | Purpose |
|------|---------|
| `ingest.py` | Chunk + contextualize + embed + insert into pgvector |
| `search_knowledge_base.py` | Query pgvector, return formatted chunks |
| `rerank.py` | Optional second-stage reranker (BGE or Cohere) |
| `schema.sql` | pgvector schema (auto-applied by docker compose) |
| `docker-compose.yml` | pgvector service |
| `sample_data/sample.pdf` | Example PDF for testing |

## Environment Variables

| Variable | Default | Required |
|----------|---------|----------|
| `DATABASE_URL` | `postgresql://lena:lena@localhost:5432/lena_rag` | No (has default) |
| `ANTHROPIC_API_KEY` | — | For contextual retrieval only |
| `COHERE_API_KEY` | — | For Cohere reranker backend only |

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `psycopg.OperationalError: connection refused` | pgvector not running | `docker compose up -d && sleep 5` |
| `ERROR: type "vector" does not exist` | schema.sql didn't apply | Run `psql -U lena lena_rag < schema.sql` |
| `SentenceTransformer: model not found` | BGE-M3 not downloaded | Allow network, wait 2–3 minutes |
| All similarities below 0.50 | Query out of distribution | Check right document was ingested; try rephrasing |
| `ANTHROPIC_API_KEY: invalid` | Wrong API key | Check the key in your environment |

## Note on the IVFFlat Index

The `schema.sql` creates an IVFFlat index with `lists = 100`. This index accelerates
similarity search but is only useful with ~1,000+ rows. For smaller datasets (e.g. testing
with a single short document), pgvector falls back to exact search automatically — no action needed.

For very large datasets (>100K chunks), increase `lists` to `sqrt(num_rows)` and
run `VACUUM ANALYZE chunks;` after bulk inserts to update index statistics.
