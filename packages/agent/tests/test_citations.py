"""Trích dẫn kiểm chứng được (R2): resolver, tách câu, verifier, adapter judge và luồng qua API/SSE."""

from __future__ import annotations

import json

import pytest
from agent.adapters.gateway_llm import GatewayLlmSupportJudge
from agent.factory import build_support_judge
from agent.ports.errors import SupportJudgeNotConfigured
from agent.services.answer import REFUSAL_TEXT, build_answer
from agent.services.citation_verifier import CitationVerifier, VerifyConfig, locate_quote
from agent.services.citations import CitationResolver, Passage
from agent.services.sentences import split_sentences
from agent.settings import Settings
from agent.testing import (
    AUTH,
    FakeSupportJudge,
    FakeToolProvider,
    ScriptedChatModel,
    route,
    tool_call,
)
from langchain_core.messages import AIMessage

P11 = "Người lao động nghỉ phép năm 12 ngày làm việc. Thời gian nghỉ được tính lương."
P12 = "Thử việc không quá 60 ngày đối với chức danh cần trình độ cao đẳng."


def passages() -> dict[str, Passage]:
    return {
        "11": Passage(
            chunk_id=11,
            doc_id="d1",
            doc_num="45/2019/QH14",
            article="113",
            char_start=1000,
            char_end=1000 + len(P11),
            text=P11,
            title="BLLĐ",
        ),
        "12": Passage(
            chunk_id=12,
            doc_id="d1",
            doc_num="45/2019/QH14",
            article="25",
            char_start=500,
            char_end=565,
            text=P12,
            title="BLLĐ",
        ),
    }


SEARCH = {
    "results": [
        {
            "chunk_id": 11,
            "doc_id": "d1",
            "title": "BLLĐ",
            "heading": "Điều 113",
            "source": "d1#2",
            "doc_num": "45/2019/QH14",
            "article": "113",
            "char_start": 1000,
            "char_end": 1070,
            "text": P11,
            "content": "<<BEGIN>>x<<END>>",
        },
        {
            "chunk_id": 12,
            "doc_id": "d1",
            "title": "BLLĐ",
            "heading": "Điều 25",
            "source": "d1#1",
            "doc_num": "45/2019/QH14",
            "article": "25",
            "char_start": 500,
            "char_end": 565,
            "text": P12,
            "content": "<<BEGIN>>y<<END>>",
        },
    ]
}
EMPTY = {"results": []}


# ------------------------------------------------------------ resolver (5.1)
def test_resolver_drops_codes_outside_retrieved_and_renumbers() -> None:
    r = CitationResolver().resolve(
        "Nghỉ 12 ngày [#11]. Bịa đặt [#999]. Thử việc 60 ngày [#12].", passages()
    )
    assert r.text == "Nghỉ 12 ngày [1]. Bịa đặt. Thử việc 60 ngày [2]."
    assert r.order == [11, 12] and r.invalid_refs == 1


def test_resolver_ignores_ids_from_other_turn_or_thread() -> None:
    # `retrieved` chỉ chứa đoạn của lượt hiện tại: id của lượt/thread khác không có trong đó
    r = CitationResolver().resolve("Câu A [#12].", {"11": passages()["11"]})
    assert r.text == "Câu A." and r.order == [] and r.invalid_refs == 1


def test_resolver_leaves_text_unchanged_apart_from_codes() -> None:
    plain = "Điều 38 quy định như sau. Người lao động có quyền."
    assert CitationResolver().resolve(plain, passages()).text == plain


def test_resolver_numbers_by_first_appearance_and_multi_code() -> None:
    r = CitationResolver().resolve("B [#12]. A [#11][#12].", passages())
    assert r.text == "B [1]. A [2][1]." and r.order == [12, 11]


