import json
import math

import httpx
import pytest
from acme_common.http import RetryingHttpClient
from mcp_docs.adapters.fake_hash import FakeHashEmbedder
from mcp_docs.adapters.gateway_http import GatewayHttpEmbedder
from mcp_docs.ports import EmbeddingUnavailable


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_fake_hash_deterministic_and_normalised() -> None:
    e = FakeHashEmbedder()
    a = await e.embed(["Nghỉ phép năm của nhân viên"])
    b = await FakeHashEmbedder().embed(["Nghỉ phép năm của nhân viên"])
    assert a == b
    assert len(a[0]) == 1024 == e.dim
    assert math.isclose(math.sqrt(sum(x * x for x in a[0])), 1.0, rel_tol=1e-9)


async def test_fake_hash_golden_prefix() -> None:
    """Giá trị cố định: hash không phụ thuộc PYTHONHASHSEED/máy."""
    (v,) = await FakeHashEmbedder().embed(["acme"])
    nz = [(i, round(x, 6)) for i, x in enumerate(v) if x != 0.0]
    assert nz == [
        (621, 0.447214),
        (662, 0.447214),
        (699, 0.447214),
        (820, -0.447214),
        (857, 0.447214),
    ]


async def test_fake_hash_similarity_ordering_and_unaccent() -> None:
    e = FakeHashEmbedder()
    q, same, accentless, other = await e.embed(
        [
            "nghỉ phép năm",
            "Chính sách nghỉ phép năm",
            "chinh sach nghi phep nam",
            "giá sản phẩm phần mềm",
        ]
    )
    assert _cos(q, same) > _cos(q, other)
    assert _cos(q, accentless) > _cos(q, other)


async def test_fake_hash_empty_text_still_unit_vector() -> None:
    (v,) = await FakeHashEmbedder().embed([""])
    assert sum(x * x for x in v) == pytest.approx(1.0)


def _embedder(handler, **kw):
    http = RetryingHttpClient(
        transport=httpx.MockTransport(handler), max_attempts=2, sleep=_nosleep
    )
    return GatewayHttpEmbedder(base_url="http://gw/v1/", api_key="k-secret", http=http, dim=4, **kw)


async def _nosleep(_: float) -> None:
    return None


async def test_gateway_http_request_shape_and_order() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        n = len(seen["body"]["input"])
        # trả đảo thứ tự index để kiểm tra sắp xếp lại
        data = [{"index": i, "embedding": [float(i + 1), 0, 0, 0]} for i in reversed(range(n))]
        return httpx.Response(200, json={"object": "list", "data": data})

    vecs = await _embedder(handler).embed(["a", "b", "c"])
    assert seen["url"] == "http://gw/v1/embeddings"
    assert seen["auth"] == "Bearer k-secret"
    assert seen["body"]["model"] == "acme-embed" and seen["body"]["input"] == ["a", "b", "c"]
    assert vecs == [[1.0, 0, 0, 0], [1.0, 0, 0, 0], [1.0, 0, 0, 0]]  # đã L2-normalize


async def test_gateway_http_batches_of_32() -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        n = len(json.loads(req.content)["input"])
        calls.append(n)
        return httpx.Response(
            200, json={"data": [{"index": i, "embedding": [1, 0, 0, 0]} for i in range(n)]}
        )

    out = await _embedder(handler).embed([str(i) for i in range(70)])
    assert calls == [32, 32, 6] and len(out) == 70


@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(401, json={"error": "x"}),
        httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 0]}]}),  # sai chiều
        httpx.Response(200, json={"nope": 1}),
        httpx.Response(200, text="not json"),
    ],
)
async def test_gateway_http_errors_map_to_embedding_unavailable(resp) -> None:
    with pytest.raises(EmbeddingUnavailable):
        await _embedder(lambda r: resp).embed(["x"])


async def test_gateway_http_retries_5xx_then_fails_without_leaking_key() -> None:
    n = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        return httpx.Response(503)

    with pytest.raises(EmbeddingUnavailable) as ei:
        await _embedder(handler).embed(["x"])
    assert n == 2 and "k-secret" not in str(ei.value)


async def test_gateway_http_model_id_from_response_header() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        n = len(json.loads(req.content)["input"])
        return httpx.Response(
            200,
            headers={"x-acme-model": "bge-m3"},
            json={"data": [{"index": i, "embedding": [1, 0, 0, 0]} for i in range(n)]},
        )

    e = _embedder(handler)
    assert e.model_id == "acme-embed"  # chưa gọi: trả alias cấu hình
    await e.embed(["a"])
    assert e.model_id == "bge-m3"


async def test_fake_hash_has_own_model_id() -> None:
    assert FakeHashEmbedder().model_id == "fake_hash"
