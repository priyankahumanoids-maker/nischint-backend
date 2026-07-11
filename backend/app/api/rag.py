"""
NISCHINT RAG System — Blog Storage, Search, Auto-Ingestion, Knowledge RAG, Content Generation.
Modular router separated from blog.py for clean architecture.
Uses pgvector for vector similarity search with full-text search fallback.
"""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.services.embedding_service import is_available as embeddings_available

logger = logging.getLogger(__name__)

# ── DLQ for blogs that were published but failed RAG indexing ─────
# Compensating action for the auto-publish chunk-ingest swallow
# below: the blog post is already live but missing from the RAG
# index — search will not surface it until reindexed. Push the
# minimum payload an offline reconciler needs to redrive the
# chunking + embedding + INSERT pipeline. Bounded for Redis memory
# safety during a sustained outage.
_RAG_REINDEX_DLQ_NAMESPACE = "dlq"
_RAG_REINDEX_DLQ_KEY = "rag_reindex"
_RAG_REINDEX_DLQ_MAX = 500


def _push_rag_reindex_dlq(payload: dict) -> bool:
    """LPUSH a `(post_id, title, query)` payload to a bounded Redis
    list so an offline reconciler can re-chunk and re-embed the
    published blog. Returns True on enqueue, False on Redis-
    unavailable. Caller has already emitted a WARNING log — the
    blog is live, the index is stale, that's the operator signal."""
    try:
        from app.services.redis_service import _get_client
        c = _get_client()
        if not c:
            return False
        full_key = f"{_RAG_REINDEX_DLQ_NAMESPACE}:{_RAG_REINDEX_DLQ_KEY}"
        c.lpush(full_key, json.dumps(payload, default=str))
        c.ltrim(full_key, 0, _RAG_REINDEX_DLQ_MAX - 1)
        return True
    except Exception as e:  # noqa: BLE001 — best-effort DLQ
        logger.debug("rag_reindex DLQ push skipped: %r", e)
        return False

# ── Routers ──
rag_router = APIRouter(prefix="/rag", tags=["RAG"])
blog_rag_router = APIRouter(prefix="/blog", tags=["Blog RAG"])
knowledge_router = APIRouter(prefix="/knowledge", tags=["Knowledge RAG"])

# ── State ──
_pgvector_available: Optional[bool] = None
_tables_ready = False

CHUNK_SIZE = 1500  # chars per chunk (~375 tokens)
CHUNK_OVERLAP = 200  # overlap between chunks


# ── Schema ──

SCHEMA_SQL_PGVECTOR = [
    "CREATE EXTENSION IF NOT EXISTS vector;",
    """CREATE TABLE IF NOT EXISTS blog_chunks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        blog_id TEXT NOT NULL,
        title TEXT,
        content TEXT,
        chunk_text TEXT NOT NULL,
        chunk_index INT DEFAULT 0,
        embedding VECTOR(1536),
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT NOW()
    );""",
    """CREATE INDEX IF NOT EXISTS idx_blog_chunks_blog_id
       ON blog_chunks(blog_id);""",
    """CREATE INDEX IF NOT EXISTS idx_blog_chunks_fts
       ON blog_chunks USING GIN (to_tsvector('english', chunk_text));""",
    """CREATE TABLE IF NOT EXISTS safety_knowledge (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        topic TEXT NOT NULL,
        category TEXT,
        content TEXT NOT NULL,
        embedding VECTOR(1536),
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT NOW()
    );""",
    """CREATE INDEX IF NOT EXISTS idx_safety_knowledge_category
       ON safety_knowledge(category);""",
    """CREATE INDEX IF NOT EXISTS idx_safety_knowledge_fts
       ON safety_knowledge USING GIN (to_tsvector('english', content));""",
]

SCHEMA_SQL_FALLBACK = [
    """CREATE TABLE IF NOT EXISTS blog_chunks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        blog_id TEXT NOT NULL,
        title TEXT,
        content TEXT,
        chunk_text TEXT NOT NULL,
        chunk_index INT DEFAULT 0,
        embedding TEXT,
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT NOW()
    );""",
    """CREATE INDEX IF NOT EXISTS idx_blog_chunks_blog_id
       ON blog_chunks(blog_id);""",
    """CREATE INDEX IF NOT EXISTS idx_blog_chunks_fts
       ON blog_chunks USING GIN (to_tsvector('english', chunk_text));""",
    """CREATE TABLE IF NOT EXISTS safety_knowledge (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        topic TEXT NOT NULL,
        category TEXT,
        content TEXT NOT NULL,
        embedding TEXT,
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT NOW()
    );""",
    """CREATE INDEX IF NOT EXISTS idx_safety_knowledge_category
       ON safety_knowledge(category);""",
    """CREATE INDEX IF NOT EXISTS idx_safety_knowledge_fts
       ON safety_knowledge USING GIN (to_tsvector('english', content));""",
]


async def _detect_pgvector(session: AsyncSession) -> bool:
    global _pgvector_available
    if _pgvector_available is not None:
        return _pgvector_available
    try:
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await session.commit()
        _pgvector_available = True
        logger.info("pgvector extension detected and enabled")
    except SQLAlchemyError:
        # Compensating action: `_pgvector_available = False` flips the
        # caller into the full-text-search fallback path. This is a
        # one-shot bootstrap probe — narrow type so a non-DB exception
        # (coding bug) still propagates.
        await session.rollback()
        _pgvector_available = False
        logger.warning("pgvector not available — falling back to full-text search")
    return _pgvector_available


async def ensure_rag_tables(session: AsyncSession):
    global _tables_ready
    if _tables_ready:
        return
    has_vector = await _detect_pgvector(session)
    schema = SCHEMA_SQL_PGVECTOR if has_vector else SCHEMA_SQL_FALLBACK
    for sql in schema:
        try:
            await session.execute(text(sql))
        except Exception as e:
            logger.warning(f"Schema statement skipped: {e}")
            await session.rollback()
    await session.commit()

    # Create ivfflat index if pgvector and enough rows
    if has_vector:
        try:
            count = await session.execute(text("SELECT COUNT(*) FROM blog_chunks"))
            row_count = count.scalar() or 0
            if row_count >= 100:
                await session.execute(text(
                    """CREATE INDEX IF NOT EXISTS idx_blog_chunks_embedding
                       ON blog_chunks USING ivfflat (embedding vector_cosine_ops)
                       WITH (lists = 100);"""
                ))
                await session.commit()
                logger.info("IVFFlat index created on blog_chunks.embedding")
        except SQLAlchemyError as e:
            # Compensating action: IVFFlat is a search-speed
            # optimization, not correctness — absent index only makes
            # similarity search slower. Narrow type so a coding bug
            # still propagates.
            logger.warning(f"IVFFlat index creation skipped: {e}")
            await session.rollback()

    _tables_ready = True
    logger.info("RAG tables initialized")