# ------------------------------------------------------------ tách câu (5.3.1)
def test_split_sentences_offsets_and_cites() -> None:
    t = "Nghỉ phép 12 ngày [1]. Thử việc tối đa 60 ngày [2].\nKhông tìm thấy gì thêm."
    ss = split_sentences(t)
    assert [t[s.start : s.end] for s in ss] == [
        "Nghỉ phép 12 ngày [1].",
        "Thử việc tối đa 60 ngày [2].",
        "Không tìm thấy gì thêm.",
    ]
    assert [s.cites for s in ss] == [[1], [2], []]
    assert [s.claim for s in ss] == [True, True, False]


def test_split_sentences_does_not_cut_article_refs_or_numbers() -> None:
    ss = split_sentences("Theo Điều 38. Người lao động được nghỉ theo 45/2019/QH14 và 1.000 ngày.")
    assert len(ss) == 1


def test_split_sentences_bullets_and_colon_intro() -> None:
    ss = split_sentences(
        "Các trường hợp sau:\n- Nghỉ việc riêng khi kết hôn [1].\n- Nghỉ tang lễ ba ngày [2]."
    )
    assert [s.claim for s in ss] == [False, True, True]
    assert ss[1].text.startswith("Nghỉ việc riêng")


# ------------------------------------------------------------ verifier (5.3)
def test_locate_quote_ignores_whitespace_diffs() -> None:
    assert locate_quote("a  b\nc d", "b c") == (3, 6)
    assert locate_quote("a b", "x") is None and locate_quote("a b", "") is None


async def run_answer(draft: str, judge: FakeSupportJudge, **cfg):
    c = VerifyConfig(**cfg)
    return await build_answer(draft, passages(), CitationVerifier(judge, c), c)


async def test_supported_answer_has_evidence_and_verdicts() -> None:
    ans = await run_answer("Nghỉ phép năm 12 ngày làm việc [#11].", FakeSupportJudge())
    assert ans.answer_status == "answered" and ans.text == "Nghỉ phép năm 12 ngày làm việc [1]."
    it = ans.items[0]
    assert it["n"] == 1 and it["verdict"] == "supported" and it["sentence_ids"] == [0]
    assert it["evidence_start"] == 1000 and it["evidence_end"] == 1030  # char_start + vị trí quote
    assert ans.sentences == [
        {"id": 0, "start": 0, "end": len(ans.text), "cites": [1], "verdict": "supported"}
    ]
    assert ans.verify["judge_calls"] == 1 and ans.verify["input_tokens"] == 100


async def test_supported_without_real_quote_is_downgraded_to_partial() -> None:
    class BadQuote(FakeSupportJudge):
        async def judge(self, sentence, passage):
            v = await super().judge(sentence, passage)
            return v.model_copy(update={"evidence_quote": "không có trong đoạn"})

    ans = await run_answer(
        "Nghỉ phép năm 12 ngày [#11]. Thử việc 60 ngày [#12].", BadQuote(), min_supported_ratio=0.0
    )
    assert {s["verdict"] for s in ans.sentences} == {"partial"}
    assert ans.verify["evidence_mismatch"] == 2 and ans.answer_status == "partially_verified"


async def test_uncited_claim_is_unsupported_and_flagged() -> None:
    ans = await run_answer(
        "Nghỉ phép năm 12 ngày [#11]. Còn nghỉ lễ thì khác nhiều lắm.",
        FakeSupportJudge(),
        min_supported_ratio=0.5,
    )
    assert [s["verdict"] for s in ans.sentences] == ["supported", "unsupported"]
    assert ans.answer_status == "partially_verified"


async def test_drop_removes_unsupported_and_renumbers() -> None:
    judge = FakeSupportJudge(rules=[("Thử việc", "unsupported")])
    ans = await run_answer(
        "Thử việc 60 ngày [#12]. Nghỉ phép năm 12 ngày làm việc [#11]. Thêm chuyện không nguồn gốc.",
        judge,
        on_unsupported="drop",
        min_supported_ratio=0.3,
    )
    assert ans.text == "Nghỉ phép năm 12 ngày làm việc [1]."
    assert [i["doc_id"] for i in ans.items] == ["d1"] and ans.items[0]["article"] == "113"
    assert ans.sentences[0]["start"] == 0 and ans.sentences[0]["end"] == len(ans.text)
    assert ans.items[0]["sentence_ids"] == [0] and ans.verify["dropped_sentences"] == 2


