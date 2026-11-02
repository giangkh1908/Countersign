"""Ports của notify-mcp (abc.ABC theo năng lực, không import vendor).

Kiểu và port của hạ tầng intent nằm ở `acme_common.ports`; re-export ở đây để nghiệp vụ import một chỗ.
"""

from acme_common.ports import (
    Approval,
    ApprovalRejected,
    ApprovalVerifier,
    ApprovalVerifierNotConfigured,
    BackendUnavailable,
    Draft,
    DuplicateIntent,
    ExecutionRolledBack,
    Intent,
    IntentIssuer,
    IntentIssuerNotConfigured,
    ReplayGuard,
    ReplayGuardNotConfigured,
)

from .delivery_log import (
    DeliveryLog,
    DeliveryLogNotConfigured,
    DeliveryLogUnavailable,
    DeliveryRecord,
    DeliveryStatus,
)
from .message_channel import (
    ChannelSendError,
    DeliveryReceipt,
    MessageChannel,
    MessageChannelNotConfigured,
)

__all__ = [
    "Approval",
    "ApprovalRejected",
    "ApprovalVerifier",
    "ApprovalVerifierNotConfigured",
    "BackendUnavailable",
    "ChannelSendError",
    "DeliveryLog",
    "DeliveryLogNotConfigured",
    "DeliveryLogUnavailable",
    "DeliveryReceipt",
    "DeliveryRecord",
    "DeliveryStatus",
    "Draft",
    "DuplicateIntent",
    "ExecutionRolledBack",
    "Intent",
    "IntentIssuer",
    "IntentIssuerNotConfigured",
    "MessageChannel",
    "MessageChannelNotConfigured",
    "ReplayGuard",
    "ReplayGuardNotConfigured",
]
