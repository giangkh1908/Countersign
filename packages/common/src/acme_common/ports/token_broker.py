"""Port `TokenBroker`: `token_for(principal, user_token, audience, scopes)`.

Adapter v1 dự kiến: `oauth_token_exchange` (RFC 8693); test: `static`; decorator Caching(inner).
Tài liệu: docs/design/contracts.md §9.2.
"""

from __future__ import annotations

import abc
from collections.abc import Sequence

from .types import AccessToken, Principal


class TokenBroker(abc.ABC):
    @abc.abstractmethod
    async def token_for(
        self,
        principal: Principal,
        user_token: str,
        audience: str,
        scopes: Sequence[str],
    ) -> AccessToken:
        """Token cho đúng một `audience`. `principal` là kết quả `TokenVerifier` của `user_token`.

        Raise `TokenExchangeDenied` (bị từ chối / vi phạm hậu điều kiện) hoặc
        `TokenServiceUnavailable`.
        """
