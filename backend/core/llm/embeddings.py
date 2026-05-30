"""Embedding backend: OpenAI Embeddings API.

We use the API instead of a local sentence-transformers model so the worker
process doesn't have to load torch (~300 MB) — that's the difference between
RAG fitting in Render's 512 MB free tier and getting SIGKILLed for OOM.

Public surface:
    embed_texts(list[str]) -> np.ndarray of shape (N, dim), L2-normalized, float32
    get_embedding_dimension() -> int
"""
import numpy as np
from openai import OpenAI
from django.conf import settings

_client = None


def _get_client():
    global _client
    if _client is None:
        # Lazy import so the openai module isn't loaded at app boot when RAG
        # is never used in this request cycle.
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def get_embedding_dimension():
    """Vector dimension for the configured embedding model."""
    return int(settings.RAG_EMBEDDING_DIM)


def embed_texts(texts):
    """Embed a list of strings into a (N, dim) float32 array, L2-normalized.

    Raises whatever the OpenAI SDK raises on failure (auth, rate limit,
    quota) — callers can let it bubble up to the API response.
    """
    dim = get_embedding_dimension()
    if not texts:
        return np.zeros((0, dim), dtype="float32")

    client = _get_client()
    kwargs = {
        "model": settings.RAG_EMBEDDING_MODEL,
        "input": list(texts),
    }
    # text-embedding-3-* support requesting reduced dimensions; older models
    # (e.g. ada-002) don't. Only pass the kwarg when the model name suggests
    # it's supported.
    if settings.RAG_EMBEDDING_MODEL.startswith("text-embedding-3"):
        kwargs["dimensions"] = dim

    response = client.embeddings.create(**kwargs)
    vectors = np.array([d.embedding for d in response.data], dtype="float32")

    # OpenAI returns unit-norm vectors at full dimension, but reduced
    # dimensions are only *approximately* normalized. Always re-normalize so
    # FAISS's L2 distance equals 2 - 2*cosine_similarity.
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms
