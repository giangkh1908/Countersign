"""Port `TokenVerifier`: `verify(token, audience) -> Principal` (kiểm iss/aud/exp/azp/scope).

Adapter v1 dự kiến: `oidc_jwks` (chuẩn OIDC).
Milestone: M1.
Tài liệu: docs/design/00-contracts.md §9.2, D16.
"""

from __future__ import annotations

import abc

from .types import Principal


class TokenVerifier(abc.ABC):
    @abc.abstractmethod
    async def verify(self, token: str, audience: str) -> Principal:
        """Raise `TokenInvalid` (token sai) hoặc `TokenServiceUnavailable` (không lấy được khoá)."""
