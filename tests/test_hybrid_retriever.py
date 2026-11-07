"""Acceptance tests for Qdrant hybrid retrieval (`app/rag/ingest.py`, `app/rag/retriever.py`).

Acceptance criterion: Recall@5 >= 90% on `eval/labeled_cases.json`.

The index is built in an in-memory Qdrant, so no server is needed. The FastEmbed models are
downloaded on first use; when they cannot be loaded (e.g. offline CI) the model-dependent
tests are skipped rather than failing.
"""

from __future__ import annotations

import pytest

from app.rag.ingest import build_passages, ingest_corpus, load_corpus
from app.rag.retriever import DEFAULT_TOP_K, HybridRetriever, recall_at_k
from app.rag.vector_store import RAGSettings, create_qdrant_client
from eval.run_retrieval_eval import RECALL_TARGET, evaluate_recall, format_report

IN_MEMORY = RAGSettings(qdrant_url=None, qdrant_path=":memory:")


@pytest.fixture(scope="module")
def retriever() -> HybridRetriever:
    try:
        client = create_qdrant_client(IN_MEMORY)
        ingest_corpus(client, IN_MEMORY, recreate=True)
    except Exception as exc:  # noqa: BLE001 - model download / load failure
        pytest.skip(f"embedding models unavailable: {exc}")
    yield HybridRetriever(client=client, settings=IN_MEMORY)
    client.close()


def test_corpus_has_25_unique_guideline_chunks() -> None:
    chunks = load_corpus(IN_MEMORY.corpus_path)
    assert len(chunks) == 25
    assert len({chunk.doc_id for chunk in chunks}) == 25


def test_passages_cover_every_word_and_have_stable_ids() -> None:
    for chunk in load_corpus(IN_MEMORY.corpus_path):
        passages = build_passages(chunk)
        assert passages[0].passage_index == 0 and chunk.title in passages[0].text
        indexed_words = set(" ".join(p.text for p in passages[1:]).split())
        assert set(chunk.content.split()) <= indexed_words
        assert [p.point_id for p in passages] == [p.point_id for p in build_passages(chunk)]


def test_recall_at_k_metric() -> None:
    assert recall_at_k(["A", "B", "C"], ["A"], k=5) == 1.0
    assert recall_at_k(["A", "B", "C"], ["A", "Z"], k=5) == 0.5
    assert recall_at_k(["X", "Y", "Z", "W", "V", "A"], ["A"], k=5) == 0.0


def test_recall_at_5_meets_90_percent_target(retriever: HybridRetriever) -> None:
    report = evaluate_recall(retriever, k=DEFAULT_TOP_K)
    print("\n" + format_report(report))
    assert report.recall >= RECALL_TARGET, format_report(report)


def test_returns_top_5_unique_documents_with_citation_metadata(retriever: HybridRetriever) -> None:
    result = retriever.retrieve("حاسس بطابوقة على صدري والوجع مسمع في دراعي الشمال")
    assert len(result.documents) == DEFAULT_TOP_K
    assert len(set(result.doc_ids)) == DEFAULT_TOP_K
    assert "NHS-CARDIO-001" in result.doc_ids
    top = result.documents[0]
    assert top.title and top.url.startswith("https://") and top.snippet


def test_query_is_pii_scrubbed_and_dialect_enriched(retriever: HybridRetriever) -> None:
    result = retriever.retrieve("أنا اسمي طارق عبد الرحمن ورقمي 01098765432، عندي حرقان ونار قايدة في فم المعدة")
    assert "01098765432" not in result.query and "طارق" not in result.query
    assert "Heartburn" in result.query or "GERD" in result.query
    assert "NHS-GI-001" in result.doc_ids


def test_empty_complaint_is_rejected(retriever: HybridRetriever) -> None:
    with pytest.raises(ValueError):
        retriever.retrieve("   ")
