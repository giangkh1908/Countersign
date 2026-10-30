"""Ports của tickets-mcp (abc.ABC theo năng lực, không import vendor)."""

from .approval_verifier import ApprovalVerifier
from .errors import (
    ApprovalRejected,
    ApprovalVerifierNotConfigured,
    BackendUnavailable,
    DuplicateIntent,
    IntentInvalid,
    IntentIssuerNotConfigured,
    ReplayGuardNotConfigured,
    RepositoryRolledBack,
    RepositoryUnavailable,
    TicketConflict,
    TicketRepositoryNotConfigured,
    UnsupportedOperation,
)
from .intent_issuer import IntentIssuer
from .replay_guard import ReplayGuard
from .ticket_repository import TicketRepository
from .types import (
    AppliedOp,
    Approval,
    Audience,
    CasResult,
    Comment,
    Draft,
    Intent,
    SignedIntent,
    StoredIntent,
    Ticket,
)

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
