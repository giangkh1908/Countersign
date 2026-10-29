# policy-sidecar

Model nặng tách khỏi gateway: `/v1/embed` (bge-m3 ONNX), `/v1/guard` (Prompt Guard 2), `/v1/pii/ner` (underthesea CRF). Verify `models.lock` lúc khởi động. Bearer nội bộ `SIDECAR_TOKEN`.

- Cổng: 8010 (không expose host)
- Mạng docker: `core` only, không egress
- Tài liệu: `docs/design/06-policy-sidecar.md`, `docs/design/00-contracts.md` §1, §7, §7.1
