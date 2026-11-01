"""Port `ApprovalVerifier`."""

from __future__ import annotations

import abc

from acme_common.ports import Principal

from .types import Approval


class ApprovalVerifier(abc.ABC):
    @abc.abstractmethod
    def verify(self, token: str, principal: Principal, intent_id: str) -> Approval:
        """Kiểm header/chữ ký/iss/aud/exp/sub/intent_id. Raise `ApprovalRejected(code)`."""
