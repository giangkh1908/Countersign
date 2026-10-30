"""Port `IntentVerifier`: `verify(intent_jws, principal) -> RenderModel`.

Adapter v1: `es256_jws`. Tài liệu: docs/design/00-contracts.md §4.1, 05 §5.2.
"""

from __future__ import annotations

import abc

from acme_common.ports import Principal

from .types import RenderModel, VerifiedIntent


class IntentVerifier(abc.ABC):
    @abc.abstractmethod
    def verify_intent(self, intent_jws: str, principal: Principal) -> VerifiedIntent:
        """Raise `SignerError` (`intent_mismatch`, `intent_expired`, `invalid_argument`)."""

    @abc.abstractmethod
    def verify(self, intent_jws: str, principal: Principal) -> RenderModel:
        """Như `verify_intent` rồi dựng render model; raise thêm `intent_unrenderable`."""
