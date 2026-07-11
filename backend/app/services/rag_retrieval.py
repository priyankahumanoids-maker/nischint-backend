"""
NISCHINT RAG Retrieval Service — Unified retrieval from blog chunks and safety knowledge.
Handles vector search, full-text fallback, and context merging.
"""
import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.embedding_service import is_available as embeddings_available

logger = logging.getLogger(__name__)


async def retrieve_blog_context(
    query: str, session: AsyncSession, top_k: int = 5, threshold: float = 0.25
) -> list[dict]:
    """Retrieve relevant blog chunks via vector or full-text search."""
    results = []

    if embeddings_available():
        try:
            from app.services.embedding_service import get_embedding
            emb = get_embedding(query)
            emb_str = "[" + ",".join(str(v) for v in emb) + "]"

            rows = await session.execute(text("""
                SELECT id, blog_id, title, chunk_text, metadata,
                       1 - (embedding <=> CAST(:emb AS vector)) AS similarity
                FROM blog_chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT :limit
            """), {"emb": emb_str, "limit": top_k})

            for row in rows.fetchall():
                score = float(row.similarity) if row.similarity else 0.0
                if score >= threshold:
                    results.append({
                        "source": "blog",
                        "blog_id": row.blog_id,
                        "title": row.title or "",
                        "text": row.chunk_text,
                        "score": round(score, 4),
                        "metadata": row.metadata if isinstance(row.metadata, dict) else {},
                    })
            if results:
                return results
        except Exception as e:
            logger.warning(f"Blog vector retrieval failed: {e}")

    # Full-text fallback
    try:
        rows = await session.execute(text("""
            SELECT id, blog_id, title, chunk_text, metadata,
                   ts_rank(to_tsvector('english', chunk_text), plainto_tsquery('english', :q)) AS rank
            FROM blog_chunks
            WHERE to_tsvector('english', chunk_text) @@ plainto_tsquery('english', :q)
            ORDER BY rank DESC
            LIMIT :limit
        """), {"q": query, "limit": top_k})

        for row in rows.fetchall():
            results.append({
                "source": "blog",
                "blog_id": row.blog_id,
                "title": row.title or "",
                "text": row.chunk_text,
                "score": round(float(row.rank), 4),
                "metadata": row.metadata if isinstance(row.metadata, dict) else {},
            })
    except Exception as e:
        logger.warning(f"Blog FTS retrieval failed: {e}")

    return results


async def retrieve_knowledge_context(
    query: str, session: AsyncSession, top_k: int = 5, threshold: float = 0.25
) -> list[dict]:
    """Retrieve relevant safety knowledge via vector or full-text search."""
    results = []

    if embeddings_available():
        try:
            from app.services.embedding_service import get_embedding
            emb = get_embedding(query)
            emb_str = "[" + ",".join(str(v) for v in emb) + "]"

            rows = await session.execute(text("""
                SELECT id, topic, category, content, metadata,
                       1 - (embedding <=> CAST(:emb AS vector)) AS similarity
                FROM safety_knowledge
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT :limit
            """), {"emb": emb_str, "limit": top_k})

            for row in rows.fetchall():
                score = float(row.similarity) if row.similarity else 0.0
                if score >= threshold:
                    results.append({
                        "source": "knowledge",
                        "topic": row.topic,
                        "category": row.category or "",
                        "text": row.content,
                        "score": round(score, 4),
                        "metadata": row.metadata if isinstance(row.metadata, dict) else {},
                    })
            if results:
                return results
        except Exception as e:
            logger.warning(f"Knowledge vector retrieval failed: {e}")

    # Full-text fallback
    try:
        rows = await session.execute(text("""
            SELECT id, topic, category, content, metadata,
                   ts_rank(to_tsvector('english', content), plainto_tsquery('english', :q)) AS rank
            FROM safety_knowledge
            WHERE to_tsvector('english', content) @@ plainto_tsquery('english', :q)
            ORDER BY rank DESC
            LIMIT :limit
        """), {"q": query, "limit": top_k})

        for row in rows.fetchall():
            results.append({
                "source": "knowledge",
                "topic": row.topic,
                "category": row.category or "",
                "text": row.content,
                "score": round(float(row.rank), 4),
                "metadata": row.metadata if isinstance(row.metadata, dict) else {},
            })
    except Exception as e:
        logger.warning(f"Knowledge FTS retrieval failed: {e}")

    return results


async def retrieve_merged_context(
    query: str, session: AsyncSession, blog_k: int = 5, knowledge_k: int = 3
) -> dict:
    """Merge blog + knowledge retrieval into a unified context for generation."""
    blog_results = await retrieve_blog_context(query, session, top_k=blog_k)
    knowledge_results = await retrieve_knowledge_context(query, session, top_k=knowledge_k)

    # Build internal links from blog results (unique by blog_id)
    seen_blog_ids = set()
    internal_links = []
    for r in blog_results:
        bid = r["blog_id"]
        if bid not in seen_blog_ids:
            seen_blog_ids.add(bid)
            slug = r.get("metadata", {}).get("slug", "")
            internal_links.append({
                "blog_id": bid,
                "title": r["title"],
                "slug": slug,
                "relevance_score": r["score"],
            })

    # Build context text for LLM
    context_parts = []
    for r in blog_results:
        context_parts.append(f"[Blog: {r['title']}]\n{r['text']}")
    for r in knowledge_results:
        context_parts.append(f"[Knowledge: {r['topic']}]\n{r['text']}")

    return {
        "blog_results": blog_results,
        "knowledge_results": knowledge_results,
        "internal_links": internal_links,
        "context_text": "\n\n---\n\n".join(context_parts),
        "total_sources": len(blog_results) + len(knowledge_results),
    }
