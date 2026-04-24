from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_docs_match_public_routes_and_env_keys() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (PROJECT_ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    required_routes = [
        "POST /api/after-sales/runs",
        "POST /api/after-sales/runs/stream",
        "POST /api/after-sales/actions",
        "GET /api/after-sales/runs/{run_id}",
        "GET /api/after-sales/audit-logs?run_id=...",
    ]
    required_env_keys = [
        "LLM_PROVIDER",
        "LLM_MODEL",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "BUSINESS_DATABASE_URL",
        "AGENT_RUNTIME_DATABASE_URL",
    ]

    for route in required_routes:
        assert route in readme
        assert route in architecture

    for key in required_env_keys:
        assert key in readme
        assert key in architecture
        assert key in env_example


def test_architecture_doc_exists() -> None:
    assert (PROJECT_ROOT / "docs" / "ARCHITECTURE.md").exists()
