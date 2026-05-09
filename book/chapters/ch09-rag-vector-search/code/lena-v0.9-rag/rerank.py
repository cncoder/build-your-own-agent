"""
rerank.py — Lena v0.9 optional reranking layer

Adds a second-stage reranker on top of pgvector retrieval.
Supports two backends:
  - BAAI/bge-reranker-v2-m3  (local, free, multilingual)
  - Cohere rerank-english-v3.0 (API, $2/1K queries, English-only)

Decision rule for when to add reranking:
  - Top-5 similarities all > 0.75   → skip (retrieval already high-confidence)
  - Top chunks cluster 0.55–0.70    → add reranker (promotes the right chunk)
  - Top chunk similarity < 0.50     → retrieval likely failed; reranker won't save you

Usage:
    from rerank import rerank_results
    from search_knowledge_base import search_knowledge_base

    raw = search_knowledge_base("rate limit for /v2/completions", top_k=15)
    # ... or use the lower-level _retrieve() function directly:
    from search_knowledge_base import _embed_query, _retrieve
    query_vec = _embed_query("rate limit for /v2/completions")
    results = _retrieve(query_vec, top_k=15, doc_id=None)
    reranked = rerank_results("rate limit for /v2/completions", results, top_k=5)

Dependencies (choose one backend):
    pip install sentence-transformers          # for BGE backend
    pip install cohere                         # for Cohere backend

Environment (Cohere backend only):
    COHERE_API_KEY
"""

import os
from typing import Literal

# ── backend: BGE-Reranker (local, free) ──────────────────────────────────────

def _rerank_bge(
    query: str,
    candidates: list[dict],
    top_k: int,
    model_name: str = "BAAI/bge-reranker-v2-m3",
) -> list[dict]:
    """Rerank using BGE-Reranker-v2-m3 running locally.

    Model: BAAI/bge-reranker-v2-m3
    Dimensions: cross-encoder (scores query-chunk pair directly, no vector)
    Latency: ~200ms per batch of 15 on CPU, ~50ms on GPU
    Download: ~580MB (one-time)
    """
    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        raise ImportError("pip install sentence-transformers  # needed for BGE reranker")

    reranker = CrossEncoder(model_name)

    # CrossEncoder expects list of (query, passage) pairs
    texts = [c["content"] for c in candidates]
    pairs = [(query, t) for t in texts]

    scores = reranker.predict(pairs)  # returns numpy array of float scores

    # Attach reranker scores and sort descending
    scored = [(score, chunk) for score, chunk in zip(scores, candidates)]
    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, chunk in scored[:top_k]:
        results.append({**chunk, "rerank_score": float(score)})
    return results


# ── backend: Cohere (API, English-only) ──────────────────────────────────────

def _rerank_cohere(
    query: str,
    candidates: list[dict],
    top_k: int,
    model: str = "rerank-english-v3.0",
) -> list[dict]:
    """Rerank using Cohere's managed reranking API.

    Model: rerank-english-v3.0
    Cost: $2 per 1,000 queries (regardless of candidates per query)
    Latency: ~100ms round-trip
    Language: English only (use BGE for multilingual)
    """
    try:
        import cohere
    except ImportError:
        raise ImportError("pip install cohere  # needed for Cohere reranker")

    api_key = os.getenv("COHERE_API_KEY")
    if not api_key:
        raise EnvironmentError("COHERE_API_KEY environment variable not set")

    co = cohere.Client(api_key)
    documents = [c["content"] for c in candidates]

    response = co.rerank(
        model=model,
        query=query,
        documents=documents,
        top_n=top_k,
    )

    results = []
    for hit in response.results:
        original = candidates[hit.index]
        results.append({**original, "rerank_score": hit.relevance_score})
    return results


# ── public interface ──────────────────────────────────────────────────────────

def rerank_results(
    query: str,
    candidates: list[dict],
    top_k: int = 5,
    backend: Literal["bge", "cohere"] = "bge",
) -> list[dict]:
    """Rerank retrieved candidates and return the top-k most relevant.

    This is a second-stage refinement on top of pgvector's ANN (approximate
    nearest neighbor) retrieval. Typical use:
      1. Retrieve top-15 from pgvector (broad net)
      2. Rerank to top-5 (precision focus)

    Args:
        query: Original user query string.
        candidates: List of chunk dicts from search_knowledge_base._retrieve().
                    Each dict must have at least: content (str).
        top_k: Number of final results to return after reranking.
        backend: "bge" (local, free, multilingual) or "cohere" (API, English, $2/1K).

    Returns:
        List of chunk dicts, same structure as input but sorted by rerank_score
        (descending). The rerank_score field is added.

    Decision guide:
        IF multilingual content or no budget: use backend="bge"
        IF English-only and query latency is critical: use backend="cohere" (~100ms vs ~200ms)
        IF similarity scores are all below 0.50: skip reranker entirely
    """
    if not candidates:
        return []

    # Safety check: if retrieval quality is already very low, reranking won't help
    max_sim = max(c.get("similarity", 0) for c in candidates)
    if max_sim < 0.45:
        print(
            f"[rerank] Warning: max retrieval similarity is {max_sim:.3f}. "
            "Reranking may not help — check that the right documents are ingested."
        )

    if backend == "bge":
        return _rerank_bge(query, candidates, top_k)
    elif backend == "cohere":
        return _rerank_cohere(query, candidates, top_k)
    else:
        raise ValueError(f"Unknown reranker backend: {backend!r}. Choose 'bge' or 'cohere'.")


def format_reranked_results(results: list[dict]) -> str:
    """Format reranked results for inclusion in a prompt."""
    if not results:
        return "No relevant chunks found."

    parts = []
    for r in results:
        rerank_tag = f", rerank={r['rerank_score']:.3f}" if "rerank_score" in r else ""
        header = f"[{r['doc_id']} §{r['chunk_index']} | sim={r['similarity']:.3f}{rerank_tag}]"
        text = f"{r['context']}\n\n{r['content']}" if r.get("context") else r["content"]
        parts.append(f"{header}\n{text}")
    return "\n\n---\n\n".join(parts)


# ── example pipeline combining retrieval + rerank ─────────────────────────────

def search_with_reranking(
    query: str,
    top_k: int = 5,
    overretrieve_factor: int = 3,
    doc_id: str | None = None,
    backend: Literal["bge", "cohere"] = "bge",
) -> str:
    """Full pipeline: embed → retrieve top_k*factor → rerank to top_k.

    The overretrieve_factor controls the initial retrieval breadth:
    - Factor 3 (default): retrieve 15 when top_k=5, then rerank to 5
    - Factor 5: retrieve 25 when top_k=5, higher recall at higher reranker cost

    Returns formatted string with reranked results.
    """
    from search_knowledge_base import _embed_query, _retrieve

    initial_k = min(top_k * overretrieve_factor, 50)
    query_vec = _embed_query(query)
    candidates = _retrieve(query_vec, top_k=initial_k, doc_id=doc_id)

    if not candidates:
        return "No chunks found in the knowledge base."

    reranked = rerank_results(query, candidates, top_k=top_k, backend=backend)
    return format_reranked_results(reranked)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Search and rerank Lena's knowledge base")
    parser.add_argument("query", help="Natural language query")
    parser.add_argument("--doc-id", default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--backend",
        choices=["bge", "cohere"],
        default="bge",
        help="Reranker backend (default: bge)",
    )
    args = parser.parse_args()

    result = search_with_reranking(
        query=args.query,
        top_k=args.top_k,
        doc_id=args.doc_id,
        backend=args.backend,
    )
    print(result)
