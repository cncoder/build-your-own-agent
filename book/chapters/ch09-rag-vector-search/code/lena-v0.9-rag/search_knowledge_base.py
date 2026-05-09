"""
search_knowledge_base.py — Lena v0.9 RAG retrieval tool

This is the tool Lena calls when she needs to answer questions about ingested documents.
Can be run standalone as a CLI or imported as a module.

Usage (CLI):
    python search_knowledge_base.py "What is the rate limit for /v2/completions?"
    python search_knowledge_base.py "What is the rate limit?" --doc-id api-spec-v2 --top-k 3

Usage (as Lena tool):
    from search_knowledge_base import search_knowledge_base
    result = search_knowledge_base("What is the rate limit?", top_k=5)

Dependencies:
    pip install psycopg[binary] sentence-transformers

Environment:
    DATABASE_URL  (default: postgresql://lena:lena@localhost:5432/lena_rag)
"""

import argparse
import os

import psycopg
from sentence_transformers import SentenceTransformer

# ── configuration ─────────────────────────────────────────────────────────────
DB_URL = os.getenv("DATABASE_URL", "postgresql://lena:lena@localhost:5432/lena_rag")
EMBED_MODEL = "BAAI/bge-m3"
MAX_TOP_K = 15  # hard cap: more than this adds noise, not signal

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


# ── core retrieval ────────────────────────────────────────────────────────────

def _embed_query(query: str) -> list[float]:
    """Embed a single query string. Returns a 768-dim normalized vector."""
    model = _get_model()
    vec = model.encode([query], normalize_embeddings=True)[0]
    return vec.tolist()


def _retrieve(
    query_vec: list[float],
    top_k: int,
    doc_id: str | None,
) -> list[dict]:
    """Run cosine similarity search against pgvector.

    Uses the <=> operator (cosine distance). Lower distance = higher similarity.
    Returns list of row dicts: doc_id, chunk_index, content, context, similarity.
    """
    vec_str = str(query_vec)
    sql = """
        SELECT
            doc_id,
            chunk_index,
            content,
            context,
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

    return [
        {
            "doc_id": row[0],
            "chunk_index": row[1],
            "content": row[2],
            "context": row[3],
            "similarity": float(row[4]),
        }
        for row in rows
    ]


def _format_results(results: list[dict]) -> str:
    """Format retrieved chunks as a string suitable for inserting into a prompt."""
    if not results:
        return "No relevant chunks found in the knowledge base."

    # Warn when all similarities are low — the query may be out of distribution
    max_sim = max(r["similarity"] for r in results)
    if max_sim < 0.50:
        warning = (
            f"[warn] Highest similarity score is {max_sim:.3f} — "
            "retrieved chunks may not be relevant to your query. "
            "Consider rephrasing or checking that the right document was ingested.\n\n"
        )
    else:
        warning = ""

    parts = []
    for r in results:
        header = f"[{r['doc_id']} §{r['chunk_index']} | similarity={r['similarity']:.3f}]"
        text = f"{r['context']}\n\n{r['content']}" if r["context"] else r["content"]
        parts.append(f"{header}\n{text}")

    return warning + "\n\n---\n\n".join(parts)


# ── public interface (Lena tool) ──────────────────────────────────────────────

def search_knowledge_base(
    query: str,
    top_k: int = 5,
    doc_id: str | None = None,
) -> str:
    """Search the vector knowledge base for chunks relevant to a query.

    This is the function registered as Lena's search_knowledge_base tool.

    Args:
        query: Natural language question or search string.
        top_k: Number of chunks to return. Default 5. Capped at 15 — more adds
               noise, not signal. If you need broader coverage, ingest smaller chunks.
        doc_id: Optional filter. If provided, only chunks from this document are
                searched. Useful when the user has explicitly referenced a document.

    Returns:
        Formatted string with the top-k chunks, each prefixed with
        [doc_id §chunk_index | similarity=N.NNN]. The caller (Lena) should
        cite the doc_id and chunk_index when answering.

    Failure modes:
        - "No relevant chunks" — table is empty or doc_id filter matches nothing.
        - Low similarity warning — query is semantically far from ingested content.
        - psycopg.OperationalError — database is not running; check docker compose.
    """
    top_k = min(top_k, MAX_TOP_K)  # enforce hard cap

    try:
        query_vec = _embed_query(query)
        results = _retrieve(query_vec, top_k, doc_id)
    except psycopg.OperationalError as e:
        return (
            f"[error] Cannot connect to pgvector database: {e}\n"
            "Make sure the database is running: docker compose up -d"
        )

    return _format_results(results)


# ── Anthropic tool definition (for Lena's tool registry) ─────────────────────

TOOL_DEFINITION = {
    "name": "search_knowledge_base",
    "description": (
        "Search the vector knowledge base for information relevant to a query. "
        "Use this tool when you need to answer questions about documents that have "
        "been ingested (PDFs, text files, etc.). "
        "Returns the top matching chunks with similarity scores and source citations. "
        "Do NOT use this tool for general knowledge questions — only for questions "
        "about ingested documents."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural language question or search string. "
                    "Be specific: 'rate limit for /v2/completions endpoint' is better "
                    "than 'what are the limits'."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": (
                    "Number of chunks to retrieve. Default 5. Max 15. "
                    "Use 3 for focused questions, 10 for broad exploratory questions."
                ),
                "default": 5,
            },
            "doc_id": {
                "type": "string",
                "description": (
                    "Optional: restrict search to a specific document by its doc_id. "
                    "Leave empty to search all ingested documents."
                ),
            },
        },
        "required": ["query"],
    },
}


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Search Lena's knowledge base")
    parser.add_argument("query", help="Natural language query")
    parser.add_argument(
        "--doc-id", default=None, help="Restrict search to a specific document ID"
    )
    parser.add_argument(
        "--top-k", type=int, default=5, help="Number of chunks to return (default: 5)"
    )
    args = parser.parse_args()

    result = search_knowledge_base(
        query=args.query,
        top_k=args.top_k,
        doc_id=args.doc_id,
    )
    print(result)


if __name__ == "__main__":
    main()
