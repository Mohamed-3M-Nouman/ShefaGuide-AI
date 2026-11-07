# ShefaGuide-AI

This README covers the work on branch `feature/rag-dialect-normalizer-db`. That branch adds three components of the ShefaGuide AI backend:

| # | Component | Files | Acceptance criterion | Result |
|---|-----------|-------|----------------------|--------|
| 1 | Egyptian dialect normalizer | `app/rag/dialect_normalizer.py` | < 50 ms per call; 20-sentence pytest at 100% | **~0.6 ms worst case; 20/20 pass** |
| 2 | Hybrid search in Qdrant (dense + BM25) | `app/rag/ingest.py`, `app/rag/retriever.py`, `app/rag/vector_store.py` | Recall@5 ≥ 90% on `eval/labeled_cases.json` | **91.88%** |
| 3 | Audit and escalation tables in PostgreSQL | `app/db/models.py`, `app/db/crud.py` | Sensitive record stored as `[REDACTED]`, 0% leakage | **0% leakage, verified on PostgreSQL 17.6** |

Only these three tasks are implemented. The LangGraph agent, FastAPI gateway, frontend, voice pipeline and dashboard are out of scope for this branch.

---

## Table of contents

1. [Quick start](#1-quick-start)
2. [Repository layout](#2-repository-layout)
3. [How the pieces fit together](#3-how-the-pieces-fit-together)
4. [Task 1: Egyptian dialect normalizer](#4-task-1-egyptian-dialect-normalizer)
5. [Task 2: Hybrid search in Qdrant](#5-task-2-hybrid-search-in-qdrant)
6. [Task 3: Audit log and escalation queue in PostgreSQL](#6-task-3-audit-log-and-escalation-queue-in-postgresql)
7. [Tests](#7-tests)
8. [Configuration reference](#8-configuration-reference)
9. [Decisions, issues found, and known limitations](#9-decisions-issues-found-and-known-limitations)

---

## 1. Quick start

Requirements: Python 3.11+ (developed on 3.12) and Docker. The existing code uses `str | None` in Pydantic models, so it does not run on the macOS system Python 3.9.

```bash
# 1. Infrastructure: PostgreSQL 17.6 + Qdrant 1.20.0
docker compose up -d

# 2. Python environment
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Build the Qdrant index (the first run downloads ~0.25 GB of models into .cache/fastembed)
QDRANT_URL=http://localhost:6333 python -m app.rag.ingest --recreate

# 4. Measure Recall@5 (exits non-zero if below 90%)
QDRANT_URL=http://localhost:6333 python -m eval.run_retrieval_eval --persistent

# 5. Run all tests, with the database tests on PostgreSQL
TEST_DATABASE_URL=postgresql+asyncpg://shefaguide:shefaguide@localhost:5432/shefaguide pytest
```

You can skip Docker:

* `python -m eval.run_retrieval_eval` with no flags builds a throwaway in-memory Qdrant index and evaluates it.
* `pytest` with no `TEST_DATABASE_URL` runs the database tests on a temporary SQLite file. See [§9](#9-decisions-issues-found-and-known-limitations) for why.

---

## 2. Repository layout

New and changed files on this branch:

```
app/
├── rag/
│   ├── __init__.py
│   ├── dialect_normalizer.py   # Task 1: Egyptian slang → clinical terms
│   ├── vector_store.py         # Task 2: shared settings, Qdrant client, embedding models
│   ├── ingest.py               # Task 2: corpus → Qdrant (dense + BM25 vectors)
│   └── retriever.py            # Task 2: hybrid search + RRF fusion, top_k = 5
└── db/
    ├── __init__.py
    ├── models.py               # Task 3: audit_logs, escalation_queue (SQLAlchemy 2.0)
    └── crud.py                 # Task 3: zero-PHI async writes/reads (asyncpg)
eval/
└── run_retrieval_eval.py       # Task 2: Recall@5 measurement
tests/
├── test_dialect_normalizer.py  # Task 1: 33 tests
├── test_hybrid_retriever.py    # Task 2: 7 tests
└── test_db_zero_phi.py         # Task 3: 7 tests
docker-compose.yml              # PostgreSQL + Qdrant for local development
requirements.txt
.gitignore                      # .venv, .qdrant, .cache, caches
```

Existing modules this work depends on, without modifying them:

* `app/safety/pii_scrubber.py`: `scrub_pii()` and `contains_pii()`
* `app/safety/red_flags.py`: `normalize_arabic()`
* `app/schemas/triage.py`: `SymptomCategory` and `UrgencyLevel`

---

## 3. How the pieces fit together

```
patient complaint
      │
      ▼
scrub_pii()                         (existing safety module)
      │
      ▼
DialectNormalizer.normalize()       Task 1: slang → clinical terms, category, red flag, linked docs
      │
      ▼
HybridRetriever.retrieve()          Task 2: enriched query → Qdrant dense + BM25 + lexicon branch → RRF → top 5 docs
      │
      ▼
  ...agent / triage decision (not part of this branch)...
      │
      ▼
crud.log_interaction()              Task 3: scrub again → audit_logs (+ escalation_queue if urgent)
```

---

## 4. Task 1: Egyptian dialect normalizer

### What it does

`app/rag/dialect_normalizer.py` loads `data/egyptian_medical_slang.json` into memory once. The file has 60 entries, 12 per symptom category, 25 of which are red flags.

Given a PII-scrubbed complaint, the normalizer finds Egyptian colloquial expressions such as «كرشة نفس» or «فم المعدة قافش». For each one it returns:

* the standard clinical term in English and Arabic (`clinical_term_en`, `clinical_term_ar`)
* the symptom `category`
* `is_red_flag`
* `linked_doc_ids`, the guideline documents linked to that expression
* `recommended_specialty`
* whether the patient **negated** the symptom
* the match type (`exact` or `partial`) and a confidence score

```python
from app.rag.dialect_normalizer import normalize_dialect

result = normalize_dialect("عندي كرشة نفس شديدة ومش قادر أتكلم")
result.primary_category      # SymptomCategory.CARDIOPULMONARY
result.has_red_flag          # True
result.clinical_terms_en     # ['Severe acute dyspnea with inability to speak full sentences / ...', ...]
result.linked_doc_ids        # ['NHS-CARDIO-002', 'WHO-CARDIO-005']
result.enriched_query()      # complaint + clinical terms, used by the retriever
```

### Why it is built this way

Exact phrase matching alone was not enough. The lexicon phrases are full sentences, and patients paraphrase them. Searching only for exact lexicon phrases found a slang entry in just **8 of the 60 clinical cases** in `eval/labeled_cases.json`. The task's own example «فم المعدة قافش» is not in the lexicon at all.

The normalizer therefore matches in two tiers.

### How it works

1. **Arabic normalization.** The normalizer reuses `normalize_arabic()` from `app/safety/red_flags.py`. It removes diacritics and tatweel and unifies alef/hamza forms, ى→ي and ة→ه. The lexicon and the complaint are normalized the same way.

2. **Tier 1: exact match (confidence 1.0).** Each entry compiles into one regex that tolerates extra whitespace and an attached proclitic (و / ب / ف). For example «بطابوقة على صدري» matches «طابوقة على صدري».

3. **Tier 2: partial match.** This tier catches paraphrases:
   * Each lexicon phrase is tokenized. Stop words and generic modifiers are dropped: sides («الشمال»), durations («أربع أيام»), fillers («فيه», «تحت»). Without this, pairs like «رجلي الشمال» would match unrelated entries.
   * A light, symmetric stemmer removes the prefixes و/ال/بال/ب and the suffixes ي/ه/ها. Because the lexicon and the complaint get the same treatment, «صدري» matches «صدره».
   * Adjacent content-word **bigrams** become cues. A bigram shared by more than 2 entries is discarded as non-distinctive. A bigram unique to one entry weighs 1.0; one shared by two entries weighs 0.5.
   * The first bigram of a phrase is usually the idiom itself («كرشة نفس», «عرق النسا», «فم المعدة»). It counts as a full cue for *accepting* a match even when two entries share it.
   * An entry matches when its cue score is ≥ 1.0. Confidence is `max(phrase coverage, 1 − 0.5^evidence)`, capped at 0.95. The leading-idiom boost does not count toward confidence.

4. **Intensity words are kept on purpose.** Words such as «شديدة» and «رهيب» are not treated as generic. They are what separates the red flag «كرشة نفس شديدة» from the routine «كرشة نفس».

5. **Negation.** If a match is directly preceded by a negator («مفيش», «معنديش», «من غير», «بدون», …), it is reported with `negated=True` and excluded from the active symptoms. The negator can also come in the form «مفيش X ولا Y». The logic mirrors the anchored negation in `red_flags.py`, so «مفيش سخونية بس عندي كحة» does **not** negate the cough.

6. **Red-flag safety threshold.**
   * `has_red_flag` is true only for an affirmed red-flag match with confidence ≥ 0.6, meaning an exact phrase or at least two independent cues.
   * Weaker red-flag evidence is not dropped. It goes into `possible_red_flags` for the downstream severity tool.
   * Without this split, generic complaints such as «وجع في أسفل الضهر» raised false red flags (cauda equina) in 8 routine cases.
   * This module only normalizes. The escalation decision stays with `app/safety/red_flags.py` and the agent.

### Results

Measured on the 90 non-adversarial cases in `eval/labeled_cases.json`:

* The strongest match is in the correct category for 66 cases, the wrong category for 2, and 22 have no match. That includes all 10 ambiguous cases, which correctly match nothing.
* No routine clinical case raises `has_red_flag`. All 20 emergency cases raise it.
* Every one of the lexicon's phrases matches its own entry exactly (self-consistency test).
* Lexicon load takes about 10 ms, once per process. The worst call is about 0.6 ms, against a 50 ms budget.

---

## 5. Task 2: Hybrid search in Qdrant

### What it does

* `app/rag/ingest.py` indexes the 25 guideline chunks in `data/corpus/medical_guidelines_chunks.json` (NHS / WHO / Mayo Clinic) into the Qdrant collection `medical_guidelines`. Each point has two named vectors: `dense` (multilingual embedding) and `bm25` (sparse BM25 weights, with Qdrant's IDF modifier).
* `app/rag/retriever.py` takes a patient complaint, runs a hybrid search, and returns the **top 5 unique guideline documents** with citation metadata: `doc_id`, `title`, `source`, `url`, `category`, specialty, best passage and score.

```python
from app.rag.retriever import HybridRetriever

retriever = HybridRetriever()                         # uses QDRANT_URL, or the local store
result = retriever.retrieve("حاسس بطابوقة على صدري والوجع مسمع في دراعي الشمال")
result.doc_ids                                        # ['NHS-CARDIO-001', ...]  (5 documents)
result.documents[0].url                               # citation link
```

### Why and how

**The language gap.** Patient complaints are Egyptian Arabic, but the guidelines are English. BM25 on its own cannot match Arabic words against English text, so the retriever first runs the Task 1 normalizer. It appends the standard **English and Arabic clinical terms** to the query (`enriched_query()`). This gives BM25 English terms to match and gives the dense model a cleaner signal.

**Retrieval steps** (`HybridRetriever.retrieve`):

1. `scrub_pii()` runs again on the query. This is defense in depth, and the function is idempotent.
2. The complaint is normalized and the enriched query is built.
3. One Qdrant `query_points` call runs up to three **prefetch** branches, fused with **Reciprocal Rank Fusion (RRF)**:

   | Branch | Vector | Purpose |
   |--------|--------|---------|
   | Dense | `dense` | Semantic, cross-lingual match. Low cosine threshold (0.1) to favor recall. |
   | Sparse | `bm25` | Exact clinical keywords from the enriched query. |
   | Lexicon-guided | `dense`, filtered to `linked_doc_ids` | Only when slang is recognized: dense search restricted to the guidelines the curated lexicon links to the expression. |

   Each branch takes up to 50 candidates, a wide window that is cheap on a 178-passage index.
4. Passages are collapsed to unique documents (best passage kept) and the top `top_k = 5` are returned.

**Why the third branch.** Plain dense + BM25 reached **89.38%**, just below the target. The lexicon already records which guideline covers each slang expression. Using it as one more RRF branch can only *add* candidates, never remove them, which suits the high-recall goal. With it, Recall@5 rose to **91.88%**.

**Why passages instead of whole chunks.**
* The chunks average ~311 words, and multilingual sentence encoders truncate at 128 tokens, so most of each chunk would never be embedded.
* `ingest.py` therefore splits each chunk into passages:
  * one summary passage: title, specialty in English and Arabic, red flags
  * 70-word content windows with 20-word overlap, each prefixed with the title
* Point IDs are deterministic (`uuid5(doc_id#index)`), so re-ingesting is idempotent.
* The 25 chunks become 178 points.

**Model choice.**
* The dense model is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (0.22 GB, 384 dimensions). It is multilingual (Arabic + English) and small enough for teammates to download.
* `paraphrase-multilingual-mpnet-base-v2` (~1 GB) was tried. Its download stalled twice on a slow connection, and MiniLM already meets the target, so MiniLM is the default.
* The sparse model is `Qdrant/bm25`.
* Models are stored in `.cache/fastembed` inside the repo. See [§9](#9-decisions-issues-found-and-known-limitations) for why.

**Local or server.**
* If `QDRANT_URL` is set, the code talks to a Qdrant server, for example the one in `docker-compose.yml`.
* Otherwise it uses the embedded local Qdrant at `QDRANT_PATH` (default `.qdrant/`).
* `QDRANT_PATH=":memory:"` gives a throwaway index, which the tests use.

### How Recall@5 is measured

`eval/run_retrieval_eval.py`:

* For each case, Recall@5 = `|expected_doc_ids ∩ top-5 retrieved| / |expected_doc_ids|`, macro-averaged over cases.
* The headline score uses the **80 clinical and emergency cases**, the inputs that actually reach retrieval.
* The 9 adversarial cases also list expected documents, but the input validator rejects them before retrieval. They are reported separately.

Results, the same on the in-memory index and on the Qdrant 1.20.0 server:

```
Recall@5 (clinical + emergency, n=80): 91.88%  [target >= 90%: PASS]
Recall@5 (all cases with expected docs, n=89): 90.45%
Hit-rate@5: 92.50%
Average retrieval latency: ~13–15 ms
```

The 7 cases that still miss are EVAL-011, 012, 029, 035, 045, 054 and 059. Most contain no expression from the slang lexicon, so they rely on the dense model alone.

---

## 6. Task 3: Audit log and escalation queue in PostgreSQL

### What it does

`app/db/models.py` defines two SQLAlchemy 2.0 tables for PostgreSQL. `app/db/crud.py` provides async functions (asyncpg) that write them with a **zero-PHI** guarantee.

### Schema (ERD)

The proposal document has no ERD, so the schema is derived from:

* FR-11: the escalation dashboard shows timestamp, category, red flags and status.
* FR-12: the audit log records session ID, scrubbed input, citations, tool calls, latency and decision.
* NFR-04: every decision is traceable to tool state and document IDs.

```
audit_logs (1) ───────────────< (0..1) escalation_queue
──────────────────────────────          ──────────────────────────────
id                  UUID PK             id                  UUID PK
session_id          VARCHAR(64)         audit_log_id        UUID FK → audit_logs.id (unique, cascade)
created_at          TIMESTAMPTZ         session_id          VARCHAR(64)
scrubbed_input      TEXT                created_at          TIMESTAMPTZ
symptom_category    VARCHAR(32)         symptom_category    VARCHAR(32)
urgency_level       SMALLINT (1..4)     detected_red_flags  JSONB
recommended_specialty TEXT              scrubbed_summary    TEXT
rationale           TEXT                status              pending | acknowledged | resolved
retrieved_doc_ids   JSONB               acknowledged_at     TIMESTAMPTZ
tool_calls          JSONB               resolved_at         TIMESTAMPTZ
escalation_triggered BOOLEAN
latency_ms          DOUBLE PRECISION
```

There are check constraints on `urgency_level`, `latency_ms` and `status`, plus indexes on `(session_id, created_at)` and `(status, created_at)` for the dashboard queries. Please review the schema if the team has a different ERD.

### How Zero-PHI is enforced

There are three independent layers:

1. **Explicit scrubbing in the CRUD layer.** `create_audit_log()` and `enqueue_escalation()` pass every free-text field through `scrub_pii()` before building the row. JSON fields are scrubbed recursively, keys included.
2. **Fail-fast verification.** After scrubbing, `contains_pii()` checks the result. If anything identifiable survived, `PHILeakError` is raised and nothing is written, because the transaction rolls back.
3. **Column types that scrub at bind time.**
   * Every text column is `ScrubbedText`, and every JSON column is `ScrubbedJSON` (JSONB on PostgreSQL). Both run `scrub_pii()` when the value is sent to the database.
   * Code that bypasses `crud.py` and writes ORM objects directly still cannot store PII.

In addition, `session_id` must be an opaque token: 8–64 characters, `[A-Za-z0-9_-]`, and rejected if it looks like a phone number or national ID.

### Usage

```python
from app.db.crud import AuditLogCreate, create_engine, create_session_factory, init_db, log_interaction

engine = create_engine()                      # DATABASE_URL, default postgresql+asyncpg://shefaguide:...@localhost:5432/shefaguide
await init_db(engine)                         # creates the two tables if missing
factory = create_session_factory(engine)

async with factory() as session, session.begin():
    audit, escalation = await log_interaction(
        session,
        AuditLogCreate(session_id="sess_abc12345", user_input=raw_text,
                       symptom_category=..., urgency_level=..., retrieved_doc_ids=[...]),
        detected_red_flags=["..."],
    )
```

How the functions behave:

* `log_interaction` writes the audit row. It also adds an `escalation_queue` row, **in the same transaction**, when `escalation_triggered` is true or urgency is `EMERGENCY_ESCALATION`.
* `list_escalations(status=...)` returns escalations for the dashboard, newest first.
* `update_escalation_status()` moves a case from pending to acknowledged to resolved, with timestamps.
* The functions only `flush()`. The caller owns the transaction.

### Verified on PostgreSQL

A record with a name, mobile number and national ID was saved through `crud` and then read back with `psql`:

```
 scrubbed_input
--------------------------------------------------------------------------------------
 أنا اسمي [REDACTED] ورقمي [REDACTED] والرقم القومي [REDACTED]، حاسس بطابوقة على صدري
```

The clinical content is preserved, and an `escalation_queue` row was created with status `pending`.

---

## 7. Tests

```
77 passed: 30 existing + 47 new (all DB tests also pass on PostgreSQL)
```

| File | Tests | What is checked |
|------|-------|-----------------|
| `tests/test_dialect_normalizer.py` | 33 | **The 20 acceptance sentences.** Each is scrubbed, then checked for the right `slang_id`, clinical terms, category, `is_red_flag`, linked docs and specialty. Also: latency < 50 ms (25 rounds, plus one long complaint); the lexicon loads once; every lexicon phrase self-matches; negation, and negation not leaking to a later symptom; weak red flags not escalating; empty and unrelated input; `[REDACTED]` passing through; `enriched_query`; missing-lexicon fail-fast. |
| `tests/test_hybrid_retriever.py` | 7 | **Recall@5 ≥ 90%.** Also: the corpus has 25 unique chunks; passages cover every word and have stable IDs; the Recall@k formula; 5 unique documents with citation metadata; the query is PII-scrubbed and dialect-enriched; an empty query is rejected. The model-dependent tests are *skipped*, not failed, if the models cannot be loaded (e.g. offline CI). |
| `tests/test_db_zero_phi.py` | 7 | **A sensitive record is stored as `[REDACTED]` with 0% leakage**, checked by reading the raw rows with SQL and decoding JSON so escaped Arabic is checked too. Also: ORM writes that bypass `crud` are still scrubbed; routine cases are not enqueued; the escalation lifecycle; identifying `session_id` values are rejected; a broken scrubber triggers `PHILeakError` and nothing is written. |

```bash
pytest                                   # DB tests on SQLite
TEST_DATABASE_URL=postgresql+asyncpg://shefaguide:shefaguide@localhost:5432/shefaguide pytest   # on PostgreSQL
pytest tests/test_hybrid_retriever.py -s # prints the full Recall@5 report
```

---

## 8. Configuration reference

| Variable | Default | Used by |
|----------|---------|---------|
| `QDRANT_URL` | unset, which means embedded local Qdrant | ingest, retriever |
| `QDRANT_API_KEY` | unset | ingest, retriever |
| `QDRANT_PATH` | `<repo>/.qdrant` (`:memory:` for a throwaway index) | ingest, retriever |
| `QDRANT_COLLECTION` | `medical_guidelines` | ingest, retriever |
| `RAG_DENSE_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | ingest, retriever |
| `RAG_SPARSE_MODEL` | `Qdrant/bm25` | ingest, retriever |
| `RAG_MODEL_CACHE` | `<repo>/.cache/fastembed` | ingest, retriever |
| `DATABASE_URL` | `postgresql+asyncpg://shefaguide:shefaguide@localhost:5432/shefaguide` | db |
| `TEST_DATABASE_URL` | unset, which means a temporary SQLite file | DB tests |

If you change the dense model, re-run `python -m app.rag.ingest --recreate`. The vector size depends on the model.

---

## 9. Decisions, issues found, and known limitations

**SQLite in the DB tests.**
* SQLite is used **only by the tests, and only when `TEST_DATABASE_URL` is unset**. The application code targets PostgreSQL: asyncpg driver, JSONB columns.
* It was added because no PostgreSQL or Docker was available when the tests were written.
* A pass on SQLite does not guarantee a pass on PostgreSQL, so run the tests against PostgreSQL before merging. Making PostgreSQL the only test target is a reasonable follow-up.

**`eval/run_eval.py` replaces `asyncio.run` globally.**
* This existing file overwrites `asyncio.run` on import with a shim that cannot drive real I/O.
* When the whole suite runs, any later async code that talks to a database breaks.
* The new DB tests avoid it by using `asyncio.Runner`. The file itself was not modified because it is outside this branch's scope.
* Other real async code will hit the same problem, so removing that patch is recommended.

**FastEmbed model cache.**
* FastEmbed stores models in the OS temp directory by default, which macOS purges.
* That silently deleted the downloaded models once, and the retrieval tests started skipping.
* Models now live in `.cache/fastembed`, which is git-ignored.

**Qdrant version.**
* `qdrant-client` 1.20 warns against a 1.15 server, so `docker-compose.yml` pins `qdrant/qdrant:v1.20.0`.
* Qdrant cannot open storage written by a much older version. After changing the image version, delete the volume and re-ingest: `docker compose down -v && docker compose up -d`. The index is fully rebuildable.

**Payload index warning.** In embedded local mode, Qdrant warns that payload indexes have no effect. This is expected: they take effect on the server.

**Limitations.**
* Recall@5 is 91.88%, about two points above the target. The misses are complaints with no slang the lexicon recognizes.
* The fastest ways to improve further are adding more phrases to `egyptian_medical_slang.json`, or a stronger multilingual model (e.g. `intfloat/multilingual-e5-large`, 2.2 GB) on a good connection.
* The normalizer's partial tier is lexical. It cannot understand synonyms that share no words with the lexicon.
* The ERD is derived from the requirements. If the team has an official ERD, align `models.py` with it.
* There is no migration tool yet. `init_db()` uses `create_all`, which creates missing tables but never alters existing ones.
