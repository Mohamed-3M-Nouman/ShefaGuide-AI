"""Measure hybrid-retrieval Recall@5 on `eval/labeled_cases.json`.

Recall@5 for one case = |expected_doc_ids ∩ top-5 retrieved| / |expected_doc_ids|, macro-averaged
over cases. The headline metric uses the cases that actually reach retrieval (clinical and
emergency red-flag cases; adversarial inputs are rejected by the input validator first). The
score over every case that lists expected documents is reported as well.

Usage:
    python -m eval.run_retrieval_eval              # in-memory index, rebuilt from the corpus
    python -m eval.run_retrieval_eval --persistent # use the configured Qdrant (QDRANT_URL/PATH)
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.rag.ingest import ingest_corpus
from app.rag.retriever import DEFAULT_TOP_K, HybridRetriever, recall_at_k
from app.rag.vector_store import RAGSettings, create_qdrant_client

LABELED_CASES_PATH: Path = Path(__file__).resolve().parent / "labeled_cases.json"
RETRIEVAL_CASE_TYPES: frozenset[str] = frozenset({"clinical", "emergency_red_flag"})
RECALL_TARGET: float = 0.90


@dataclass
class RecallReport:
    k: int
    recall: float  # headline: clinical + emergency cases
    recall_all: float  # every case with expected_doc_ids
    hit_rate: float  # share of headline cases with at least one expected doc in top-k
    cases: int
    cases_all: int
    avg_latency_ms: float
    misses: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.recall >= RECALL_TARGET


def load_cases(path: Path = LABELED_CASES_PATH) -> list[dict[str, Any]]:
    return [case for case in json.loads(path.read_text("utf-8")) if case.get("expected_doc_ids")]


def evaluate_recall(retriever: HybridRetriever, k: int = DEFAULT_TOP_K) -> RecallReport:
    cases = load_cases()
    headline: list[float] = []
    every: list[float] = []
    hits = 0
    latencies: list[float] = []
    misses: list[dict[str, Any]] = []

    for case in cases:
        started = time.perf_counter()
        doc_ids = retriever.retrieve(case["user_input"], top_k=k).doc_ids
        latencies.append((time.perf_counter() - started) * 1000.0)

        score = recall_at_k(doc_ids, case["expected_doc_ids"], k)
        every.append(score)
        if case["case_type"] not in RETRIEVAL_CASE_TYPES:
            continue
        headline.append(score)
        hits += score > 0
        if score < 1.0:
            misses.append(
                {
                    "case_id": case["case_id"],
                    "recall": round(score, 3),
                    "expected": case["expected_doc_ids"],
                    "retrieved": doc_ids,
                }
            )

    return RecallReport(
        k=k,
        recall=sum(headline) / len(headline),
        recall_all=sum(every) / len(every),
        hit_rate=hits / len(headline),
        cases=len(headline),
        cases_all=len(every),
        avg_latency_ms=sum(latencies) / len(latencies),
        misses=misses,
    )


def format_report(report: RecallReport) -> str:
    lines = [
        f"Recall@{report.k} (clinical + emergency, n={report.cases}): {report.recall:.2%}"
        f"  [target >= {RECALL_TARGET:.0%}: {'PASS' if report.passed else 'FAIL'}]",
        f"Recall@{report.k} (all cases with expected docs, n={report.cases_all}): {report.recall_all:.2%}",
        f"Hit-rate@{report.k}: {report.hit_rate:.2%}",
        f"Average retrieval latency: {report.avg_latency_ms:.1f} ms",
    ]
    if report.misses:
        lines.append("Incomplete retrievals:")
        lines.extend(
            f"  {m['case_id']}: recall={m['recall']} expected={m['expected']} got={m['retrieved']}"
            for m in report.misses
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--persistent", action="store_true", help="query the configured Qdrant instead of a fresh in-memory index")
    parser.add_argument("--k", type=int, default=DEFAULT_TOP_K)
    args = parser.parse_args()

    if args.persistent:
        settings = RAGSettings()
    else:
        settings = RAGSettings(qdrant_url=None, qdrant_path=":memory:")
    client = create_qdrant_client(settings)
    try:
        if not args.persistent:
            ingest_corpus(client, settings, recreate=True)
        report = evaluate_recall(HybridRetriever(client=client, settings=settings), k=args.k)
    finally:
        client.close()
    print(format_report(report))
    raise SystemExit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
