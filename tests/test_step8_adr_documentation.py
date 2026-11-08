"""Completeness and traceability verification tests for Step 8 Architecture Decision Records (`docs/adr/`).

Verifies:
1. All 4 ADR files and `docs/adr/README.md` exist in `docs/adr/` and are non-empty (>= 40 lines each for the 4 ADRs).
2. Each ADR contains required sections (`Status`, `Context`, `Decision`, `Consequences`, `SLO`) and
   status `Accepted — Production Baseline`.
3. The ADR suite references actual existing repository modules (`app/agent/graph.py`, `app/rag/retriever.py`,
   `app/safety/pii_scrubber.py`, `app/voice/adapter.py`, `app/core/sse.py`) and verifies those files exist on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
ADR_DIR: Path = PROJECT_ROOT / "docs" / "adr"

EXPECTED_ADR_FILES: tuple[str, ...] = (
    "ADR-001-langgraph-state-machine-and-supremacy-rule.md",
    "ADR-002-qdrant-hybrid-rag-and-egyptian-dialect-normalization.md",
    "ADR-003-zero-phi-privacy-architecture-and-pii-scrubbing.md",
    "ADR-004-fault-tolerant-voice-adapter-and-global-safe-fallback.md",
)

REQUIRED_SECTIONS: tuple[str, ...] = (
    "Status",
    "Context",
    "Decision",
    "Consequences",
    "SLO",
)

EXPECTED_MODULE_REFERENCES: dict[str, tuple[str, ...]] = {
    "ADR-001-langgraph-state-machine-and-supremacy-rule.md": (
        "app/agent/graph.py",
        "app/agent/state.py",
        "app/safety/red_flags.py",
    ),
    "ADR-002-qdrant-hybrid-rag-and-egyptian-dialect-normalization.md": (
        "app/rag/dialect_normalizer.py",
        "app/rag/retriever.py",
        "app/rag/vector_store.py",
    ),
    "ADR-003-zero-phi-privacy-architecture-and-pii-scrubbing.md": (
        "app/safety/pii_scrubber.py",
        "app/db/models.py",
        "app/db/crud.py",
        "app/core/sse.py",
        "app/voice/adapter.py",
    ),
    "ADR-004-fault-tolerant-voice-adapter-and-global-safe-fallback.md": (
        "app/voice/adapter.py",
        "app/main.py",
        "app/core/config.py",
    ),
}


def test_adr_index_and_files_exist_with_minimum_line_counts() -> None:
    """Verify docs/adr/README.md and all 4 ADR files exist and have >= 40 lines each."""
    assert ADR_DIR.exists() and ADR_DIR.is_dir(), f"Missing ADR directory: {ADR_DIR}"

    readme_path = ADR_DIR / "README.md"
    assert readme_path.exists(), "Missing docs/adr/README.md index file"
    readme_text = readme_path.read_text(encoding="utf-8")
    assert len(readme_text.strip()) > 100

    for filename in EXPECTED_ADR_FILES:
        assert filename in readme_text, f"ADR index README.md does not link {filename}"
        adr_path = ADR_DIR / filename
        assert adr_path.exists(), f"Missing ADR file: {adr_path}"
        lines = adr_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 40, f"{filename} has only {len(lines)} lines (expected >= 40)"


@pytest.mark.parametrize("filename", EXPECTED_ADR_FILES)
def test_adr_contains_required_sections_and_production_status(filename: str) -> None:
    """Verify each ADR contains Status, Context, Decision, Consequences, and SLO sections."""
    adr_path = ADR_DIR / filename
    content = adr_path.read_text(encoding="utf-8")

    assert "Accepted — Production Baseline" in content, (
        f"{filename} missing 'Accepted — Production Baseline' status"
    )
    for section_keyword in REQUIRED_SECTIONS:
        assert section_keyword in content, (
            f"{filename} missing required section keyword: {section_keyword}"
        )


@pytest.mark.parametrize("filename", EXPECTED_ADR_FILES)
def test_adr_references_existing_repository_modules(filename: str) -> None:
    """Verify each ADR references actual existing code modules in the repository."""
    adr_path = ADR_DIR / filename
    content = adr_path.read_text(encoding="utf-8")

    for module_rel_path in EXPECTED_MODULE_REFERENCES[filename]:
        assert module_rel_path in content, (
            f"{filename} must reference repository module '{module_rel_path}'"
        )
        full_module_path = PROJECT_ROOT / module_rel_path
        assert full_module_path.exists(), (
            f"Referenced module '{module_rel_path}' does not exist at {full_module_path}"
        )
