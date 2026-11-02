"""Package `ports` của acme_common: ABC, kiểu và lỗi trung lập (không import vendor)."""

from .approval_verifier import ApprovalVerifier
from .clock import Clock
from .errors import (
    ApprovalRejected,
    ApprovalVerifierNotConfigured,
    BackendUnavailable,
    ClockNotConfigured,
    EventSinkNotConfigured,
    IntentInvalid,
    IntentIssuerNotConfigured,
    NotConfigured,
    RateLimiterNotConfigured,
    ReplayGuardNotConfigured,
    TokenBrokerNotConfigured,
    TokenExchangeDenied,
    TokenInvalid,
    TokenServiceUnavailable,
    TokenVerifierNotConfigured,
    ToolServerHostNotConfigured,
)
from .event_sink import EventRecord, EventSink
from .intent_executor import (
    DuplicateIntent,
    ExecutionConflict,
    ExecutionRolledBack,
    ExecutionUnavailable,
    IntentExecutor,
)
from .intent_issuer import IntentIssuer
from .intent_types import (
    Approval,
    CasResult,
    Draft,
    Intent,
    SignedIntent,
    StoredIntent,
)
from .rate_limiter import RateLimiter
from .replay_guard import ReplayGuard
from .token_broker import TokenBroker
from .token_verifier import TokenVerifier
from .tool_server_host import RawToolHandler, ToolResult, ToolServerHost, ToolSpec
from .types import AccessToken, LimitDecision, Principal

__all__ = [
    "AccessToken",
    "Approval",
    "ApprovalRejected",
    "ApprovalVerifier",
    "ApprovalVerifierNotConfigured",
    "BackendUnavailable",
    "CasResult",
    "Draft",
    "DuplicateIntent",
    "ExecutionConflict",
    "ExecutionRolledBack",
    "ExecutionUnavailable",
    "Intent",
    "IntentExecutor",
    "IntentInvalid",
    "IntentIssuer",
    "IntentIssuerNotConfigured",
    "ReplayGuard",
    "ReplayGuardNotConfigured",
    "SignedIntent",
    "StoredIntent",
    "Clock",
    "ClockNotConfigured",
    "EventRecord",
    "EventSink",
    "EventSinkNotConfigured",
    "LimitDecision",
    "NotConfigured",
    "Principal",
    "RateLimiter",
    "RateLimiterNotConfigured",
    "TokenBroker",
    "TokenBrokerNotConfigured",
    "TokenExchangeDenied",
    "TokenInvalid",
    "TokenServiceUnavailable",
    "TokenVerifier",
    "TokenVerifierNotConfigured",
    "RawToolHandler",
    "ToolResult",
    "ToolServerHost",
    "ToolServerHostNotConfigured",
    "ToolSpec",
]
