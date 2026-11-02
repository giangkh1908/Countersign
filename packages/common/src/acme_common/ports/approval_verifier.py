"""Port `ApprovalVerifier`."""

from __future__ import annotations

import abc

from .intent_types import Approval
from .types import Principal


class ApprovalVerifier(abc.ABC):
    @abc.abstractmethod
    def verify(self, token: str, principal: Principal, intent_id: str) -> Approval:
        """Kiểm header/chữ ký/iss/aud/exp/sub/intent_id. Raise `ApprovalRejected(code)`."""