# ── Chunking ──

def _clean_html(html: str) -> str:
    """Strip HTML tags for clean text chunking."""
    clean = re.sub(r'<[^>]+>', ' ', html)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def chunk_text(content: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks at sentence boundaries."""
    clean = _clean_html(content)
    if len(clean) <= chunk_size:
        return [clean] if clean else []

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', clean)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 > chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            # Overlap: keep the tail of the current chunk
            overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
            current_chunk = overlap_text + " " + sentence
        else:
            current_chunk = (current_chunk + " " + sentence).strip()

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


# ── Pydantic Models ──

class IngestRequest(BaseModel):
    blog_id: Optional[str] = None
    title: Optional[str] = None
    content: str
    metadata: Optional[dict] = None


class IngestResponse(BaseModel):
    blog_id: str
    chunks_created: int
    embeddings_generated: bool
    message: str


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    threshold: float = 0.3


class SearchResult(BaseModel):
    chunk_id: str
    blog_id: str
    title: Optional[str]
    chunk_text: str
    score: float
    metadata: Optional[dict]


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    search_method: str
    total_results: int


class AutoIngestResponse(BaseModel):
    total_blogs: int
    ingested: int
    skipped: int
    errors: int
    details: list[dict]


class HealthResponse(BaseModel):
    status: str
    pgvector: bool
    embeddings_configured: bool
    total_chunks: int
    total_blogs_indexed: int
    total_knowledge_entries: int
    total_insights: int
    embedding_model: str


# ── Endpoints ──

@rag_router.get("/health", response_model=HealthResponse)
async def rag_health(session: AsyncSession = Depends(get_db_session)):
    """RAG system health check — reports pgvector status, embedding config, and chunk counts."""
    await ensure_rag_tables(session)

    has_vector = _pgvector_available or False
    has_embeddings = embeddings_available()

    total_chunks = 0
    total_blogs = 0
    total_knowledge = 0
    total_insights = 0
    try:
        result = await session.execute(text("SELECT COUNT(*) FROM blog_chunks"))
        total_chunks = result.scalar() or 0
        result2 = await session.execute(text("SELECT COUNT(DISTINCT blog_id) FROM blog_chunks"))
        total_blogs = result2.scalar() or 0
        result3 = await session.execute(text("SELECT COUNT(*) FROM safety_knowledge"))
        total_knowledge = result3.scalar() or 0
        result4 = await session.execute(text("SELECT COUNT(*) FROM rag_insights"))
        total_insights = result4.scalar() or 0
    except Exception:
        pass

    status = "operational" if (has_vector and has_embeddings) else "degraded"
    from app.core.config import settings as app_settings

    return HealthResponse(
        status=status,
        pgvector=has_vector,
        embeddings_configured=has_embeddings,
        total_chunks=total_chunks,
        total_blogs_indexed=total_blogs,
        total_knowledge_entries=total_knowledge,
        total_insights=total_insights,
        embedding_model=app_settings.embedding_model,
    )


@blog_rag_router.post("/ingest", response_model=IngestResponse)
async def ingest_blog(req: IngestRequest, session: AsyncSession = Depends(get_db_session)):
    """Ingest a blog post: chunk content, generate embeddings, store in blog_chunks."""
    await ensure_rag_tables(session)

    blog_id = req.blog_id or str(uuid.uuid4())
    chunks = chunk_text(req.content)
    if not chunks:
        raise HTTPException(status_code=400, detail="No content to ingest after cleaning")

    # Delete existing chunks for this blog_id (re-ingest)
    await session.execute(text("DELETE FROM blog_chunks WHERE blog_id = :bid"), {"bid": blog_id})

    embeddings_ok = False
    embeddings = []

    if embeddings_available():
        try:
            from app.services.embedding_service import get_embeddings_batch
            embeddings = get_embeddings_batch(chunks)
            embeddings_ok = True
        except Exception as e:
            logger.error(f"Embedding generation failed for blog {blog_id}: {e}")

    for i, chunk in enumerate(chunks):
        chunk_id = str(uuid.uuid4())
        meta = req.metadata or {}
        meta["chunk_index"] = i
        meta["total_chunks"] = len(chunks)

        if embeddings_ok and i < len(embeddings) and _pgvector_available:
            emb_str = "[" + ",".join(str(v) for v in embeddings[i]) + "]"
            await session.execute(text("""
                INSERT INTO blog_chunks (id, blog_id, title, content, chunk_text, chunk_index, embedding, metadata)
                VALUES (:id, :blog_id, :title, :content, :chunk_text, :chunk_index,
                        CAST(:embedding AS vector), CAST(:metadata AS jsonb))
            """), {
                "id": chunk_id, "blog_id": blog_id, "title": req.title,
                "content": req.content[:500], "chunk_text": chunk,
                "chunk_index": i, "embedding": emb_str,
                "metadata": __import__("json").dumps(meta),
            })
        else:
            await session.execute(text("""
                INSERT INTO blog_chunks (id, blog_id, title, content, chunk_text, chunk_index, metadata)
                VALUES (:id, :blog_id, :title, :content, :chunk_text, :chunk_index,
                        CAST(:metadata AS jsonb))
            """), {
                "id": chunk_id, "blog_id": blog_id, "title": req.title,
                "content": req.content[:500], "chunk_text": chunk,
                "chunk_index": i, "metadata": __import__("json").dumps(meta),
            })

    await session.commit()
    logger.info(f"Ingested blog {blog_id}: {len(chunks)} chunks, embeddings={embeddings_ok}")

    return IngestResponse(
        blog_id=blog_id,
        chunks_created=len(chunks),
        embeddings_generated=embeddings_ok,
        message=f"Successfully ingested {len(chunks)} chunks"
        + (" with embeddings" if embeddings_ok else " (text-only, no embeddings)"),
    )


@blog_rag_router.post("/search", response_model=SearchResponse)
async def search_blog(req: SearchRequest, session: AsyncSession = Depends(get_db_session)):
    """Search blog chunks using vector similarity (pgvector) or full-text search fallback."""
    await ensure_rag_tables(session)

    results = []
    search_method = "none"

    # Strategy 1: Vector similarity search (if pgvector + embeddings available)
    if _pgvector_available and embeddings_available():
        try:
            from app.services.embedding_service import get_embedding
            query_embedding = get_embedding(req.query)
            emb_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

            rows = await session.execute(text("""
                SELECT id, blog_id, title, chunk_text, metadata,
                       1 - (embedding <=> CAST(:emb AS vector)) AS similarity
                FROM blog_chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT :limit
            """), {"emb": emb_str, "limit": req.top_k})

            for row in rows.fetchall():
                score = float(row.similarity) if row.similarity else 0.0
                if score >= req.threshold:
                    results.append(SearchResult(
                        chunk_id=str(row.id),
                        blog_id=row.blog_id,
                        title=row.title,
                        chunk_text=row.chunk_text,
                        score=round(score, 4),
                        metadata=row.metadata if isinstance(row.metadata, dict) else {},
                    ))
            search_method = "vector_cosine"
            logger.info(f"Vector search for '{req.query[:50]}': {len(results)} results")
        except Exception as e:
            logger.error(f"Vector search failed, falling back to FTS: {e}")
            results = []

    # Strategy 2: Full-text search fallback
    if not results:
        try:
            rows = await session.execute(text("""
                SELECT id, blog_id, title, chunk_text, metadata,
                       ts_rank(to_tsvector('english', chunk_text), plainto_tsquery('english', :query)) AS rank
                FROM blog_chunks
                WHERE to_tsvector('english', chunk_text) @@ plainto_tsquery('english', :query)
                ORDER BY rank DESC
                LIMIT :limit
            """), {"query": req.query, "limit": req.top_k})

            for row in rows.fetchall():
                results.append(SearchResult(
                    chunk_id=str(row.id),
                    blog_id=row.blog_id,
                    title=row.title,
                    chunk_text=row.chunk_text,
                    score=round(float(row.rank), 4),
                    metadata=row.metadata if isinstance(row.metadata, dict) else {},
                ))
            search_method = "full_text"
            logger.info(f"FTS search for '{req.query[:50]}': {len(results)} results")
        except Exception as e:
            logger.error(f"Full-text search also failed: {e}")
            search_method = "error"

    return SearchResponse(
        query=req.query,
        results=results,
        search_method=search_method,
        total_results=len(results),
    )


@blog_rag_router.post("/auto-ingest", response_model=AutoIngestResponse)
async def auto_ingest(session: AsyncSession = Depends(get_db_session)):
    """Pull all published blog posts, chunk, embed, and store. Idempotent (re-ingests all)."""
    await ensure_rag_tables(session)

    # Fetch all published blogs
    rows = await session.execute(text(
        "SELECT id, title, slug, content FROM blog_posts WHERE status = 'published'"
    ))
    blogs = rows.fetchall()

    details = []
    ingested = 0
    skipped = 0
    errors = 0

    for blog in blogs:
        blog_id = str(blog.id)
        title = blog.title or ""
        content = blog.content or ""

        if not content.strip():
            skipped += 1
            details.append({"blog_id": blog_id, "title": title, "status": "skipped", "reason": "empty content"})
            continue

        try:
            chunks = chunk_text(content)
            if not chunks:
                skipped += 1
                details.append({"blog_id": blog_id, "title": title, "status": "skipped", "reason": "no chunks after cleaning"})
                continue

            # Delete old chunks
            await session.execute(text("DELETE FROM blog_chunks WHERE blog_id = :bid"), {"bid": blog_id})

            embeddings = []
            embeddings_ok = False
            if embeddings_available():
                try:
                    from app.services.embedding_service import get_embeddings_batch
                    embeddings = get_embeddings_batch(chunks)
                    embeddings_ok = True
                except Exception as e:
                    logger.warning(f"Embedding failed for blog {blog_id}: {e}")

            for i, chunk in enumerate(chunks):
                chunk_id = str(uuid.uuid4())
                meta = {"chunk_index": i, "total_chunks": len(chunks), "slug": blog.slug}
                import json as json_mod

                if embeddings_ok and i < len(embeddings) and _pgvector_available:
                    emb_str = "[" + ",".join(str(v) for v in embeddings[i]) + "]"
                    await session.execute(text("""
                        INSERT INTO blog_chunks (id, blog_id, title, content, chunk_text, chunk_index, embedding, metadata)
                        VALUES (:id, :bid, :title, :content, :chunk, :ci,
                                CAST(:emb AS vector), CAST(:meta AS jsonb))
                    """), {
                        "id": chunk_id, "bid": blog_id, "title": title,
                        "content": content[:500], "chunk": chunk,
                        "ci": i, "emb": emb_str, "meta": json_mod.dumps(meta),
                    })
                else:
                    await session.execute(text("""
                        INSERT INTO blog_chunks (id, blog_id, title, content, chunk_text, chunk_index, metadata)
                        VALUES (:id, :bid, :title, :content, :chunk, :ci,
                                CAST(:meta AS jsonb))
                    """), {
                        "id": chunk_id, "bid": blog_id, "title": title,
                        "content": content[:500], "chunk": chunk,
                        "ci": i, "meta": json_mod.dumps(meta),
                    })

            await session.commit()
            ingested += 1
            details.append({
                "blog_id": blog_id, "title": title, "status": "ingested",
                "chunks": len(chunks), "embeddings": embeddings_ok,
            })
            logger.info(f"Auto-ingested blog '{title}': {len(chunks)} chunks")

        except (SQLAlchemyError, ValueError, KeyError) as e:
            # Compensating action: the per-blog failure is collected
            # into the `details` array returned to the caller (line 519
            # below) — the caller knows exactly which blogs failed and
            # why. Narrow types cover DB errors + malformed input;
            # everything else propagates.
            errors += 1
            details.append({"blog_id": blog_id, "title": title, "status": "error", "reason": str(e)[:200]})
            logger.error(f"Auto-ingest error for blog {blog_id}: {e}")
            await session.rollback()

    return AutoIngestResponse(
        total_blogs=len(blogs),
        ingested=ingested,
        skipped=skipped,
        errors=errors,
        details=details,
    )


# ══════════════════════════════════════════════════════════════════════
# BLOCK 2: Knowledge RAG + Content Generation Engine
# ══════════════════════════════════════════════════════════════════════

# ── Knowledge Models ──

class KnowledgeIngestRequest(BaseModel):
    topic: str
    category: Optional[str] = None
    content: str
    metadata: Optional[dict] = None


class KnowledgeIngestResponse(BaseModel):
    id: str
    topic: str
    embedding_generated: bool
    message: str


class KnowledgeBatchIngestRequest(BaseModel):
    entries: list[KnowledgeIngestRequest]


class KnowledgeBatchIngestResponse(BaseModel):
    total: int
    ingested: int
    errors: int
    details: list[dict]


class KnowledgeSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    category: Optional[str] = None
    threshold: float = 0.25


class KnowledgeSearchResult(BaseModel):
    id: str
    topic: str
    category: Optional[str]
    content: str
    score: float
    metadata: Optional[dict]


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[KnowledgeSearchResult]
    search_method: str
    total_results: int


class GenerateRequest(BaseModel):
    query: str
    persona: str = "parent"
    emotion: str = "concern"
    location: str = "India"


class GenerateResponse(BaseModel):
    title: str
    hook: str
    sections: list[dict]
    cta: str
    internal_links: list[dict]
    seo: dict
    intent_analysis: Optional[dict] = None
    rag_context: dict


# ── Knowledge Endpoints ──

@knowledge_router.post("/ingest", response_model=KnowledgeIngestResponse)
async def ingest_knowledge(req: KnowledgeIngestRequest, session: AsyncSession = Depends(get_db_session)):
    """Ingest a single safety knowledge entry with embedding."""
    await ensure_rag_tables(session)

    entry_id = str(uuid.uuid4())
    meta = req.metadata or {}
    embedding_ok = False

    if embeddings_available() and _pgvector_available:
        try:
            from app.services.embedding_service import get_embedding
            emb = get_embedding(req.content)
            emb_str = "[" + ",".join(str(v) for v in emb) + "]"
            await session.execute(text("""
                INSERT INTO safety_knowledge (id, topic, category, content, embedding, metadata)
                VALUES (:id, :topic, :cat, :content, CAST(:emb AS vector), CAST(:meta AS jsonb))
            """), {
                "id": entry_id, "topic": req.topic, "cat": req.category,
                "content": req.content, "emb": emb_str, "meta": json.dumps(meta),
            })
            embedding_ok = True
        except Exception as e:
            logger.error(f"Knowledge embedding failed: {e}")
            await session.rollback()

    if not embedding_ok:
        await session.execute(text("""
            INSERT INTO safety_knowledge (id, topic, category, content, metadata)
            VALUES (:id, :topic, :cat, :content, CAST(:meta AS jsonb))
        """), {
            "id": entry_id, "topic": req.topic, "cat": req.category,
            "content": req.content, "meta": json.dumps(meta),
        })

    await session.commit()
    return KnowledgeIngestResponse(
        id=entry_id, topic=req.topic, embedding_generated=embedding_ok,
        message=f"Knowledge entry '{req.topic}' stored" + (" with embedding" if embedding_ok else ""),
    )


@knowledge_router.post("/batch-ingest", response_model=KnowledgeBatchIngestResponse)
async def batch_ingest_knowledge(req: KnowledgeBatchIngestRequest, session: AsyncSession = Depends(get_db_session)):
    """Batch ingest multiple safety knowledge entries."""
    await ensure_rag_tables(session)

    details = []
    ingested = 0
    errors = 0

    for entry in req.entries:
        try:
            entry_id = str(uuid.uuid4())
            meta = entry.metadata or {}
            embedding_ok = False

            if embeddings_available() and _pgvector_available:
                try:
                    from app.services.embedding_service import get_embedding
                    emb = get_embedding(entry.content)
                    emb_str = "[" + ",".join(str(v) for v in emb) + "]"
                    await session.execute(text("""
                        INSERT INTO safety_knowledge (id, topic, category, content, embedding, metadata)
                        VALUES (:id, :topic, :cat, :content, CAST(:emb AS vector), CAST(:meta AS jsonb))
                    """), {
                        "id": entry_id, "topic": entry.topic, "cat": entry.category,
                        "content": entry.content, "emb": emb_str, "meta": json.dumps(meta),
                    })
                    embedding_ok = True
                except Exception as e:
                    logger.warning(f"Embedding failed for '{entry.topic}': {e}")
                    await session.rollback()

            if not embedding_ok:
                await session.execute(text("""
                    INSERT INTO safety_knowledge (id, topic, category, content, metadata)
                    VALUES (:id, :topic, :cat, :content, CAST(:meta AS jsonb))
                """), {
                    "id": entry_id, "topic": entry.topic, "cat": entry.category,
                    "content": entry.content, "meta": json.dumps(meta),
                })

            await session.commit()
            ingested += 1
            details.append({"topic": entry.topic, "status": "ingested", "embedding": embedding_ok})
        except (SQLAlchemyError, ValueError, KeyError) as e:
            # Compensating action (mirrors :508): per-entry failure
            # is collected into the response `details` array — caller
            # knows exactly which entries failed and why.
            errors += 1
            details.append({"topic": entry.topic, "status": "error", "reason": str(e)[:200]})
            await session.rollback()

    return KnowledgeBatchIngestResponse(
        total=len(req.entries), ingested=ingested, errors=errors, details=details,
    )


@knowledge_router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(req: KnowledgeSearchRequest, session: AsyncSession = Depends(get_db_session)):
    """Search safety knowledge via vector similarity or full-text search."""
    await ensure_rag_tables(session)

    results = []
    search_method = "none"
    category_filter = ""
    params: dict = {"q": req.query, "limit": req.top_k}

    if req.category:
        category_filter = "AND category = :cat"
        params["cat"] = req.category

    # Vector search
    if _pgvector_available and embeddings_available():
        try:
            from app.services.embedding_service import get_embedding
            emb = get_embedding(req.query)
            emb_str = "[" + ",".join(str(v) for v in emb) + "]"
            params["emb"] = emb_str

            rows = await session.execute(text(f"""
                SELECT id, topic, category, content, metadata,
                       1 - (embedding <=> CAST(:emb AS vector)) AS similarity
                FROM safety_knowledge
                WHERE embedding IS NOT NULL {category_filter}
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT :limit
            """), params)

            for row in rows.fetchall():
                score = float(row.similarity) if row.similarity else 0.0
                if score >= req.threshold:
                    results.append(KnowledgeSearchResult(
                        id=str(row.id), topic=row.topic, category=row.category,
                        content=row.content, score=round(score, 4),
                        metadata=row.metadata if isinstance(row.metadata, dict) else {},
                    ))
            search_method = "vector_cosine"
            if results:
                return KnowledgeSearchResponse(
                    query=req.query, results=results,
                    search_method=search_method, total_results=len(results),
                )
        except Exception as e:
            logger.warning(f"Knowledge vector search failed: {e}")

    # Full-text fallback
    try:
        rows = await session.execute(text(f"""
            SELECT id, topic, category, content, metadata,
                   ts_rank(to_tsvector('english', content), plainto_tsquery('english', :q)) AS rank
            FROM safety_knowledge
            WHERE to_tsvector('english', content) @@ plainto_tsquery('english', :q) {category_filter}
            ORDER BY rank DESC
            LIMIT :limit
        """), params)

        for row in rows.fetchall():
            results.append(KnowledgeSearchResult(
                id=str(row.id), topic=row.topic, category=row.category,
                content=row.content, score=round(float(row.rank), 4),
                metadata=row.metadata if isinstance(row.metadata, dict) else {},
            ))
        search_method = "full_text"
    except Exception as e:
        logger.error(f"Knowledge FTS failed: {e}")
        search_method = "error"

    return KnowledgeSearchResponse(
        query=req.query, results=results,
        search_method=search_method, total_results=len(results),
    )


# ── Content Generation Engine ──

@rag_router.post("/generate", response_model=GenerateResponse)
async def generate_content(req: GenerateRequest, session: AsyncSession = Depends(get_db_session)):
    """RAG Decision + Content Engine. Retrieves context from blog + knowledge, generates structured content."""
    await ensure_rag_tables(session)

    # Step 1: Retrieve merged context (extra blog_k for internal link diversity)
    from app.services.rag_retrieval import retrieve_merged_context, retrieve_blog_context
    context = await retrieve_merged_context(req.query, session, blog_k=10, knowledge_k=3)

    # Supplement internal links with a broader title-level search
    if len(context["internal_links"]) < 5:
        try:
            broader = await retrieve_blog_context(req.query, session, top_k=15, threshold=0.15)
            seen = {lnk["blog_id"] for lnk in context["internal_links"]}
            for r in broader:
                if r["blog_id"] not in seen:
                    seen.add(r["blog_id"])
                    slug = r.get("metadata", {}).get("slug", "")
                    if slug:
                        context["internal_links"].append({
                            "blog_id": r["blog_id"],
                            "title": r["title"],
                            "slug": slug,
                            "relevance_score": r["score"],
                        })
                if len(context["internal_links"]) >= 5:
                    break
        except SQLAlchemyError as e:
            # Compensating action: enrichment fallback is purely
            # additive — primary search already returned, so a broader-
            # link miss just means fewer internal-link suggestions.
            # Narrow to DB errors; coding bugs propagate.
            logger.warning(f"Broader link search failed: {e}")

    if context["total_sources"] == 0:
        logger.warning(f"No RAG context found for query: {req.query}")

    # Step 2: Generate structured content
    from app.services.rag_generation import generate_structured_content
    try:
        result = await generate_structured_content(
            query=req.query,
            persona=req.persona,
            emotion=req.emotion,
            location=req.location,
            context_text=context["context_text"],
            internal_links=context["internal_links"],
        )
    except asyncio.TimeoutError:
        # Generation exceeded the outer timeout — return a deferred-
        # retry payload instead of a hard 500. Aligns with the
        # DLQ-architecture's "compensating action exists" philosophy:
        # the front door never hangs, the caller can retry safely.
        raise HTTPException(
            status_code=503,
            detail={
                "status":    "deferred",
                "retryable": True,
                "reason":    "rag_generation_timeout",
            },
        )

    if result is None:
        raise HTTPException(status_code=500, detail="Content generation failed — invalid response from LLM")

    # Step 3: Build dynamic internal links directly from RAG search results
    # (more reliable than relying on LLM to reference blog_ids correctly)
    seen_slugs = set()
    enriched_links = []
    for lnk in context["internal_links"][:5]:
        slug = lnk.get("slug", "")
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        enriched_links.append({
            "slug": slug,
            "title": lnk.get("title", ""),
            "anchor": lnk.get("title", ""),
            "relevance_score": lnk.get("relevance_score", 0),
        })

    # Supplement with LLM-suggested anchors if they match a known slug
    llm_links = result.get("internal_links", [])
    link_map = {lnk.get("slug", ""): lnk for lnk in enriched_links if lnk.get("slug")}
    for gl in llm_links:
        anchor = gl.get("anchor", "")
        bid = gl.get("blog_id", "")
        # Match by blog_id from context
        for ctx_lnk in context["internal_links"]:
            if ctx_lnk["blog_id"] == bid and ctx_lnk.get("slug") in link_map and anchor:
                link_map[ctx_lnk["slug"]]["anchor"] = anchor
                break

    # Step 4: Log insight (fire-and-forget, don't block response)
    try:
        from app.services.rag_insight_service import log_insight
        generated_slug = result.get("seo", {}).get("meta_title", "").lower().replace(" ", "-")[:80]
        await log_insight(session, {
            "event_type": "blog_generated",
            "query": req.query,
            "persona": req.persona,
            "emotion": req.emotion,
            "blog_slug": generated_slug,
            "source": "blog",
            "metadata": {
                "title": result.get("title", ""),
                "sections_count": len(result.get("sections", [])),
                "internal_links_count": len(enriched_links),
                "rag_sources": context["total_sources"],
            },
        })
    except Exception as e:
        logger.warning(f"Insight logging failed (non-blocking): {e}")

    return GenerateResponse(
        title=result.get("title", ""),
        hook=result.get("hook", ""),
        sections=result.get("sections", []),
        cta=result.get("cta", ""),
        internal_links=enriched_links,
        seo=result.get("seo", {}),
        intent_analysis=result.get("intent_analysis"),
        rag_context={
            "blog_sources": len(context["blog_results"]),
            "knowledge_sources": len(context["knowledge_results"]),
            "total_sources": context["total_sources"],
        },
    )

# ══════════════════════════════════════════════════════════════════════
# BLOCK 3: RAG Insights Tracking System
# ══════════════════════════════════════════════════════════════════════

class InsightRequest(BaseModel):
    event_type: str  # blog_generated / cta_clicked / lead_created
    query: Optional[str] = None
    persona: Optional[str] = None
    emotion: Optional[str] = None
    blog_id: Optional[str] = None
    blog_slug: Optional[str] = None
    lead_id: Optional[str] = None
    conversion: bool = False
    score: Optional[int] = None
    priority: Optional[str] = None
    source: Optional[str] = None
    metadata: Optional[dict] = None


class InsightResponse(BaseModel):
    id: str
    event_type: str
    message: str


class InsightsListResponse(BaseModel):
    total: int
    results: list[dict]
    limit: int
    offset: int


class TopQueriesResponse(BaseModel):
    queries: list[dict]


@rag_router.post("/insight", response_model=InsightResponse)
async def log_rag_insight(req: InsightRequest, session: AsyncSession = Depends(get_db_session)):
    """Log a RAG lifecycle event (blog_generated, cta_clicked, lead_created)."""
    from app.services.rag_insight_service import log_insight

    insight_id = await log_insight(session, req.model_dump())
    return InsightResponse(id=insight_id, event_type=req.event_type, message="Insight logged")


@rag_router.get("/insights", response_model=InsightsListResponse)
async def get_rag_insights(
    event_type: Optional[str] = None,
    query: Optional[str] = None,
    blog_slug: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
):
    """Retrieve RAG insights with optional filters."""
    from app.services.rag_insight_service import get_insights

    data = await get_insights(
        session, event_type=event_type, query=query,
        blog_slug=blog_slug, source=source, limit=limit, offset=offset,
    )
    return InsightsListResponse(**data)


@rag_router.get("/insights/top-queries", response_model=TopQueriesResponse)
async def get_top_queries(
    limit: int = 10,
    session: AsyncSession = Depends(get_db_session),
):
    """Get top performing queries ranked by conversion funnel progression."""
    from app.services.rag_insight_service import get_top_performing_queries

    queries = await get_top_performing_queries(session, limit=limit)
    return TopQueriesResponse(queries=queries)


# ══════════════════════════════════════════════════════════════════════
# AUTO BLOG MACHINE — Unified Pipeline Endpoint
# ══════════════════════════════════════════════════════════════════════

class AutoPublishIntent(BaseModel):
    query: str
    persona: str = "parent"
    emotion: str = "concern"
    location: str = "India"
    category: Optional[str] = "awareness"
    auto_publish: bool = True


class AutoPublishBatchRequest(BaseModel):
    intents: list[AutoPublishIntent] = []
    use_top_queries: bool = False
    max_intents: int = 3


class AutoPublishResult(BaseModel):
    query: str
    status: str  # success / error
    blog_id: Optional[str] = None
    slug: Optional[str] = None
    url: Optional[str] = None
    chunks_ingested: Optional[int] = None
    error: Optional[str] = None


class AutoPublishBatchResponse(BaseModel):
    total: int
    published: int
    errors: int
    results: list[AutoPublishResult]


async def _run_single_pipeline(
    intent: AutoPublishIntent, session: AsyncSession
) -> AutoPublishResult:
    """Execute the full pipeline for a single intent: Generate → Create → Ingest → Track."""
    import json as json_mod

    try:
        # Step 1: RAG Generate
        from app.services.rag_retrieval import retrieve_merged_context
        from app.services.rag_generation import generate_structured_content

        context = await retrieve_merged_context(intent.query, session, blog_k=5, knowledge_k=3)

        try:
            generated = await generate_structured_content(
                query=intent.query,
                persona=intent.persona,
                emotion=intent.emotion,
                location=intent.location,
                context_text=context["context_text"],
                internal_links=context["internal_links"],
            )
        except asyncio.TimeoutError:
            # Auto-publish is a background cron path — surface the
            # deferred state in the result so the caller retries
            # against its own schedule. No CF edge to placate here.
            return AutoPublishResult(
                query=intent.query, status="deferred",
                error="rag_generation_timeout",
            )
        except Exception as gen_err:
            return AutoPublishResult(query=intent.query, status="error", error=f"Generation failed: {gen_err}")

        if generated is None:
            return AutoPublishResult(query=intent.query, status="error", error="LLM generation returned null")

        title = generated.get("title", intent.query) if isinstance(generated, dict) else intent.query
        seo = generated.get("seo", {}) if isinstance(generated, dict) else {}
        if isinstance(seo, str):
            seo = {}
        sections = generated.get("sections", []) if isinstance(generated, dict) else []

        # Step 2: Format blog HTML from structured output
        section_html = []
        for s in sections:
            if isinstance(s, dict):
                heading = s.get("heading", s.get("type", ""))
                content = s.get("content", "")
            else:
                heading = ""
                content = str(s)
            section_html.append(f"<h2>{heading}</h2>\n<p>{content}</p>")

        blog_content = f"""<h1>{title}</h1>
<p>{generated.get('hook', '') if isinstance(generated, dict) else ''}</p>

{''.join(section_html)}

<p><strong>{generated.get('cta', '') if isinstance(generated, dict) else ''}</strong></p>"""

        hook_text = generated.get("hook", "") if isinstance(generated, dict) else ""

        # Step 3: Create blog post via internal DB insert (bypass HTTP overhead)
        from app.api.blog import slugify
        base_slug = slugify(title)
        slug = base_slug
        counter = 1
        while True:
            dup = await session.execute(text("SELECT id FROM blog_posts WHERE slug = :s LIMIT 1"), {"s": slug})
            if not dup.fetchone():
                break
            counter += 1
            slug = f"{base_slug}-{counter}"

        post_id = str(uuid.uuid4())
        from datetime import datetime as dt
        now = dt.now(timezone.utc)
        blog_status = "published" if intent.auto_publish else "draft"
        published_at = now if blog_status == "published" else None

        # Build schema
        from app.api.blog import build_schema, BASE_URL
        try:
            schema_json = build_schema({
                "title": title, "slug": slug, "content": blog_content,
                "excerpt": hook_text[:300],
                "meta_title": seo.get("meta_title", title)[:60] if isinstance(seo, dict) else title[:60],
                "meta_description": seo.get("meta_description", "")[:160] if isinstance(seo, dict) else "",
                "id": post_id, "author": "NISCHINT AI",
                "published_at": published_at.isoformat() if published_at else "",
                "updated_at": now.isoformat(),
            })
        except Exception as schema_err:
            logger.warning(f"Schema build failed (non-critical): {schema_err}")
            schema_json = []

        keywords_str = ", ".join(seo.get("keywords", [])) if isinstance(seo, dict) and isinstance(seo.get("keywords"), list) else ""

        await session.execute(text("""
            INSERT INTO blog_posts (
                id, title, slug, content, excerpt,
                meta_title, meta_description, keywords, category,
                author, faq_json, schema_json,
                status, views, published_at, created_at, updated_at
            ) VALUES (
                :id, :title, :slug, :content, :excerpt,
                :meta_title, :meta_description, :keywords, :category,
                :author, CAST(:faq AS jsonb), CAST(:schema AS jsonb),
                :status, 0, :published_at, :now, :now
            )
        """), {
            "id": post_id, "title": title, "slug": slug,
            "content": blog_content, "excerpt": hook_text[:300],
            "meta_title": seo.get("meta_title", title)[:60] if isinstance(seo, dict) else title[:60],
            "meta_description": seo.get("meta_description", "")[:160] if isinstance(seo, dict) else "",
            "keywords": keywords_str,
            "category": intent.category or "awareness",
            "author": "NISCHINT AI",
            "faq": json_mod.dumps([]),
            "schema": json_mod.dumps(schema_json),
            "status": blog_status,
            "published_at": published_at,
            "now": now,
        })
        await session.commit()

        # Step 4: Ingest into RAG
        chunks = chunk_text(blog_content)
        chunks_count = 0
        if chunks and embeddings_available():
            try:
                from app.services.embedding_service import get_embeddings_batch
                embeddings = get_embeddings_batch(chunks)

                await session.execute(text("DELETE FROM blog_chunks WHERE blog_id = :bid"), {"bid": post_id})
                for i, chunk_item in enumerate(chunks):
                    chunk_id = str(uuid.uuid4())
                    meta = {"chunk_index": i, "total_chunks": len(chunks), "slug": slug, "auto_generated": True}
                    emb_str = "[" + ",".join(str(v) for v in embeddings[i]) + "]"
                    await session.execute(text("""
                        INSERT INTO blog_chunks (id, blog_id, title, content, chunk_text, chunk_index, embedding, metadata)
                        VALUES (:id, :bid, :title, :content, :chunk, :ci,
                                CAST(:emb AS vector), CAST(:meta AS jsonb))
                    """), {
                        "id": chunk_id, "bid": post_id, "title": title,
                        "content": blog_content[:500], "chunk": chunk_item,
                        "ci": i, "emb": emb_str, "meta": json_mod.dumps(meta),
                    })
                chunks_count = len(chunks)
                await session.commit()
            except SQLAlchemyError as e:
                # Compensating action: blog post is already live but
                # missing from the RAG index. LPUSH to `dlq:rag_reindex`
                # so an offline reconciler can re-chunk + re-embed.
                # Search won't surface this post until reindexed —
                # the operator signal IS the depth on this DLQ.
                _push_rag_reindex_dlq({
                    "post_id":     post_id,
                    "title":       title,
                    "slug":        slug,
                    "query":       intent.query,
                    "persona":     intent.persona,
                    "section_count": len(sections),
                    "failed_at":   datetime.now(timezone.utc).isoformat(),
                    "error_type":  type(e).__name__,
                    "error":       str(e)[:200],
                })
                logger.warning(
                    "rag_reindex_dlq",
                    extra={
                        "event":      "rag_reindex_dlq",
                        "post_id":    post_id,
                        "slug":       slug,
                        "error_type": type(e).__name__,
                    },
                )
                await session.rollback()

        # Step 5: Track insight
        try:
            from app.services.rag_insight_service import log_insight
            await log_insight(session, {
                "event_type": "blog_published",
                "query": intent.query,
                "persona": intent.persona,
                "emotion": intent.emotion,
                "blog_id": post_id,
                "blog_slug": slug,
                "source": "n8n",
                "metadata": {
                    "title": title, "auto_generated": True,
                    "sections": len(sections), "chunks": chunks_count,
                },
            })
        except Exception as e:
            logger.warning(f"Auto-publish insight logging failed: {e}")

        blog_url = f"{BASE_URL}/blog/{slug}"
        logger.info(f"[AUTO-PUBLISH] '{title}' → {slug} ({chunks_count} chunks)")

        return AutoPublishResult(
            query=intent.query, status="success",
            blog_id=post_id, slug=slug, url=blog_url,
            chunks_ingested=chunks_count,
        )

    except (SQLAlchemyError, ValueError, RuntimeError) as e:
        # Compensating action: pipeline returns an
        # AutoPublishResult with `status="error"` so the caller
        # (typically the n8n cron) knows the specific failure and
        # can retry on its own schedule. Narrow types cover DB +
        # validation + downstream service errors; everything else
        # propagates so coding bugs surface in alerting.
        logger.error(
            "auto_publish_pipeline_failed",
            extra={
                "event":      "auto_publish_pipeline_failed",
                "query":      intent.query,
                "error_type": type(e).__name__,
            },
        )
        return AutoPublishResult(query=intent.query, status="error", error=str(e)[:300])


DEFAULT_INTENTS = [
    AutoPublishIntent(query="child safety tips for Indian parents", persona="parent", emotion="concern", category="child_safety"),
    AutoPublishIntent(query="women safety while traveling alone at night", persona="woman", emotion="risk", category="women_safety"),
    AutoPublishIntent(query="elderly parents living alone safety solutions", persona="guardian", emotion="concern", category="family_safety"),
    AutoPublishIntent(query="family GPS tracking app benefits", persona="parent", emotion="worry", category="family_safety"),
    AutoPublishIntent(query="school commute safety for children in India", persona="parent", emotion="fear", category="child_safety"),
]

# Persona/emotion mapping by keyword
_PERSONA_MAP = {
    "child": ("parent", "fear", "child_safety"),
    "kid": ("parent", "worry", "child_safety"),
    "school": ("parent", "concern", "child_safety"),
    "women": ("woman", "anxiety", "women_safety"),
    "woman": ("woman", "risk", "women_safety"),
    "girl": ("woman", "fear", "women_safety"),
    "elder": ("guardian", "concern", "family_safety"),
    "family": ("parent", "concern", "family_safety"),
    "parent": ("parent", "worry", "family_safety"),
}


def _query_to_intent(query_text: str) -> AutoPublishIntent:
    """Convert a raw query string into a typed intent with persona/emotion."""
    q_lower = query_text.lower()
    for keyword, (persona, emotion, category) in _PERSONA_MAP.items():
        if keyword in q_lower:
            return AutoPublishIntent(query=query_text, persona=persona, emotion=emotion, category=category)
    return AutoPublishIntent(query=query_text, persona="parent", emotion="concern", category="awareness")


@rag_router.post("/auto-publish", response_model=AutoPublishBatchResponse)
async def auto_publish(req: AutoPublishBatchRequest, session: AsyncSession = Depends(get_db_session)):
    """Auto Blog Machine — Execute full pipeline for each intent: Generate → Create → Ingest → Track.
    When use_top_queries=true, prioritizes high-performing queries from insights."""
    await ensure_rag_tables(session)

    intents = list(req.intents)

    # Prioritize top-performing queries when enabled
    if req.use_top_queries:
        from app.services.rag_insight_service import get_top_performing_queries
        top = await get_top_performing_queries(session, limit=20)

        # Filter: queries with CTA clicks or leads are highest value
        # Then pick those with fewer blog_published events (avoid over-publishing same topic)
        scored = []
        for tq in top:
            q = tq["query"]
            if not q:
                continue
            # Score: leads*10 + cta*5 + generated*1, penalize if already published a lot
            value = tq["leads"] * 10 + tq["cta_clicks"] * 5 + tq["generated"]
            scored.append((value, q))

        scored.sort(key=lambda x: -x[0])

        # Deduplicate against provided intents
        existing_queries = {i.query.lower().strip() for i in intents}
        for _, q in scored:
            if q.lower().strip() in existing_queries:
                continue
            existing_queries.add(q.lower().strip())
            intents.insert(0, _query_to_intent(q))  # Prepend (higher priority)
            if len(intents) >= req.max_intents:
                break

    # Fallback to defaults if still empty
    if not intents:
        import hashlib
        from datetime import datetime as dt
        day_hash = int(hashlib.md5(dt.now(timezone.utc).strftime("%Y-%m-%d").encode()).hexdigest(), 16)
        for i in range(min(req.max_intents, len(DEFAULT_INTENTS))):
            idx = (day_hash + i) % len(DEFAULT_INTENTS)
            intents.append(DEFAULT_INTENTS[idx])

    # Cap to max_intents
    intents = intents[:req.max_intents]

    results = []
    published = 0
    errors = 0

    for intent in intents:
        result = await _run_single_pipeline(intent, session)
        results.append(result)
        if result.status == "success":
            published += 1
        else:
            errors += 1

    logger.info(f"[AUTO-PUBLISH BATCH] {published}/{len(req.intents)} published, {errors} errors")

    return AutoPublishBatchResponse(
        total=len(intents),
        published=published,
        errors=errors,
        results=results,
    )


# ══════════════════════════════════════════════════════════════════════
# Revenue Dashboard
# ══════════════════════════════════════════════════════════════════════

@rag_router.get("/revenue/summary")
async def revenue_summary(session: AsyncSession = Depends(get_db_session)):
    """Lightweight revenue dashboard from rag_insights."""
    from app.services.rag_insight_service import ensure_table, get_top_performing_queries
    await ensure_table(session)

    # Counts by event type (single query)
    rows = await session.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE event_type = 'blog_generated') AS blogs_generated,
            COUNT(*) FILTER (WHERE event_type = 'blog_published') AS blogs_published,
            COUNT(*) FILTER (WHERE event_type = 'cta_clicked')    AS cta_clicks,
            COUNT(*) FILTER (WHERE event_type = 'lead_created')   AS total_leads,
            COUNT(*) FILTER (WHERE conversion = TRUE)             AS conversions,
            COUNT(*) AS total_events
        FROM rag_insights
    """))
    stats = rows.fetchone()

    total_blogs = (stats.blogs_generated or 0) + (stats.blogs_published or 0)
    total_leads = stats.total_leads or 0
    conversions = stats.conversions or 0
    cta_clicks = stats.cta_clicks or 0
    conversion_rate = round((total_leads / total_blogs * 100), 2) if total_blogs > 0 else 0.0

    # Top persona + emotion (single query)
    persona_row = await session.execute(text("""
        SELECT persona, COUNT(*) AS cnt FROM rag_insights
        WHERE persona IS NOT NULL GROUP BY persona ORDER BY cnt DESC LIMIT 1
    """))
    top_persona = (p.persona if (p := persona_row.fetchone()) else "")

    emotion_row = await session.execute(text("""
        SELECT emotion, COUNT(*) AS cnt FROM rag_insights
        WHERE emotion IS NOT NULL GROUP BY emotion ORDER BY cnt DESC LIMIT 1
    """))
    top_emotion = (e.emotion if (e := emotion_row.fetchone()) else "")

    # Top queries (reuse existing service)
    top_queries = await get_top_performing_queries(session, limit=5)

    return {
        "total_blogs": total_blogs,
        "total_leads": total_leads,
        "cta_clicks": cta_clicks,
        "conversions": conversions,
        "conversion_rate": conversion_rate,
        "top_queries": top_queries,
        "top_persona": top_persona,
        "top_emotion": top_emotion,
        "total_events": stats.total_events or 0,
    }
