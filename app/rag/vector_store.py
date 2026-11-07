"""Shared Qdrant settings, client, and embedding-model factories for ingestion and retrieval.

Configuration (environment variables):
  QDRANT_URL            Qdrant server URL (e.g. http://localhost:6333). When unset, an embedded
                        local Qdrant stored at QDRANT_PATH is used (no server required).
  QDRANT_API_KEY        Optional API key for a remote Qdrant server.
  QDRANT_PATH           Local storage directory for embedded mode (default: <repo>/.qdrant).
  QDRANT_COLLECTION     Collection name (default: medical_guidelines).
  RAG_DENSE_MODEL       FastEmbed multilingual dense model.
  RAG_SPARSE_MODEL      FastEmbed sparse model (default: Qdrant/bm25).
  RAG_MODEL_CACHE       Where FastEmbed models are stored (default: <repo>/.cache/fastembed).
                        FastEmbed's own default is the OS temp dir, which macOS purges.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client import QdrantClient

REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent

MODEL_CACHE_DIR: str = os.getenv("RAG_MODEL_CACHE", str(REPO_ROOT / ".cache" / "fastembed"))

DENSE_VECTOR_NAME: str = "dense"
SPARSE_VECTOR_NAME: str = "bm25"


@dataclass(frozen=True)
class RAGSettings:
    """Runtime configuration for the hybrid medical-guideline index."""

    qdrant_url: str | None = field(default_factory=lambda: os.getenv("QDRANT_URL") or None)
    qdrant_api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)
    qdrant_path: str = field(
        default_factory=lambda: os.getenv("QDRANT_PATH", str(REPO_ROOT / ".qdrant"))
    )
    collection_name: str = field(
        default_factory=lambda: os.getenv("QDRANT_COLLECTION", "medical_guidelines")
    )
    dense_model: str = field(
        default_factory=lambda: os.getenv(
            "RAG_DENSE_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    )
    sparse_model: str = field(default_factory=lambda: os.getenv("RAG_SPARSE_MODEL", "Qdrant/bm25"))
    corpus_path: Path = REPO_ROOT / "data" / "corpus" / "medical_guidelines_chunks.json"


def create_qdrant_client(settings: RAGSettings) -> QdrantClient:
    """Connect to a Qdrant server when QDRANT_URL is set, else open the embedded local store.

    `qdrant_path=":memory:"` gives a throwaway in-process instance (used by tests).
    """
    if settings.qdrant_url:
        return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    if settings.qdrant_path == ":memory:":
        return QdrantClient(location=":memory:")
    return QdrantClient(path=settings.qdrant_path)


@lru_cache(maxsize=4)
def get_dense_model(model_name: str) -> TextEmbedding:
    """Load (and cache) a FastEmbed dense embedding model."""
    return TextEmbedding(model_name=model_name, cache_dir=MODEL_CACHE_DIR)


@lru_cache(maxsize=4)
def get_sparse_model(model_name: str) -> SparseTextEmbedding:
    """Load (and cache) a FastEmbed sparse model (BM25 by default)."""
    return SparseTextEmbedding(model_name=model_name, cache_dir=MODEL_CACHE_DIR)


def dense_dimension(model_name: str) -> int:
    """Embedding size of a FastEmbed dense model."""
    for description in TextEmbedding.list_supported_models():
        if description["model"] == model_name:
            return int(description["dim"])
    return len(next(iter(get_dense_model(model_name).embed(["dimension probe"]))))
