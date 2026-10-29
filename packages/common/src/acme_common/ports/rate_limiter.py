"""Port `RateLimiter`: `reserve`, `settle`, `acquire_slot(key_id, max)`, `release_slot(key_id)`.

Adapter v1 dự kiến: `redis_token_bucket`, `in_memory` (degraded, D5).
Milestone: M1.
Tài liệu: docs/design/00-contracts.md §9.2.
"""
