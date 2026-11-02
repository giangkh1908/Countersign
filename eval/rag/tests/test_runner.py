"""Runner và CLI với retriever giả; không cần Postgres hay gateway."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from acme_common.ports import Principal
from mcp_docs.ports import DocumentRetriever, RetrievedChunk, SearchResult

from eval.rag import __main__ as cli
from eval.rag import backends, runner
from eval.rag.dataset import Question
from eval.rag.fakes import CorpusFakeRetriever, eval_principal


def _chunk(doc: str, art: str, i: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=i, doc_id=doc, title=doc, heading=None, source=f"{doc}#{i}", ord=i,
        department="ALL", classification=0, allowed_roles=(), content="x", doc_num=doc, article=art,
    )  # fmt: skip


class ScriptedRetriever(DocumentRetriever):
    """Trả danh sách (doc, article) đã định sẵn, theo câu hỏi."""

    def __init__(self, script: dict[str, list[tuple[str, str]]]) -> None:
        self.script = script
        self.closed = False

    async def search(
        self, query: str, principal: Principal, k: int, department_filter: str | None = None
    ) -> SearchResult:
        keys = self.script.get(query, [])
        return SearchResult([_chunk(d, a, i) for i, (d, a) in enumerate(keys)][:k])

    async def aclose(self) -> None:
        self.closed = True


QS = [
    Question("q1", "hỏi 1", (("d", "1"),)),
    Question("q2", "hỏi 2", (("d", "2"), ("d", "3")), type="synthesis"),
    Question("q3", "hỏi 3", (), type="unanswerable", answerable=False),
]


async def test_run_config_cham_dung_va_bo_qua_cau_khong_dap_an():
    r = ScriptedRetriever(
        {"hỏi 1": [("d", "9"), ("d", "1")], "hỏi 2": [("d", "2"), ("d", "2"), ("d", "7")]}
    )
    res = await runner.run_config("hybrid", r, QS, eval_principal())
    assert [x.id for x in res.results] == ["q1", "q2"]  # q3 bị bỏ
    q1, q2 = res.results
    assert q1.scores["mrr"] == 0.5 and q1.scores["recall@1"] == 0.0 and q1.scores["recall@3"] == 1.0
    assert q2.scores["recall@10"] == 0.5 and q2.ranked == [("d", "2"), ("d", "7")]
    agg = res.aggregate()
    assert agg["n"] == 2 and agg["mrr"] == pytest.approx((0.5 + 1.0) / 2)
    assert set(res.by_type()) == {"lookup", "synthesis"}


async def test_run_all_dong_retriever_va_goi_du_4_cau_hinh():
    built: list[ScriptedRetriever] = []

    def factory(name: str) -> DocumentRetriever:
        r = ScriptedRetriever({"hỏi 1": [("d", "1")]})
        built.append(r)
        return r

    out = await runner.run_all(factory, QS[:1], eval_principal())
    assert list(out) == list(runner.CONFIGS)
    assert len(built) == len(runner.CONFIGS) and all(r.closed for r in built)
    assert all(r.aggregate()["recall@5"] == 1.0 for r in out.values())


async def test_corpus_fake_chay_duoc_va_tra_dieu_co_that(raw: Path):
    r = CorpusFakeRetriever(raw, "hybrid")
    found = await r.search("nghỉ phép năm bao nhiêu ngày", eval_principal(), 5)
    assert found.chunks and all(c.doc_num and c.article for c in found.chunks)
    assert found.chunks[0].article == "113"


async def test_corpus_fake_direct_lookup(raw: Path):
    r = CorpusFakeRetriever(raw, "hybrid_direct")
    found = await r.search("Nội dung Điều 23 của 20/2023/QH15 là gì?", eval_principal(), 3)
    assert (found.chunks[0].doc_num, found.chunks[0].article) == ("20/2023/QH15", "23")


def test_corpus_fake_mode_la():
    with pytest.raises(ValueError):
        CorpusFakeRetriever(Path("."), "bm25")


def test_real_factory_bao_loi_ro_khi_settings_chua_co_cong_tac():
    from mcp_docs.settings import Settings

    if {"docs_use_vector", "docs_use_fts", "docs_direct_lookup"} <= set(Settings.model_fields):
        pytest.skip("Settings đã có công tắc hybrid")
    with pytest.raises(backends.UnsupportedConfig, match="DOCS_USE_VECTOR"):
        backends.real_factory(Settings())


def test_cli_run_fake_ghi_bao_cao_co_phien_ban_index(
    raw: Path, tmp_path: Path, capsys, write_suite
):
    suite = write_suite(
        tmp_path / "s.jsonl",
        [
            {"id": "q1", "question": "nghỉ phép năm bao nhiêu ngày", "gold": [{"doc_num": "45/2019/QH14", "article": "113"}]},
            {"id": "q2", "question": "chữ ký số có giá trị như chữ ký tay không", "gold": [{"doc_num": "20/2023/QH15", "article": "23"}]},
        ],
    )  # fmt: skip
    out = tmp_path / "out"
    code = cli.main(
        ["run", "--fake", "--suite", str(suite), "--raw-dir", str(raw), "--out", str(out)]
    )
    assert code == 0
    printed = capsys.readouterr().out
    for label in runner.CONFIG_LABELS.values():
        assert label in printed
    [report_path] = list(out.glob("*/report.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["fake"] is True and report["dataset"]["n"] == 2
    assert report["versions"] == {"embed_model": "fake_hash", "embed_dim": 256, "index_sig": "fake"}
    assert set(report["configs"]) == set(runner.CONFIGS)
    assert report["configs"]["hybrid"]["metrics"]["n"] == 2


def test_cli_nhan_sai_thi_khong_chay(raw: Path, tmp_path: Path, capsys, write_suite):
    suite = write_suite(
        tmp_path / "s.jsonl",
        [{"id": "q1", "question": "x", "gold": [{"doc_num": "45/2019/QH14", "article": "999"}]}],
    )
    code = cli.main(
        [
            "run",
            "--fake",
            "--suite",
            str(suite),
            "--raw-dir",
            str(raw),
            "--out",
            str(tmp_path / "o"),
        ]
    )
    assert code == 1
    assert "không có Điều 999" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_cli_validate(raw: Path, tmp_path: Path, capsys, write_suite):
    suite = write_suite(
        tmp_path / "s.jsonl",
        [{"id": "q1", "question": "x", "gold": [{"doc_num": "45/2019/QH14", "article": "46"}]}],
    )
    assert cli.main(["validate", "--suite", str(suite), "--raw-dir", str(raw)]) == 0
    assert "OK: 1 câu" in capsys.readouterr().out


def test_overrides_tao_duoc_settings_hop_le():
    """Hồi quy: `docs_direct_lookup` là str off|pin; bool từng làm Settings ném ValidationError."""
    from mcp_docs.settings import Settings

    for name in runner.CONFIGS:
        s = Settings(**{**Settings().model_dump(), **backends.OVERRIDES[name]})
        assert s.docs_direct_lookup == ("pin" if name == "hybrid_direct" else "off")
    assert Settings(**backends.OVERRIDES["fts_segmented"]).docs_fts_mode == "segmented"


async def test_pinning_retriever_ghim_dieu_nen_trong_cau_hoi():
    from dataclasses import replace

    from mcp_docs.testing import FakeArticleReader, FakeRetriever, make_chunk

    def law(i: int, article: str):
        return replace(
            make_chunk(i, "ALL", 0),
            title="Bộ luật Lao động",
            doc_num="45/2019/QH14",
            article=article,
        )

    target = law(10, "38")
    inner = FakeRetriever([make_chunk(1, "ALL", 0), make_chunk(2, "ALL", 0)])
    r = backends.PinningRetriever(inner, FakeArticleReader([target, law(11, "5")]))
    found = await r.search("Điều 38 Bộ luật Lao động quy định gì", eval_principal(), 3)
    assert [c.chunk_id for c in found.chunks] == [10, 1, 2]
    # không nêu Điều thì giữ nguyên kết quả của retriever bên trong
    plain = await r.search("nghỉ phép năm", eval_principal(), 3)
    assert [c.chunk_id for c in plain.chunks] == [1, 2]