async def test_refuse_when_all_unsupported_or_low_ratio() -> None:
    ans = await run_answer("Thử việc 60 ngày [#12].", FakeSupportJudge(default="unsupported"))
    assert ans.answer_status == "refused" and ans.text == REFUSAL_TEXT and ans.items == []
    ans = await run_answer(
        "Nghỉ phép năm 12 ngày [#11]. Thử việc 60 ngày [#12]. Thêm chuyện thứ ba hoàn toàn khác.",
        FakeSupportJudge(rules=[("Thử việc", "unsupported")]),
        min_supported_ratio=0.9,
    )
    assert ans.answer_status == "refused"


async def test_judge_failure_gives_unverified_never_supported() -> None:
    ans = await run_answer("Nghỉ phép năm 12 ngày [#11].", FakeSupportJudge(fail=True))
    assert ans.sentences[0]["verdict"] == "unverified" and ans.verify["judge_errors"] == 1
    assert ans.answer_status == "partially_verified" and ans.items[0]["verdict"] == "unverified"


async def test_max_pairs_caps_judge_calls() -> None:
    j = FakeSupportJudge()
    ans = await run_answer("Nghỉ phép năm 12 ngày [#11]. Thử việc 60 ngày [#12].", j, max_pairs=1)
    assert len(j.calls) == 1 and ans.sentences[1]["verdict"] == "unverified"


async def test_verifier_off_keeps_citations_unverified() -> None:
    ans = await build_answer("Nghỉ phép năm 12 ngày [#11].", passages(), None, VerifyConfig())
    assert ans.verify["enabled"] is False and ans.sentences == []
    assert ans.items[0]["verdict"] == "unverified" and ans.answer_status == "answered"


# ------------------------------------------------------------ adapter judge (JSON có cấu trúc)
def chat_with(*msgs: str) -> ScriptedChatModel:
    from collections import deque

    return ScriptedChatModel(queue=deque(AIMessage(m) for m in msgs))


async def test_gateway_judge_parses_json_and_unmarks_quote() -> None:
    j = GatewayLlmSupportJudge(
        chat_with(
            'Kết quả: {"verdict": "supported", "evidence_quote": "nghỉ phép năm", "reason": "ok"}'
        )
    )
    v = await j.judge("Nghỉ phép năm 12 ngày.", P11)
    assert v.verdict == "supported" and v.evidence_quote == "nghỉ phép năm" and v.calls == 1


async def test_gateway_judge_retries_once_then_unverified() -> None:
    ok = '{"verdict": "partial", "evidence_quote": "", "reason": "x"}'
    v = await GatewayLlmSupportJudge(chat_with("không phải json", ok)).judge("c", "d")
    assert v.verdict == "partial" and v.calls == 2
    v = await GatewayLlmSupportJudge(chat_with("hỏng", '{"verdict": "tuyệt vời"}')).judge("c", "d")
    assert v.verdict == "unverified" and v.error == "invalid_json" and v.calls == 2


def test_judge_factory_registry() -> None:
    s = Settings(acme_env="test")
    assert isinstance(
        build_support_judge("gateway_llm", s, chat=chat_with()), GatewayLlmSupportJudge
    )
    with pytest.raises(SupportJudgeNotConfigured):
        build_support_judge("nope", s, chat=chat_with())


# ------------------------------------------------------------ luồng qua API/SSE
def scripts(draft: str) -> dict:
    return {
        "router": [route("docs")],
        "agent": [tool_call("search_documents", {"query": "nghi phep"}), AIMessage(draft)],
    }


def text_of(events) -> str:
    return "".join(d["text"] for e, d in events if e == "token")


