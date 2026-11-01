"""Hồi quy: kiểu `audit_hmac_key_id` của gateway phải là int (kế thừa CommonSettings)."""

from datetime import UTC, datetime

from acme_common.services.audit_chain import GENESIS_HASH, AuditKeyring, seal
from gateway.settings import Settings


def test_audit_kid_la_int_va_seal_khong_loi(monkeypatch) -> None:
    # Compose đặt biến môi trường dạng chuỗi.
    monkeypatch.setenv("AUDIT_HMAC_KEY", "k" * 32)
    monkeypatch.setenv("AUDIT_HMAC_KEY_ID", "1")
    s = Settings()

    assert s.audit_hmac_key_id == 1
    assert isinstance(s.audit_hmac_key_id, int)

    keyring = AuditKeyring.single(s.audit_hmac_key, s.audit_hmac_key_id)
    row = {"id": 1, "ts": datetime(2026, 1, 1, tzinfo=UTC), "action": "test"}
    sealed = seal(keyring, GENESIS_HASH, row)
    assert sealed["hmac_kid"] == 1
    assert len(sealed["hash"]) == 32


def test_audit_key_doc_tu_file(monkeypatch, tmp_path) -> None:
    f = tmp_path / "audit_key"
    f.write_text("f" * 32 + "\n")
    monkeypatch.delenv("AUDIT_HMAC_KEY", raising=False)
    monkeypatch.setenv("AUDIT_HMAC_KEY_FILE", str(f))
    assert Settings().audit_hmac_key == "f" * 32
