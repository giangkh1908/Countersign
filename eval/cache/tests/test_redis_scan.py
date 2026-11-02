from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "e2e"))
import leak_check as lc  # noqa: E402

from eval.cache.redis_scan import parse_key, scan_entries  # noqa: E402

SHA = "a" * 64


def key(dept: str, clr: str, roles: str) -> str:
    return f"cache:v1:0:{dept}:{clr}:{roles}:mock.acme-fast:{SHA}"


DOCS = [
    lc.Doc("doc-hr-1", "Quy chế thưởng HR", "HR", 3, [], "vân tay tuyệt mật của HR số một"),
    lc.Doc("doc-all-1", "Nội quy chung", "ALL", 0, [], "vân tay nội quy chung công khai"),
]


def entry(text: str) -> str:
    return json.dumps({"content": text, "finish_reason": "stop"}, ensure_ascii=False)


def test_parse_key_tach_pham_vi() -> None:
    s = parse_key(key("CS,IT", "1", "employee,team_lead"))
    assert s is not None
    assert s.dept == {"CS", "IT"} and s.clearance == 1 and s.roles == {"employee", "team_lead"}
    assert parse_key("cache:v1:khong-du-phan") is None
    assert parse_key("other:v1:0:A:1:r:m:" + SHA) is None


def test_phat_hien_ro_ri_cheo_pham_vi() -> None:
    entries = {
        key("SALES", "1", "employee"): entry("trả lời có vân tay tuyệt mật của HR số một"),
        key("HR", "3", "employee"): entry("vân tay tuyệt mật của HR số một"),  # được phép
        key("SALES", "1", "employee").replace("aaaa", "bbbb"): entry("Quy chế thưởng HR"),
    }
    res = scan_entries(entries, DOCS, lc)
    assert res.keys == 3
    assert [d for _, d in res.hard] == ["doc-hr-1"]  # chỉ khoá SALES chứa vân tay HR
    assert [d for _, d in res.title] == ["doc-hr-1"]
    assert res.with_allowed_trace == 1  # khoá HR chứa dấu vết tài liệu của chính phạm vi


def test_khong_ro_ri_voi_noi_dung_sach() -> None:
    res = scan_entries({key("SALES", "1", "employee"): entry("xin chào")}, DOCS, lc)
    assert res.leaks == 0 and res.malformed == 0
