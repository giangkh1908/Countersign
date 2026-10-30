"""Hash-chain HMAC dùng chung cho audit (gateway, MCP). Xem docs/design/00-contracts.md §3.1, §3.6.

- `chain`: hàm thuần (`seal`, `verify_chain`, `AuditKeyring`).
- `pg`: ghi vào Postgres trong transaction của caller (`append_audit`, `append_audit_sync`).
"""

from .chain import (
    GENESIS_HASH,
    AuditKeyring,
    VerifyResult,
    canonical_row,
    compute_hash,
    seal,
    verify_chain,
)

__all__ = [
    "GENESIS_HASH",
    "AuditKeyring",
    "VerifyResult",
    "canonical_row",
    "compute_hash",
    "seal",
    "verify_chain",
]
