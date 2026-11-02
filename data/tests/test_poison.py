"""Corpus độc: tất định, đủ số lượng/kỹ thuật, ground truth khớp tài liệu, nạp được bằng ingest sẵn có."""

from __future__ import annotations

import hashlib
from collections import Counter

import pytest
from mcp_docs.ingest.job import load_metadata

from data.generator.users import load_users
from data.poison.build import DEFAULT_OUT, VICTIMS, build, load_manifest
from data.poison.techniques import TECHNIQUES


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(DEFAULT_OUT)


def test_committed_corpus_matches_generator(tmp_path) -> None:
    build(tmp_path / "c")
    for f in ("documents.jsonl", "manifest.jsonl"):
        assert (tmp_path / "c" / f).read_bytes() == (DEFAULT_OUT / f).read_bytes(), f


def test_counts(manifest) -> None:
    poisoned = [r for r in manifest if r["kind"] == "poisoned"]
    assert len(poisoned) >= 50
    assert Counter(r["technique"] for r in poisoned) == {t: 7 for t in TECHNIQUES}
    assert sum(r["kind"] == "clean" for r in manifest) >= 5
    assert sum(r["kind"] == "secret" for r in manifest) >= 5


def test_ground_truth_fields(manifest) -> None:
    for r in manifest:
        if r["kind"] != "poisoned":
            continue
        for k in (
            "technique",
            "goal",
            "attacker_objective",
            "success_behavior",
            "department",
            "classification",
            "attack",
        ):
            assert r[k] not in (None, ""), (r["slug"], k)
        assert r["severity"] in ("harm", "nuisance")
        assert r["attack"]["tool"] in ("prepare_send_group_report", "prepare_create_ticket")
        assert r["classification"] <= 1  # tài liệu độc không tự mang mức mật cao


def test_victims_match_realm(manifest) -> None:
    users = {u.username: u for u in load_users()}
    for name, dept, _ in VICTIMS:
        assert dept in users[name].departments
    secrets = {r["slug"]: r for r in manifest if r["kind"] == "secret"}
    for name, _, secret in VICTIMS:
        u, s = users[name], secrets[secret]
        assert u.clearance >= s["classification"]
        assert s["department"] in u.departments
        assert not s["allowed_roles"] or set(s["allowed_roles"]) & set(u.roles)


def test_ingest_compatible(manifest) -> None:
    metas = load_metadata(DEFAULT_OUT)  # parse_meta fail-closed trên từng dòng
    assert len(metas) == len(manifest)
    for m in metas:
        data = (DEFAULT_OUT / m.source_path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == m.sha256


def test_no_real_data_markers(manifest) -> None:
    for r in manifest:
        text = (DEFAULT_OUT / r["source_path"]).read_text(encoding="utf-8")
        assert "@" not in text.replace("@A@", "")  # không email
        assert "http" not in text or ".invalid" in text or ".example" in text
