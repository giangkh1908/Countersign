import uuid
from datetime import UTC, datetime, timedelta

import pytest
from acme_common.audit import GENESIS_HASH, AuditKeyring, seal, verify_chain

KR = AuditKeyring.single("k" * 32, 1)


def build(n: int, kr: AuditKeyring = KR, *, intent: bool = False):
    rows, prev = [], GENESIS_HASH
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(1, n + 1):
        row = {
            "id": i, "ts": t0 + timedelta(seconds=i, microseconds=i), "request_id": str(uuid.uuid4()),
            "actor_type": "service", "actor_id": "agent-service", "end_user_sub": "u1",
            "action": "tool.call", "resource": f"t{i}", "decision": "allow",
            "details": {"n": i, "name": "Đã đóng", "nested": {"a": [1, 2]}},
        }  # fmt: skip
        if intent:
            row["intent_id"] = None
        s = seal(kr, prev, row)
        rows.append(s)
        prev = s["hash"]
    return rows


def test_valid_chain_ok() -> None:
    rows = build(5)
    r = verify_chain(rows, KR, expected_tail=(5, rows[-1]["hash"]))
    assert r.ok and r.checked == 5 and r.last_id == 5


def test_intent_id_column_part_of_hash() -> None:
    rows = build(3, intent=True)
    assert verify_chain(rows, KR).ok
    rows[1]["intent_id"] = str(uuid.uuid4())
    assert verify_chain(rows, KR).reason == "hash_mismatch"


def test_modified_row_detected() -> None:
    rows = build(5)
    rows[2] = {**rows[2], "decision": "deny"}
    r = verify_chain(rows, KR)
    assert not r.ok and r.reason == "hash_mismatch" and r.bad_id == 3


def test_modified_details_detected() -> None:
    rows = build(4)
    rows[1] = {**rows[1], "details": {**rows[1]["details"], "n": 999}}
    assert verify_chain(rows, KR).bad_id == 2


def test_deleted_middle_row_detected() -> None:
    rows = build(5)
    del rows[2]
    r = verify_chain(rows, KR)
    assert not r.ok and r.reason == "chain_break" and r.bad_id == 4


def test_deleted_first_row_detected() -> None:
    rows = build(3)[1:]
    assert verify_chain(rows, KR).reason == "chain_break"


def test_deleted_tail_only_detected_with_anchor() -> None:
    rows = build(5)
    tail = (5, rows[-1]["hash"])
    assert verify_chain(rows[:4], KR).ok  # không anchor: không thấy
    r = verify_chain(rows[:4], KR, expected_tail=tail)
    assert not r.ok and r.reason == "tail_missing"


def test_resume_from_anchor() -> None:
    rows = build(5)
    r = verify_chain(rows[3:], KR, prev_hash=rows[2]["hash"])
    assert r.ok and r.checked == 2


def test_wrong_key_fails_and_unknown_kid() -> None:
    rows = build(2)
    assert verify_chain(rows, AuditKeyring.single("z" * 32, 1)).reason == "hash_mismatch"
    assert verify_chain(rows, AuditKeyring.single("k" * 32, 7)).reason == "unknown_kid"


def test_key_rotation_old_rows_still_verify() -> None:
    old = build(2)
    kr2 = AuditKeyring({1: b"k" * 32, 2: b"n" * 32}, 2)
    new = seal(kr2, old[-1]["hash"], {**build(3)[2], "id": 3})
    assert new["hmac_kid"] == 2 and verify_chain([*old, new], kr2).ok


def test_float_in_details_rejected_and_short_key() -> None:
    row = build(1)[0]
    with pytest.raises(ValueError):
        seal(KR, GENESIS_HASH, {**row, "details": {"x": 1.5}})
    with pytest.raises(ValueError):
        AuditKeyring.single("short")


def test_ts_microseconds_and_timezone_normalised() -> None:
    row = build(1)[0]
    from datetime import timezone

    other_tz = row["ts"].astimezone(timezone(timedelta(hours=7)))
    assert verify_chain([{**row, "ts": other_tz}], KR).ok