async def test_flow_citations_event_and_history_keep_verification(make_env) -> None:
    env = make_env(
        FakeToolProvider({"search_documents": SEARCH}),
        scripts("Nghỉ phép năm 12 ngày làm việc [#11]. Chuyện khác không có nguồn nào cả."),
    )
    tid = await env.new_thread()
    events = await env.run(tid, "Nghỉ phép?")
    cit = next(d for e, d in events if e == "citations")
    assert cit["answer_status"] == "partially_verified" and cit["verify"]["enabled"] is True
    assert [s["verdict"] for s in cit["sentences"]] == ["supported", "unsupported"]
    final = text_of(events)
    assert final.startswith("Nghỉ phép năm 12 ngày làm việc [1].")
    assert all(0 <= s["start"] < s["end"] <= len(final) for s in cit["sentences"])
    # mô hình không được thấy `text` thô, chỉ thấy `content` đã spotlight và mã [#id]
    tool_msg = next(
        m
        for m in (await env.c.graph.aget_state({"configurable": {"thread_id": tid}})).values[
            "messages"
        ]
        if m.type == "tool"
    )
    assert '"text"' not in tool_msg.content and "[#11]" in tool_msg.content

    # hồi quy: nạp lại lịch sử vẫn đủ dữ liệu kiểm chứng
    r = await env.client.get(f"/v1/threads/{tid}/messages", headers=AUTH)
    ai = [m for m in r.json()["messages"] if m["role"] == "assistant"][-1]
    assert ai["content"] == final
    assert ai["answer_status"] == "partially_verified"
    assert ai["sentences"] == cit["sentences"] and ai["verify"]["enabled"] is True
    c0 = ai["citations"][0]
    for k in ("n", "passage", "char_start", "evidence_start", "evidence_end", "verdict"):
        assert k in c0
    assert (c0["n"], c0["verdict"], c0["char_start"], c0["evidence_start"]) == (
        1,
        "supported",
        1000,
        1000,
    )
    assert c0["passage"] == P11
    json.dumps(r.json())


async def test_flow_zero_passages_refuses_before_generation(make_env) -> None:
    env = make_env(FakeToolProvider({"search_documents": EMPTY}), scripts("KHÔNG ĐƯỢC SINH [#11]."))
    tid = await env.new_thread()
    events = await env.run(tid, "Gì đó?")
    assert text_of(events).startswith("Không tìm thấy trong tài liệu")
    cit = next(d for e, d in events if e == "citations")
    assert cit["answer_status"] == "refused" and cit["items"] == []
    assert [e for e, _ in events if e in ("done", "error")] == ["done"]
    assert len(env.c.chat_factory("t", "r")("agent").queue) == 1  # lượt sinh thứ hai không bị gọi
    r = await env.client.get(f"/v1/threads/{tid}/messages", headers=AUTH)
    assert [m for m in r.json()["messages"] if m["role"] == "assistant"][-1][
        "answer_status"
    ] == "refused"


async def test_flow_invalid_ref_is_removed_end_to_end(make_env) -> None:
    env = make_env(
        FakeToolProvider({"search_documents": SEARCH}),
        scripts("Nghỉ phép năm 12 ngày làm việc [#11][#999]."),
    )
    events = await env.run(await env.new_thread(), "Nghỉ phép?")
    assert text_of(events).strip() == "Nghỉ phép năm 12 ngày làm việc [1]."
    cit = next(d for e, d in events if e == "citations")
    assert cit["verify"]["invalid_refs"] == 1 and len(cit["items"]) == 1


async def test_flow_verify_off_streams_with_unverified_items(make_env) -> None:
    from agent.testing import build_test_container  # noqa: F401

    env = make_env(
        FakeToolProvider({"search_documents": SEARCH}),
        scripts("Nghỉ phép năm 12 ngày làm việc [#11]."),
    )
    env.c.settings.agent_verify_citations = "off"
    events = await env.run(await env.new_thread(), "Nghỉ phép?")
    cit = next(d for e, d in events if e == "citations")
    assert cit["verify"]["enabled"] is False and cit["items"][0]["verdict"] == "unverified"
    assert cit["answer_status"] == "answered"
