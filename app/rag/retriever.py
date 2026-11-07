"""High-recall hybrid retriever over the Qdrant medical-guideline index.

For each patient complaint:
  1. PII is scrubbed again (defence in depth; `scrub_pii` is idempotent).
  2. Egyptian slang is normalized and the standardized clinical terms are appended to the
     query, bridging Arabic complaints to the English guideline corpus.
  3. Qdrant runs the prefetches – dense (multilingual embeddings, low similarity threshold),
     sparse BM25, and, when slang was recognized, a dense search restricted to the
     lexicon-linked guidelines – and fuses them with Reciprocal Rank Fusion.
  4. Passages are collapsed to unique guideline documents and the top `top_k` (5) are returned.

The configuration favours recall over precision, as required for safe triage: wide prefetch
windows and a deliberately low dense similarity threshold.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field
from qdrant_client import QdrantClient, models

from app.rag.dialect_normalizer import DialectNormalizer, NormalizationResult, get_dialect_normalizer
from app.rag.vector_store import (
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    RAGSettings,
    create_qdrant_client,
    get_dense_model,
    get_sparse_model,
)
from app.safety.pii_scrubber import scrub_pii
from app.schemas.triage import SymptomCategory

DEFAULT_TOP_K: int = 5
# Low cosine threshold on the dense branch: keep weakly similar passages (high recall).
DEFAULT_DENSE_SCORE_THRESHOLD: float = 0.1
# Candidates per branch before fusion. The corpus is small, so a wide window is cheap.
DEFAULT_PREFETCH_LIMIT: int = 50


class RetrievedDocument(BaseModel):
    """A guideline document returned by hybrid retrieval, ready to be cited."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    title: str
    source: str
    url: str
    category: SymptomCategory
    recommended_specialty_ar: str = ""
    recommended_specialty_en: str = ""
    score: float = Field(..., description="Reciprocal Rank Fusion score of the best passage.")
    snippet: str = Field(..., description="Text of the best-matching passage.")


class RetrievalResult(BaseModel):
    """Retrieved documents plus the normalized query that produced them."""

    model_config = ConfigDict(frozen=True)

    query: str
    normalization: NormalizationResult
    documents: tuple[RetrievedDocument, ...]

    @property
    def doc_ids(self) -> list[str]:
        return [document.doc_id for document in self.documents]


class HybridRetriever:
    """Dense + BM25 hybrid search with RRF fusion over the guideline collection."""

    def __init__(
        self,
        client: QdrantClient | None = None,
        settings: RAGSettings | None = None,
        normalizer: DialectNormalizer | None = None,
        top_k: int = DEFAULT_TOP_K,
        dense_score_threshold: float | None = DEFAULT_DENSE_SCORE_THRESHOLD,
        prefetch_limit: int = DEFAULT_PREFETCH_LIMIT,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        self.settings = settings or RAGSettings()
        self.client = client or create_qdrant_client(self.settings)
        self.normalizer = normalizer or get_dialect_normalizer()
        self.top_k = top_k
        self.dense_score_threshold = dense_score_threshold
        self.prefetch_limit = prefetch_limit
        self._dense_model = get_dense_model(self.settings.dense_model)
        self._sparse_model = get_sparse_model(self.settings.sparse_model)

    def build_query(self, complaint: str) -> tuple[str, NormalizationResult]:
        """Scrub PII, normalize Egyptian slang, and return the enriched retrieval query."""
        normalization = self.normalizer.normalize(scrub_pii(complaint))
        return normalization.enriched_query(), normalization

    def retrieve(
        self,
        complaint: str,
        top_k: int | None = None,
        categories: Sequence[SymptomCategory] | None = None,
    ) -> RetrievalResult:
        """Return the `top_k` most relevant guideline documents for a patient complaint.

        `categories` optionally restricts the search to the given symptom categories.
        """
        if not isinstance(complaint, str) or not complaint.strip():
            raise ValueError("complaint must be a non-empty string")
        limit = top_k or self.top_k
        query, normalization = self.build_query(complaint)

        dense_vector = next(iter(self._dense_model.query_embed(query))).tolist()
        sparse = next(iter(self._sparse_model.query_embed(query)))
        sparse_vector = models.SparseVector(
            indices=sparse.indices.tolist(), values=sparse.values.tolist()
        )

        query_filter = None
        if categories:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="category",
                        match=models.MatchAny(any=[category.value for category in categories]),
                    )
                ]
            )

        prefetch = [
            models.Prefetch(
                query=dense_vector,
                using=DENSE_VECTOR_NAME,
                limit=self.prefetch_limit,
                score_threshold=self.dense_score_threshold,
                filter=query_filter,
            ),
            models.Prefetch(
                query=sparse_vector,
                using=SPARSE_VECTOR_NAME,
                limit=self.prefetch_limit,
                filter=query_filter,
            ),
        ]
        linked_doc_ids = normalization.linked_doc_ids
        if linked_doc_ids:
            # Lexicon-guided branch: dense search restricted to the guidelines the slang
            # lexicon links to the recognized expressions. It is fused like the other two
            # branches, so it can only add candidates (recall), never remove any.
            must: list[models.Condition] = [
                models.FieldCondition(key="doc_id", match=models.MatchAny(any=linked_doc_ids))
            ]
            if query_filter is not None:
                must.extend(query_filter.must or [])
            prefetch.append(
                models.Prefetch(
                    query=dense_vector,
                    using=DENSE_VECTOR_NAME,
                    limit=self.prefetch_limit,
                    filter=models.Filter(must=must),
                )
            )

        response = self.client.query_points(
            collection_name=self.settings.collection_name,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=self.prefetch_limit,
            with_payload=True,
        )

        documents: dict[str, RetrievedDocument] = {}
        for point in response.points:
            payload = point.payload or {}
            doc_id = str(payload.get("doc_id", ""))
            if not doc_id or doc_id in documents:
                continue  # keep only the best-ranked passage per document
            documents[doc_id] = RetrievedDocument(
                doc_id=doc_id,
                title=str(payload.get("title", "")),
                source=str(payload.get("source", "")),
                url=str(payload.get("url", "")),
                category=SymptomCategory(payload.get("category", SymptomCategory.UNKNOWN.value)),
                recommended_specialty_ar=str(payload.get("recommended_specialty_ar", "")),
                recommended_specialty_en=str(payload.get("recommended_specialty_en", "")),
                score=float(point.score),
                snippet=str(payload.get("text", "")),
            )
            if len(documents) >= limit:
                break

        return RetrievalResult(
            query=query, normalization=normalization, documents=tuple(documents.values())
        )


def recall_at_k(retrieved: Sequence[str], expected: Sequence[str], k: int = DEFAULT_TOP_K) -> float:
    """Fraction of expected doc_ids present in the first `k` retrieved doc_ids."""
    wanted = set(expected)
    if not wanted:
        raise ValueError("expected doc_ids must not be empty")
    return len(wanted & set(retrieved[:k])) / len(wanted)
