"""Index the curated medical-guideline corpus into Qdrant for hybrid (dense + BM25) search.

Reads `data/corpus/medical_guidelines_chunks.json` (NHS / WHO / Mayo Clinic guideline chunks),
splits each chunk into overlapping passages so no part of a long chunk is truncated by the
dense encoder, and upserts every passage with two named vectors:

  * `dense` – multilingual sentence embedding (Arabic complaints vs English guidelines)
  * `bm25`  – sparse BM25 term weights, with Qdrant's IDF modifier

Point IDs are deterministic, so re-running ingestion is idempotent.

Usage:
    python -m app.rag.ingest            # create the collection if missing, then upsert
    python -m app.rag.ingest --recreate # drop and rebuild the collection
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import uuid
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from qdrant_client import QdrantClient, models

from app.rag.vector_store import (
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    RAGSettings,
    create_qdrant_client,
    dense_dimension,
    get_dense_model,
    get_sparse_model,
)
from app.schemas.triage import SymptomCategory

logger = logging.getLogger(__name__)

# Passage window in words. Multilingual sentence encoders truncate at 128 tokens (~90 English
# words), so long guideline chunks are split into overlapping windows.
PASSAGE_WORDS: int = 70
PASSAGE_OVERLAP_WORDS: int = 20
_POINT_NAMESPACE = uuid.UUID("5f6b2a4e-3c1d-4e8a-9b7f-2d6c8e1a0b45")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


class GuidelineChunk(BaseModel):
    """One curated guideline chunk from the medical corpus."""

    model_config = ConfigDict(extra="ignore")

    doc_id: str = Field(..., min_length=1)
    source: str
    license: str = ""
    category: SymptomCategory
    title: str
    url: str
    red_flags: list[str] = Field(default_factory=list)
    recommended_specialty_ar: str = ""
    recommended_specialty_en: str = ""
    content: str = Field(..., min_length=1)


class Passage(BaseModel):
    """An indexable window of a guideline chunk."""

    model_config = ConfigDict(frozen=True)

    point_id: str
    doc_id: str
    passage_index: int
    text: str


def load_corpus(path: Path) -> list[GuidelineChunk]:
    """Load and validate the guideline corpus; duplicate doc_ids are rejected."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    chunks = [GuidelineChunk.model_validate(item) for item in raw]
    doc_ids = [chunk.doc_id for chunk in chunks]
    duplicates = sorted({doc_id for doc_id in doc_ids if doc_ids.count(doc_id) > 1})
    if duplicates:
        raise ValueError(f"Duplicate doc_id values in corpus: {duplicates}")
    return chunks


def _windows(words: list[str], size: int, overlap: int) -> list[list[str]]:
    if len(words) <= size:
        return [words]
    step = max(1, size - overlap)
    windows = [words[i : i + size] for i in range(0, len(words) - overlap, step)]
    return [window for window in windows if window]


def build_passages(chunk: GuidelineChunk) -> list[Passage]:
    """Split a chunk into passages, each prefixed with its title so it stays self-describing.

    Passage 0 is a summary (title, specialties, red flags); the rest window over the content.
    """
    header = f"{chunk.title} ({chunk.source})."
    summary_parts = [
        header,
        f"Specialty: {chunk.recommended_specialty_en}." if chunk.recommended_specialty_en else "",
        chunk.recommended_specialty_ar,
        "Red flags: " + " ".join(chunk.red_flags) if chunk.red_flags else "",
    ]
    texts = [" ".join(part for part in summary_parts if part)]

    words = " ".join(_SENTENCE_SPLIT.split(chunk.content.strip())).split()
    for window in _windows(words, PASSAGE_WORDS, PASSAGE_OVERLAP_WORDS):
        texts.append(f"{header} {' '.join(window)}")

    return [
        Passage(
            point_id=str(uuid.uuid5(_POINT_NAMESPACE, f"{chunk.doc_id}#{index}")),
            doc_id=chunk.doc_id,
            passage_index=index,
            text=text,
        )
        for index, text in enumerate(texts)
    ]


def ensure_collection(client: QdrantClient, settings: RAGSettings, recreate: bool = False) -> None:
    """Create the hybrid collection (named dense + sparse BM25 vectors) if needed."""
    exists = client.collection_exists(settings.collection_name)
    if exists and recreate:
        client.delete_collection(settings.collection_name)
        exists = False
    if exists:
        return
    client.create_collection(
        collection_name=settings.collection_name,
        vectors_config={
            DENSE_VECTOR_NAME: models.VectorParams(
                size=dense_dimension(settings.dense_model),
                distance=models.Distance.COSINE,
            )
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
        },
    )
    client.create_payload_index(
        settings.collection_name, field_name="doc_id", field_schema=models.PayloadSchemaType.KEYWORD
    )
    client.create_payload_index(
        settings.collection_name, field_name="category", field_schema=models.PayloadSchemaType.KEYWORD
    )


def ingest_corpus(
    client: QdrantClient,
    settings: RAGSettings | None = None,
    recreate: bool = False,
    batch_size: int = 64,
) -> int:
    """Embed and upsert every passage of the corpus. Returns the number of points written."""
    settings = settings or RAGSettings()
    chunks = load_corpus(settings.corpus_path)
    ensure_collection(client, settings, recreate=recreate)

    dense_model = get_dense_model(settings.dense_model)
    sparse_model = get_sparse_model(settings.sparse_model)

    entries = [(chunk, passage) for chunk in chunks for passage in build_passages(chunk)]
    for start in range(0, len(entries), batch_size):
        batch = entries[start : start + batch_size]
        texts = [passage.text for _, passage in batch]
        dense_vectors = list(dense_model.passage_embed(texts))
        sparse_vectors = list(sparse_model.passage_embed(texts))
        points = [
            models.PointStruct(
                id=passage.point_id,
                vector={
                    DENSE_VECTOR_NAME: dense.tolist(),
                    SPARSE_VECTOR_NAME: models.SparseVector(
                        indices=sparse.indices.tolist(), values=sparse.values.tolist()
                    ),
                },
                payload={
                    "doc_id": chunk.doc_id,
                    "passage_index": passage.passage_index,
                    "text": passage.text,
                    "source": chunk.source,
                    "license": chunk.license,
                    "category": chunk.category.value,
                    "title": chunk.title,
                    "url": chunk.url,
                    "recommended_specialty_ar": chunk.recommended_specialty_ar,
                    "recommended_specialty_en": chunk.recommended_specialty_en,
                },
            )
            for (chunk, passage), dense, sparse in zip(batch, dense_vectors, sparse_vectors)
        ]
        client.upsert(collection_name=settings.collection_name, points=points, wait=True)

    logger.info(
        "Indexed %d passages from %d guideline chunks into '%s'",
        len(entries),
        len(chunks),
        settings.collection_name,
    )
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recreate", action="store_true", help="drop and rebuild the collection")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    settings = RAGSettings()
    client = create_qdrant_client(settings)
    try:
        count = ingest_corpus(client, settings, recreate=args.recreate)
    finally:
        client.close()
    print(f"Indexed {count} passages into '{settings.collection_name}'.")


if __name__ == "__main__":
    main()
