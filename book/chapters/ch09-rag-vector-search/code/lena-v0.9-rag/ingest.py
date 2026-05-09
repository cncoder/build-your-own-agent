"""
ingest.py — Lena v0.9 RAG: chunk + contextualize + embed + write to pgvector

Usage:
    python ingest.py --pdf sample_data/sample.pdf --doc-id my-doc
    python ingest.py --txt sample_data/sample.txt --doc-id my-txt

Dependencies:
    pip install psycopg[binary] sentence-transformers boto3 nltk pypdf

Environment:
    DATABASE_URL  (default: postgresql://lena:lena@localhost:5432/lena_rag)
    AWS_REGION    (default: us-west-2)

本书代码默认 Bedrock。OpenAI/Anthropic 直连映射见附录 D。
"""

import argparse
import os
import sys
import time
from pathlib import Path

import boto3
import nltk
import psycopg
from sentence_transformers import SentenceTransformer

# ── one-time NLTK data download ─────────────────────────────────────────────
nltk.download("punkt", quiet=True)
nltk.download("punkt_tab", quiet=True)

# ── configuration ────────────────────────────────────────────────────────────
DB_URL = os.getenv("DATABASE_URL", "postgresql://lena:lena@localhost:5432/lena_rag")
BEDROCK_REGION = os.getenv("AWS_REGION", "us-west-2")
# Haiku 4-5：快且便宜，适合大批量 context 生成
CONTEXT_MODEL = "us.anthropic.claude-haiku-4-5"
EMBED_MODEL = "BAAI/bge-m3"
CHUNK_TARGET_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 80

_embed_model: SentenceTransformer | None = None
_bedrock_client = None


def get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        print(f"[embed] Loading {EMBED_MODEL} (first run downloads ~560MB)...")
        _embed_model = SentenceTransformer(EMBED_MODEL)
    return _embed_model


def get_bedrock():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
    return _bedrock_client


# ── text extraction ───────────────────────────────────────────────────────────

def extract_text_from_pdf(path: str) -> str:
    """Extract raw text from a PDF. Requires pypdf."""
    try:
        import pypdf
    except ImportError:
        sys.exit("pypdf not installed. Run: pip install pypdf")

    reader = pypdf.PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text and text.strip():
            pages.append(text)
        else:
            print(f"  [warn] page {i+1} has no extractable text (scanned image?)")
    return "\n\n".join(pages)


