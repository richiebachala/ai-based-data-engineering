# Chapter 5: Context Engineering — Retrieval, Shaping, Provenance
# Section: 5.2 Hybrid retrieval — BM25 + semantic + RRF
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Hybrid retrieval combining BM25 (keyword) and semantic (vector) search
with Reciprocal Rank Fusion (RRF).

Contextual Retrieval (Anthropic, Nov 2024):
  Prepend a 2-3 sentence document-level context summary to each chunk
  before embedding. Reduces top-20 retrieval failures by up to 49%.
  Combined with BM25 + RRF: up to 67% reduction.

The bug fix for C5-1 (Cortex Search filter) is shown in the
Snowflake Cortex Search integration at the bottom of this file.
"""

from dataclasses import dataclass, field
from typing import Optional
import anthropic
import json

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    raise ImportError("pip install rank-bm25>=0.2")

client = anthropic.Anthropic()


@dataclass
class RetrievedChunk:
    source:      str
    source_type: str
    content:     str
    bm25_rank:   Optional[int]   = None
    semantic_rank: Optional[int] = None
    rrf_score:   float           = 0.0
    token_estimate: int          = 0

    def __post_init__(self):
        self.token_estimate = max(1, len(self.content) // 4)


# ============================================================
# Contextual Retrieval: enrich chunks before embedding
# ============================================================

def add_contextual_prefix(
    document_summary: str,
    chunk_content: str,
    chunk_type: str = "documentation",
) -> str:
    """
    Prepend a document-level context summary to a chunk before embedding.

    Anthropic Contextual Retrieval: this operation uses prompt caching
    — the full document is cached after the first chunk, and all
    subsequent chunks hit the cache at 10% of normal input token cost.
    """
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=150,
        system=[
            {
                "type": "text",
                "text": document_summary,
                "cache_control": {"type": "ephemeral"}  # cache the full document
            }
        ],
        messages=[{"role": "user", "content": (
            f"Write 2-3 sentences explaining how this {chunk_type} chunk "
            f"relates to the document above. Be specific and concise.\n\n"
            f"Chunk:\n{chunk_content[:500]}"
        )}]
    )
    prefix = response.content[0].text.strip()
    return f"{prefix}\n\n{chunk_content}"


# ============================================================
# BM25 index
# ============================================================

class BM25Index:
    """Lightweight BM25 index over a corpus of ContextChunks."""

    def __init__(self, chunks: list):
        self.chunks  = chunks
        corpus       = [c.content.lower().split() for c in chunks]
        self.index   = BM25Okapi(corpus)

    def query(
        self,
        query: str,
        top_k: int = 20,
    ) -> list[tuple[int, float]]:
        """Return [(chunk_index, bm25_score), ...] sorted by score descending."""
        tokens = query.lower().split()
        scores = self.index.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


# ============================================================
# Semantic search (stub — replace with real vector store)
# ============================================================

def semantic_search(
    query: str,
    chunks: list,
    top_k: int = 20,
) -> list[tuple[int, float]]:
    """
    Semantic search using Anthropic embeddings.
    STUB: In production, use Snowflake Cortex EMBED_TEXT_768() or
    a dedicated vector store (Pinecone, Weaviate, pgvector).
    Returns [(chunk_index, cosine_similarity), ...]
    """
    # STUB: replace with real embedding + cosine similarity
    # For illustration: return random rankings for demonstration
    import random
    ranked = [(i, random.random()) for i in range(len(chunks))]
    return sorted(ranked, key=lambda x: x[1], reverse=True)[:top_k]


# ============================================================
# Reciprocal Rank Fusion (RRF)
# ============================================================

def reciprocal_rank_fusion(
    bm25_results: list[tuple[int, float]],
    semantic_results: list[tuple[int, float]],
    k: int = 60,
) -> list[tuple[int, float]]:
    """
    Combine BM25 and semantic rankings using RRF.

    RRF score = sum(1 / (k + rank_in_list)) for each list.
    k=60 is the standard default from the original paper (Cormack et al., SIGIR 2009).
    """
    scores: dict[int, float] = {}

    for rank, (chunk_idx, _) in enumerate(bm25_results, start=1):
        scores[chunk_idx] = scores.get(chunk_idx, 0.0) + 1.0 / (k + rank)

    for rank, (chunk_idx, _) in enumerate(semantic_results, start=1):
        scores[chunk_idx] = scores.get(chunk_idx, 0.0) + 1.0 / (k + rank)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ============================================================
# Full hybrid retrieval pipeline
# ============================================================

def hybrid_retrieve(
    query: str,
    chunks: list,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """
    Retrieve top_k chunks using BM25 + semantic + RRF.

    Args:
        query:   The user's question or agent task
        chunks:  All available context chunks (pre-built index)
        top_k:   Number of chunks to return

    Returns:
        List of RetrievedChunk sorted by RRF score (best first)
    """
    bm25_idx   = BM25Index(chunks)
    bm25_res   = bm25_idx.query(query, top_k=20)
    sem_res    = semantic_search(query, chunks, top_k=20)

    fused      = reciprocal_rank_fusion(bm25_res, sem_res)

    results = []
    for chunk_idx, rrf_score in fused[:top_k]:
        c = chunks[chunk_idx]
        # Determine individual ranks for attribution
        bm25_rank = next((r for r, (i, _) in enumerate(bm25_res, 1) if i == chunk_idx), None)
        sem_rank  = next((r for r, (i, _) in enumerate(sem_res, 1)  if i == chunk_idx), None)
        results.append(RetrievedChunk(
            source=c.source,
            source_type=c.source_type,
            content=c.content,
            bm25_rank=bm25_rank,
            semantic_rank=sem_rank,
            rrf_score=rrf_score,
            token_estimate=c.token_estimate,
        ))
    return results


# ============================================================
# Snowflake Cortex Search integration
# Bug fix C5-1: OBJECT_CONSTRUCT, not ARRAY_CONSTRUCT for filters
# ============================================================

def cortex_search(
    conn,
    query: str,
    source_type_filter: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """
    Query Snowflake Cortex Search service.

    Bug fix C5-1: The filter parameter requires OBJECT_CONSTRUCT,
    not ARRAY_CONSTRUCT. Using ARRAY_CONSTRUCT raises a runtime error.

    Correct:   OBJECT_CONSTRUCT('source_type', %s)
    Wrong:     ARRAY_CONSTRUCT('source_type', %s)   <- runtime error
    """
    with conn.cursor() as cur:
        if source_type_filter:
            # CORRECT: OBJECT_CONSTRUCT for Cortex Search filters
            cur.execute("""
                SELECT * FROM TABLE(
                    SNOWFLAKE.CORTEX.SEARCH(
                        'opspu_context_index',
                        %s,
                        OBJECT_CONSTRUCT('source_type', %s),
                        %s
                    )
                )
            """, (query, source_type_filter, limit))
        else:
            cur.execute("""
                SELECT * FROM TABLE(
                    SNOWFLAKE.CORTEX.SEARCH('opspu_context_index', %s, NULL, %s)
                )
            """, (query, limit))
        return [dict(zip([d[0] for d in cur.description], row))
                for row in cur.fetchall()]
