"""
NISCHINT Embedding Service — OpenAI text-embedding-3-small.
Direct API integration for full control over batching and retries.
"""
import logging
from typing import Optional

from openai import OpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Optional[OpenAI] = None


def _get_client() -> Optional[OpenAI]:
    global _client
    if _client is None:
        api_key = settings.openai_api_key
        if not api_key:
            return None
        _client = OpenAI(api_key=api_key)
    return _client


def is_available() -> bool:
    return _get_client() is not None


def get_embedding(text: str) -> list[float]:
    client = _get_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY not configured")
    response = client.embeddings.create(model=settings.embedding_model, input=text)
    return response.data[0].embedding


def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    client = _get_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY not configured")
    # OpenAI supports batching natively — up to 2048 inputs per call
    response = client.embeddings.create(model=settings.embedding_model, input=texts)
    # Sort by index to guarantee order
    sorted_data = sorted(response.data, key=lambda x: x.index)
    return [item.embedding for item in sorted_data]
