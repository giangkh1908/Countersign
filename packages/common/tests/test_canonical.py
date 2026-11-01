import hashlib
import unicodedata

import pytest
from acme_common.services.canonical import canonical_json, intent_sha256


def test_sorted_compact_utf8() -> None:
    assert canonical_json({"b": 1, "a": [1, {"d": "đ", "c": None}]}) == (
        '{"a":[1,{"c":null,"d":"đ"}],"b":1}'.encode()
    )


def test_nfc_normalisation() -> None:
    nfd = unicodedata.normalize("NFD", "Đã đóng")
    assert canonical_json({"k": nfd}) == canonical_json({"k": unicodedata.normalize("NFC", nfd)})


def test_rejects_float_and_nan() -> None:
    with pytest.raises(ValueError):
        canonical_json({"a": 1.5})
    with pytest.raises(ValueError):
        canonical_json({"a": float("nan")})


def test_intent_sha256_stable() -> None:
    p = {"op": "close_ticket", "target": "TCK-1"}
    assert intent_sha256(p) == hashlib.sha256(b'{"op":"close_ticket","target":"TCK-1"}').hexdigest()
