-- schema.sql — pgvector schema for Lena v0.9 RAG
-- Applied automatically by docker-entrypoint-initdb.d on first container start.
-- Safe to run multiple times (IF NOT EXISTS guards).

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Main chunks table
-- embedding dimension: 768 (BAAI/bge-m3 output)
-- If you switch embedding models, drop and recreate this table.
CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    doc_id      TEXT        NOT NULL,           -- e.g. "api-spec-v2"
    chunk_index INTEGER     NOT NULL,           -- position within document (0-indexed)
    content     TEXT        NOT NULL,           -- original chunk text
    context     TEXT,                           -- Anthropic contextual prepend (may be NULL)
    embedding   VECTOR(768),                    -- BGE-M3 768-dim normalized vector
    metadata    JSONB       DEFAULT '{}'::jsonb, -- extensible: page number, section, etc.
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast cosine similarity search
-- lists = 100: tune to sqrt(expected_rows) for large datasets
-- For < 1000 rows pgvector uses exact search automatically — no harm done
CREATE INDEX IF NOT EXISTS chunks_embedding_cosine_idx
    ON chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Index for fast doc_id filtering (common access pattern)
CREATE INDEX IF NOT EXISTS chunks_doc_id_idx
    ON chunks (doc_id);

-- Composite index for ordered chunk retrieval within a document
CREATE INDEX IF NOT EXISTS chunks_doc_chunk_idx
    ON chunks (doc_id, chunk_index);
