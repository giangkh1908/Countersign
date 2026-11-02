"""Ports của tickets-mcp (abc.ABC theo năng lực, không import vendor).

Các kiểu/port của hạ tầng intent đã chuyển sang `acme_common.ports`; re-export ở đây chỉ để nghiệp vụ
ticket import một chỗ.
"""

from acme_common.ports import (
    Approval,
    ApprovalRejected,
    ApprovalVerifier,
    ApprovalVerifierNotConfigured,
    BackendUnavailable,
    CasResult,
    Draft,
    DuplicateIntent,
    Intent,
    IntentInvalid,
    IntentIssuer,
    IntentIssuerNotConfigured,
    ReplayGuard,
    ReplayGuardNotConfigured,
    SignedIntent,
    StoredIntent,
)

from .errors import (
    RepositoryRolledBack,
    RepositoryUnavailable,
    TicketConflict,
    TicketRepositoryNotConfigured,
    UnsupportedOperation,
)
from .ticket_repository import TicketRepository
from .types import AppliedOp, Audience, Comment, Ticket

__all__ = [
    "AppliedOp",
    "Approval",
    "ApprovalRejected",
    "ApprovalVerifier",
    "ApprovalVerifierNotConfigured",
    "Audience",
    "BackendUnavailable",
    "CasResult",
    "Comment",
    "Draft",
    "DuplicateIntent",
    "Intent",
    "IntentInvalid",
    "IntentIssuer",
    "IntentIssuerNotConfigured",
    "ReplayGuard",
    "ReplayGuardNotConfigured",
    "RepositoryRolledBack",
    "RepositoryUnavailable",
    "SignedIntent",
    "StoredIntent",
    "Ticket",
    "TicketConflict",
    "TicketRepository",
    "TicketRepositoryNotConfigured",
    "UnsupportedOperation",
]
