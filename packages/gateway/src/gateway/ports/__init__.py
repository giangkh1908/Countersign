"""Package `ports` của gateway: ABC, kiểu và lỗi trung lập (không import vendor)."""

from .chat_provider import ChatProvider
from .embedding_provider import EmbeddingProvider
from .errors import (
    EmbeddingNotConfigured,
    KeyAlreadyExists,
    KeyNotFound,
    KeyStoreNotConfigured,
    ProviderNotConfigured,
    RerankNotConfigured,
)
from .key_store import KeyStore
from .rerank_provider import RerankProvider
from .types import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    EmbeddingResult,
    KeyRecord,
    NewKey,
    ProviderError,
    RerankItem,
    RerankResult,
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
    "RerankItem",
    "RerankNotConfigured",
    "RerankProvider",
    "RerankResult",
    "ToolCallDelta",
    "Usage",
]
