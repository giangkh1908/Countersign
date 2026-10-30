"""Test offline cho generator ACME: tất định, số lượng, tham chiếu user khớp realm Keycloak."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from data.generator.build import SEED, build
from data.generator.users import DEFAULT_REALM, load_users


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("gen") / "out"
    build(d)
    return d


def test_deterministic(tmp_path):
    m1 = build(tmp_path / "a", seed=SEED)
    m2 = build(tmp_path / "b", seed=SEED)
    assert m1 == m2
    for rel in m1["files"]:
        assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes()


def test_seed_changes_output(tmp_path):
    assert build(tmp_path / "a", seed=1)["files"] != build(tmp_path / "b", seed=2)["files"]


def test_counts(out):
    c = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["counts"]
    assert c["documents"] == 30
    assert c["tickets"] == 100
    assert c["users"] == 16
    assert c["customers"] == 40 and c["orders"] == 300


def _docs(out):
    return [json.loads(line) for line in (out / "documents.jsonl").read_text("utf-8").splitlines()]


def test_documents_acl_mix(out):
    docs = _docs(out)
    assert {d["classification"] for d in docs} == {0, 1, 2, 3}
    assert {d["department"] for d in docs} == {"ALL", "SALES", "HR"}
    for d in docs:
        text = (out / d["source_path"]).read_text(encoding="utf-8")
        canaries = re.findall(r"ACME-CANARY-[A-Z]+-\d{4}", text)
        assert len(canaries) == (1 if d["classification"] >= 2 else 0)
        assert d["department"] != "ALL" or d["classification"] <= 1
    assert len({d["id"] for d in docs}) == 30


def test_users_exist_in_realm(out):
    realm = json.loads(DEFAULT_REALM.read_text(encoding="utf-8"))
    ids = {u["id"] for u in realm["users"]}
    subs = {u.sub for u in load_users()}
    assert subs == ids  # sub = `id` cố định trong realm
    for d in _docs(out):
        assert d["owner_sub"] in subs
    sql = (out / "sql" / "tickets.sql").read_text(encoding="utf-8")
    used = set(re.findall(r"'([a-z]+\.[a-z]+)'", sql))
    assert used <= names
    assert used  # có tham chiếu user


def test_ticket_distribution(out):
    sql = (out / "sql" / "tickets.sql").read_text(encoding="utf-8")
    for status in ("open", "in_progress", "resolved", "closed"):
        assert f"'{status}'" in sql
    assert "'SALES'" in sql and "'HR'" in sql


def test_sub_map_applied(tmp_path):
    users = load_users(sub_map={"an.nguyen": "11111111-1111-1111-1111-111111111111"})
    assert next(u for u in users if u.username == "an.nguyen").sub.startswith("1111")
    m = build(tmp_path / "x", sub_map={"an.nguyen": "11111111-1111-1111-1111-111111111111"})
    assert m["counts"]["tickets"] == 100
