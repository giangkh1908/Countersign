"""Port `ApprovalSigner`: `sign(intent, principal) -> ApprovalToken`.

Adapter v1: `es256_jwt`. Tài liệu: docs/design/approval.md §2.1.
"""

from __future__ import annotations

import abc

from acme_common.ports import Principal

from .types import ApprovalToken, VerifiedIntent


class ApprovalSigner(abc.ABC):
    @abc.abstractmethod
    def sign(self, intent: VerifiedIntent, principal: Principal) -> ApprovalToken:
        """Ký approval token ràng buộc `intent_sha256` và `sub` của người duyệt."""