def extract_text_from_txt(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


# ── chunking ──────────────────────────────────────────────────────────────────

def rough_token_count(text: str) -> int:
    """Rough approximation: 1 token ≈ 4 chars (English prose)."""
    return max(1, len(text) // 4)


def chunk_text(
    text: str,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    """Semantic chunking: split on sentences, merge greedily to ~target_tokens."""
    sentences = nltk.tokenize.sent_tokenize(text)
    if not sentences:
        return [text] if text.strip() else []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        sent_len = rough_token_count(sent)
        if current_len + sent_len > target_tokens and current:
            chunks.append(" ".join(current))
            # keep overlap tail
            tail: list[str] = []
            budget = overlap_tokens
            for s in reversed(current):
                if budget <= 0:
                    break
                tail.insert(0, s)
                budget -= rough_token_count(s)
            current = tail
            current_len = sum(rough_token_count(s) for s in tail)
        current.append(sent)
        current_len += sent_len

    if current:
        chunks.append(" ".join(current))

    return [c for c in chunks if c.strip()]


# ── Bedrock Contextual Retrieval ───────────────────────────────────────────

DOCUMENT_CONTEXT_PROMPT = """<document>
{doc_content}
</document>"""

CHUNK_CONTEXT_PROMPT = """Here is the chunk we want to situate within the whole document:
<chunk>
{chunk_content}
</chunk>

Give a short succinct context (1-2 sentences) to situate this chunk within the overall document \
for the purpose of improving search retrieval. Answer only with the context, no preamble."""


def generate_context_for_chunk(
    doc_content: str,
    chunk_content: str,
    chunk_idx: int,
    total_chunks: int,
) -> tuple[str, int]:
    """Use Bedrock Contextual Retrieval to prepend situating context to a chunk.

    Haiku-4-5 is used here: fast and cheap for batch context generation.
    Returns (context_text, input_tokens).
    """
    client = get_bedrock()
    user_text = (
        DOCUMENT_CONTEXT_PROMPT.format(doc_content=doc_content)
        + "\n\n"
        + CHUNK_CONTEXT_PROMPT.format(chunk_content=chunk_content)
    )
    response = client.converse(
        modelId=CONTEXT_MODEL,
        messages=[{"role": "user", "content": [{"text": user_text}]}],
        inferenceConfig={"maxTokens": 200, "temperature": 0.0},
    )
    context = response["output"]["message"]["content"][0]["text"].strip()
    input_tokens = response.get("usage", {}).get("inputTokens", 0)
    print(f"  chunk {chunk_idx+1}/{total_chunks}: [input_tokens={input_tokens}]")
    return context, input_tokens


# ── embedding ─────────────────────────────────────────────────────────────────

def embed_batch(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """Embed texts in batches. Returns list of 768-dim float vectors."""
    model = get_embed_model()
    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        vecs = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        all_vectors.extend(vecs.tolist())
    return all_vectors


# ── database ──────────────────────────────────────────────────────────────────

def get_conn() -> psycopg.Connection:
    return psycopg.connect(DB_URL)


def insert_chunks(doc_id: str, chunks: list[dict]) -> int:
    """Insert prepared chunk dicts into pgvector."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO chunks (doc_id, chunk_index, content, context, embedding)
                   VALUES (%s, %s, %s, %s, %s::vector)""",
                [
                    (
                        doc_id,
                        c["index"],
                        c["content"],
                        c.get("context"),
                        str(c["embedding"]),
                    )
                    for c in chunks
                ],
            )
        conn.commit()
    return len(chunks)


def delete_doc(doc_id: str) -> int:
    """Remove all chunks for a doc_id (idempotent re-ingest)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))
            deleted = cur.rowcount
        conn.commit()
    return deleted


# ── main pipeline ─────────────────────────────────────────────────────────────

def ingest_document(
    doc_id: str,
    text: str,
    use_contextual_retrieval: bool = True,
) -> None:
    """Full ingest pipeline: chunk → [contextualize] → embed → insert."""
    t0 = time.time()

    # 1. Chunk
    chunks_text = chunk_text(text)
    print(f"[chunk] Split into {len(chunks_text)} chunks (target {CHUNK_TARGET_TOKENS} tokens)")
    if not chunks_text:
        print("[warn] No chunks produced — is the document empty?")
        return

    # 2. Delete existing rows for this doc_id (idempotent)
    deleted = delete_doc(doc_id)
    if deleted:
        print(f"[db] Removed {deleted} existing chunks for doc_id={doc_id!r}")

    # 3. Generate contextual descriptions (optional but recommended)
    contexts: list[str | None] = [None] * len(chunks_text)
    if use_contextual_retrieval:
        print(f"[context] Generating context for {len(chunks_text)} chunks via Bedrock ({CONTEXT_MODEL})...")
        for i, chunk in enumerate(chunks_text):
            ctx, _ = generate_context_for_chunk(text, chunk, i, len(chunks_text))
            contexts[i] = ctx

    # 4. Embed: text_to_embed = context + chunk (or just chunk if no context)
    print(f"[embed] Embedding {len(chunks_text)} chunks with {EMBED_MODEL}...")
    texts_to_embed = [
        f"{ctx}\n\n{chunk}" if ctx else chunk
        for ctx, chunk in zip(contexts, chunks_text)
    ]
    vectors = embed_batch(texts_to_embed)

    # 5. Insert
    prepared = [
        {
            "index": i,
            "content": chunk,
            "context": ctx,
            "embedding": vec,
        }
        for i, (chunk, ctx, vec) in enumerate(zip(chunks_text, contexts, vectors))
    ]
    count = insert_chunks(doc_id, prepared)
    elapsed = time.time() - t0
    print(f"[insert] Inserted {count} chunks into pgvector in {elapsed:.1f}s")
    print(f"Done. doc_id={doc_id!r}, chunks={count}, total_time={elapsed:.1f}s")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingest a document into Lena's knowledge base")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf", metavar="PATH", help="Path to a PDF file")
    group.add_argument("--txt", metavar="PATH", help="Path to a plain text file")
    parser.add_argument(
        "--doc-id",
        required=True,
        help="Unique identifier for this document (e.g. 'api-spec-v2')",
    )
    parser.add_argument(
        "--no-context",
        action="store_true",
        help="Skip Bedrock Contextual Retrieval (faster, lower quality)",
    )
    args = parser.parse_args()

    if args.pdf:
        print(f"[ingest] Extracting text from PDF: {args.pdf}")
        text = extract_text_from_pdf(args.pdf)
    else:
        print(f"[ingest] Reading text file: {args.txt}")
        text = extract_text_from_txt(args.txt)

    print(f"[ingest] Extracted {len(text):,} chars")
    if len(text) < 50:
        sys.exit("[error] Document appears to have no extractable text. Aborting.")

    ingest_document(
        doc_id=args.doc_id,
        text=text,
        use_contextual_retrieval=not args.no_context,
    )


if __name__ == "__main__":
    main()
