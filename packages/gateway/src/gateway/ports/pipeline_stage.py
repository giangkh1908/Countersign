"""Port `PipelineStage`: `async __call__(ctx, call_next)`.

Adapter v1 dự kiến: auth, ratelimit, budget, pii, guard, cache, router (registry theo GW_FEATURES).
Milestone: M1-M4.
Tài liệu: docs/design/00-contracts.md §9.2.
"""
