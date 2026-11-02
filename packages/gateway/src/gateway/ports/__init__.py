"""Package `ports` của gateway: ABC, kiểu và lỗi trung lập (không import vendor)."""

from .chat_provider import ChatProvider
from .embedding_provider import EmbeddingProvider
from .errors import (
    EmbeddingNotConfigured,
    KeyAlreadyExists,
    KeyNotFound,
    KeyStoreNotConfigured,
    ProviderNotConfigured,
)
from .key_store import KeyStore
from .types import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    EmbeddingResult,
    KeyRecord,
    NewKey,
    ProviderError,
    ToolCallDelta,
    Usage,
)

__all__ = [
    "ChatChunk",
    "ChatProvider",
    "ChatRequest",
    "ChatResponse",
    "EmbeddingNotConfigured",
    "EmbeddingProvider",
    "EmbeddingResult",
    "KeyAlreadyExists",
    "KeyNotFound",
    "KeyRecord",
    "KeyStore",
    "KeyStoreNotConfigured",
    "NewKey",
    "ProviderError",
    "ProviderNotConfigured",
    "ToolCallDelta",
    "Usage",
]
