"""Canary tài liệu mật không lọt ra response/log/audit khi người dùng không đủ quyền (trong-process).

Quét 16 user thật của realm x mọi câu hỏi (tiêu đề, truy vấn, chính chuỗi canary) trên corpus gồm
seed ACME (sinh tạm) + corpus độc. Chạy cả khi retriever "rò" (không lọc ACL): service phải lọc lại.
"""

from __future__ import annotations

import json
import logging
import re

import pytest
from mcp_docs.services.acl import AclPolicy

from data.generator.build import build as build_seed
from data.generator.users import load_users
from data.poison.build import build as build_poison
from eval.attack.fakes import KeywordRetriever, load_chunks
from eval.attack.harness import CONFIGS, World

pytestmark = pytest.mark.security

CANARY = re.compile(r"(?:ACME|ATK)-CANARY-[A-Z]+-\d{4}")


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    root = tmp_path_factory.mktemp("canary")
    build_seed(root / "seed")
    build_poison(root / "poison")
    return load_chunks(root / "seed") + load_chunks(root / "poison")


def _canary_owner(store):
    """canary -> (department, classification, allowed_roles) lấy từ chunk chứa nó."""
    out = {}
    for c in store:
        for k in CANARY.findall(c.content):
            out[k] = (c.department, c.classification, c.allowed_roles)
    return out


def test_corpus_has_canaries(store) -> None:
    owners = _canary_owner(store)
    assert len(owners) >= 10  # 5 của seed (c2/c3) + canary corpus độc


@pytest.mark.parametrize("leaky_retriever", [False, True], ids=["acl_adapter", "acl_service_only"])
async def test_no_canary_beyond_clearance(store, caplog, leaky_retriever) -> None:
    owners = _canary_owner(store)
    queries = sorted(
        {c.title for c in store if CANARY.search(c.content)} | {k.lower() for k in owners}
    )  # truy vấn là canary viết thường: echo truy vấn không tính là rò
    queries += ["mã tham chiếu kiểm soát", "lương thưởng", "nâng cấp hạ tầng", "tối mật"]
    caplog.set_level(logging.DEBUG)
    visible_total = 0
    for user in load_users():
        seen = ""
        for i in range(0, len(queries), 10):  # World mới mỗi 10 truy vấn để không chạm rate limit
            w = World(store, CONFIGS["none"], user)
            if leaky_retriever:
                w.docs._retriever = KeywordRetriever(store, enforce_acl=False)
            for q in queries[i : i + 10]:
                res = await w.call(
                    w.h_docs, "docs-mcp", "search_documents", {"query": q, "top_k": 10}
                )
                assert not res.is_error, res.data
                seen += json.dumps(dict(res.data), ensure_ascii=False)
            seen += json.dumps(w.docs_sink.events, ensure_ascii=False, default=str)  # audit/usage
        p = w.principal("docs-mcp")
        allowed = {
            k for k, (d, cls, roles) in owners.items() if AclPolicy.can_read(p, d, cls, roles)
        }
        forbidden = set(owners) - allowed
        seen += caplog.text
        leaked = [k for k in forbidden if k in seen]
        assert not leaked, f"{user.username} thấy canary trái quyền: {leaked}"
        visible_total += sum(1 for k in allowed if k in seen)
        caplog.clear()
    assert visible_total > 0  # kiểm tra không rỗng: người có quyền vẫn thấy canary của mình
