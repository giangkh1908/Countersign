"""Migration knowledge: cặp up/down đủ, compose nối đúng thứ tự, runner dùng bảng và role theo hợp đồng."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
MIG = ROOT / "infra/postgres/migrations/knowledge"
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def _versions(kind: str) -> set[str]:
    return {p.name.removesuffix(f".{kind}.sql") for p in MIG.glob(f"*.{kind}.sql")}


def test_every_migration_has_up_and_down() -> None:
    assert _versions("up") == _versions("down") != set()
    assert all(re.fullmatch(r"\d{4}_[a-z0-9_]+", v) for v in _versions("up"))


def test_knowledge_migrate_runs_before_docs_mcp() -> None:
    job = COMPOSE["knowledge-migrate"]
    assert job["restart"] == "no"
    assert job["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert job["environment"]["PGUSER"] == "kn_owner"
    assert job["secrets"] == ["kn_owner_password"]
    deps = COMPOSE["docs-mcp"]["depends_on"]
    assert deps["knowledge-migrate"]["condition"] == "service_completed_successfully"


def test_embed_dim_shared_between_job_and_docs_mcp() -> None:
    default = "${EMBED_DIM:-1024}"
    assert COMPOSE["knowledge-migrate"]["environment"]["EMBED_DIM"] == default
    assert COMPOSE["docs-mcp"]["environment"]["DOCS_EMBED_DIM"] == default
    assert "EMBED_DIM=1024" in (ROOT / ".env.example").read_text(encoding="utf-8")


def test_embedding_migration_guards_dimension_change() -> None:
    for kind in ("up", "down"):
        sql = (MIG / f"0002_embedding_dim.{kind}.sql").read_text(encoding="utf-8")
        assert "migrate.force" in sql and "TRUNCATE chunks" in sql
        assert (
            len(re.findall(r"(?<!NO )FORCE ROW LEVEL SECURITY", sql)) == 2
        )  # bật lại chunks + documents
