import hashlib
import json
from pathlib import Path

import pytest
from mcp_docs.adapters.fake_hash import FakeHashEmbedder
from mcp_docs.adapters.markdown import MarkdownLoader
from mcp_docs.ingest.job import load_metadata, run_ingest
from mcp_docs.ports import DocumentRejected, EmbeddingUnavailable
from mcp_docs.testing import FailingEmbedder, FakeIndexer

BODY = "# Quy chế\n\n## Nghỉ phép\n\n" + "Nhân viên được nghỉ phép năm. " * 30 + "\n"


def make_corpus(tmp: Path, **override) -> Path:
    (tmp / "corpus" / "HR").mkdir(parents=True)
    f = tmp / "corpus" / "HR" / "a.md"
    f.write_text(BODY, encoding="utf-8")
    rec = {
        "id": "11111111-1111-4111-8111-111111111111",
        "source_path": "corpus/HR/a.md",
        "title": "Quy chế nghỉ phép",
        "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
        "department": "HR",
        "classification": 2,
        "allowed_roles": ["dept_manager"],
        "owner_sub": "u1",
        "version": 1,
    }
    rec.update(override)
    rec = {k: v for k, v in rec.items() if v is not ...}
    (tmp / "documents.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    return tmp


async def ingest(corpus: Path, indexer: FakeIndexer, **kw):
    return await run_ingest(
        corpus,
        loader_for=lambda p: MarkdownLoader(),
        embedder=kw.pop("embedder", FakeHashEmbedder()),
        indexer=indexer,
        **kw,
    )


async def test_ingest_writes_chunks_with_acl_and_1024_dim(tmp_path: Path) -> None:
    idx = FakeIndexer()
    rep = await ingest(make_corpus(tmp_path), idx)
    assert rep.ingested == ["corpus/HR/a.md"] and rep.chunks >= 1
    meta, chunks = idx.docs["11111111-1111-4111-8111-111111111111"]
    assert (meta.department, meta.classification, meta.allowed_roles) == (
        "HR",
        2,
        ("dept_manager",),
    )
    assert all(len(c.embedding) == 1024 for c in chunks)
    assert [c.chunk.ord for c in chunks] == list(range(len(chunks)))


async def test_ingest_is_idempotent_and_reingests_on_change(tmp_path: Path) -> None:
    corpus = make_corpus(tmp_path)
    idx = FakeIndexer()
    await ingest(corpus, idx)
    again = await ingest(corpus, idx)
    assert again.ingested == [] and again.skipped == ["corpus/HR/a.md"]
    forced = await ingest(corpus, idx, force=True)
    assert forced.ingested == ["corpus/HR/a.md"]
    (corpus / "corpus" / "HR" / "a.md").write_text(BODY + "\nThêm một dòng.\n", encoding="utf-8")
    changed = await ingest(corpus, idx)
    assert changed.ingested == ["corpus/HR/a.md"]  # sha256 thật của file đổi, bất kể metadata cũ


async def test_acl_change_triggers_reingest(tmp_path: Path) -> None:
    idx = FakeIndexer()
    await ingest(make_corpus(tmp_path), idx)
    make_corpus_acl = json.loads((tmp_path / "documents.jsonl").read_text())
    make_corpus_acl["classification"] = 3
    (tmp_path / "documents.jsonl").write_text(json.dumps(make_corpus_acl) + "\n")
    rep = await ingest(tmp_path, idx)
    assert rep.ingested == ["corpus/HR/a.md"]
    assert next(iter(idx.docs.values()))[0].classification == 3


@pytest.mark.parametrize(
    "override",
    [
        {"department": ...},
        {"classification": ...},
        {"allowed_roles": ...},
        {"classification": 4},
        {"classification": "2"},
        {"department": "hr"},
        {"id": "not-a-uuid"},
        {"allowed_roles": "dept_manager"},
        {"source_path": "../escape.md"},
    ],
)
async def test_bad_or_missing_acl_metadata_fails_closed(tmp_path: Path, override) -> None:
    idx = FakeIndexer()
    with pytest.raises(DocumentRejected):
        await ingest(make_corpus(tmp_path, **override), idx)
    assert idx.docs == {}


async def test_embedding_failure_stops_without_partial_write(tmp_path: Path) -> None:
    idx = FakeIndexer()
    with pytest.raises(EmbeddingUnavailable):
        await ingest(make_corpus(tmp_path), idx, embedder=FailingEmbedder())
    assert idx.docs == {}


def test_load_metadata_requires_file(tmp_path: Path) -> None:
    with pytest.raises(DocumentRejected):
        load_metadata(tmp_path)


class _NamedEmbedder(FakeHashEmbedder):
    """Embedder tất định mang id model tuỳ ý (mô phỏng gateway đổi model sau cùng một alias)."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    @property
    def model_id(self) -> str:
        return self._name


async def test_model_change_behind_same_alias_reingests_without_force(tmp_path: Path) -> None:
    corpus, idx = make_corpus(tmp_path), FakeIndexer()
    assert (await ingest(corpus, idx, embedder=_NamedEmbedder("mock-hash-1024"))).ingested
    assert (await ingest(corpus, idx, embedder=_NamedEmbedder("mock-hash-1024"))).ingested == []
    rep = await ingest(corpus, idx, embedder=_NamedEmbedder("bge-m3"))  # không force
    assert rep.ingested and rep.chunks >= 1
    assert idx.index_meta["embed_model"] == "bge-m3"


async def test_index_sig_change_triggers_reingest_and_fts_text_is_stored(tmp_path: Path) -> None:
    from mcp_docs.adapters.segmenter_none import NoSegmenter
    from mcp_docs.adapters.segmenter_syllable_bigram import SyllableBigramSegmenter

    corpus, idx = make_corpus(tmp_path), FakeIndexer()
    base = {"segmenter": SyllableBigramSegmenter(), "embedder": _NamedEmbedder("m1")}
    assert (await ingest(corpus, idx, **base)).ingested
    chunks = next(iter(idx.docs.values()))[1]
    assert all(c.fts_text and c.fts_text.split()[0].islower() for c in chunks)
    assert (await ingest(corpus, idx, **base)).ingested == []
    for kw in (
        {"embedder": _NamedEmbedder("m2")},
        {"segmenter": NoSegmenter()},
        {"article_max_tokens": 300},
    ):
        assert (await ingest(corpus, idx, **(base | kw))).ingested, kw
        assert (await ingest(corpus, idx, **base)).ingested  # đổi lại cũng nạp lại
    assert idx.index_meta["embed_model"] == "m1" and idx.index_meta["embed_dim"] == "1024"


class _LyingEmbedder(FakeHashEmbedder):
    """Khai báo 1024 chiều nhưng trả vector 8 chiều (gateway cấu hình lệch)."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 8 for _ in texts]


async def test_ingest_verifies_schema_and_probes_embedder(tmp_path: Path) -> None:
    from mcp_docs.ports import IndexConfigError

    idx = FakeIndexer()
    await ingest(make_corpus(tmp_path), idx)
    assert idx.verified_dim == 1024
    with pytest.raises(IndexConfigError, match="DOCS_EMBED_DIM"):
        await ingest(make_corpus(tmp_path / "b"), FakeIndexer(), embedder=_LyingEmbedder())
