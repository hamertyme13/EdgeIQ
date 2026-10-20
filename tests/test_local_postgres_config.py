from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_local_postgres_is_loopback_only_and_persistent() -> None:
    compose = (ROOT / "compose.postgres.yml").read_text(encoding="utf-8")
    assert '127.0.0.1:${EDGEIQ_LOCAL_POSTGRES_PORT:-55432}:5432' in compose
    assert "edgeiq-postgres-data:/var/lib/postgresql/data" in compose
    assert "condition: service_healthy" in compose


def test_local_credential_is_not_packaged_or_committed() -> None:
    name = ".edgeiq_local_postgres.env"
    assert name in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert name in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
