"""Step 11 Delivery Verification Suite: Verifies Capstone README and Defense Documentation."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
README_PATH = PROJECT_ROOT / "README.md"
DEMO_PATH = PROJECT_ROOT / "docs" / "DEMO_SCRIPT_AND_LIMITATIONS.md"


def test_root_readme_comprehensive_and_contains_required_sections() -> None:
    """Verify README.md exists, has >= 120 lines, and covers all required DEPI elements."""
    assert README_PATH.is_file(), "README.md must exist in root"
    lines = README_PATH.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 120, f"README.md should be >= 120 lines, found {len(lines)}"

    content = "\n".join(lines)

    # 4 Pillars check
    for pillar in ("Pillar 1", "Pillar 2", "Pillar 3", "Pillar 4"):
        assert pillar in content, f"Missing {pillar} in README.md"

    # SLO-01 through SLO-08 check
    for i in range(1, 9):
        slo_tag = f"SLO-0{i}"
        assert slo_tag in content, f"Missing {slo_tag} in README.md"

    # Endpoints & Key tools check
    for item in (
        "/api/v1/triage",
        "/api/v1/traceability/",
        "/api/v1/escalations/stream",
        "docker compose",
        "docs/adr/",
        "docs/DEMO_SCRIPT_AND_LIMITATIONS.md",
    ):
        assert item in content, f"Missing {item} reference in README.md"


def test_demo_script_and_limitations_exists_and_complete() -> None:
    """Verify docs/DEMO_SCRIPT_AND_LIMITATIONS.md exists, has >= 80 lines, and covers all scenarios."""
    assert DEMO_PATH.is_file(), "docs/DEMO_SCRIPT_AND_LIMITATIONS.md must exist"
    lines = DEMO_PATH.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 80, f"Demo script should be >= 80 lines, found {len(lines)}"

    content = "\n".join(lines)

    # Check 4 scenarios
    assert "Scenario 1" in content and "Traceability" in content
    assert "Scenario 2" in content and "Max-3-Turns" in content
    assert "Scenario 3" in content and "Red-Flag" in content
    assert "Scenario 4" in content and ("Adversarial" in content or "Prescription" in content)

    # Check system limitations
    assert "Clinical Limitations" in content
    assert "Architectural Limitations" in content
    assert "Operational & Security Limitations" in content or "Operational" in content


def test_all_referenced_documentation_and_workflow_files_exist() -> None:
    """Verify all key files and architecture documents referenced in README.md exist on disk."""
    required_paths = [
        PROJECT_ROOT / "Dockerfile",
        PROJECT_ROOT / "docker-compose.yml",
        PROJECT_ROOT / ".env.example",
        PROJECT_ROOT / ".github" / "workflows" / "ci.yml",
        PROJECT_ROOT / "docs" / "adr" / "README.md",
        PROJECT_ROOT / "docs" / "DEMO_SCRIPT_AND_LIMITATIONS.md",
        PROJECT_ROOT / "app" / "agent" / "session_store.py",
        PROJECT_ROOT / "app" / "core" / "sse.py",
        PROJECT_ROOT / "app" / "voice" / "adapter.py",
    ]
    for path in required_paths:
        assert path.exists(), f"Referenced file does not exist: {path}"
