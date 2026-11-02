"""Lỗi của factory/port gateway: `XxxNotConfigured` khi tên adapter lạ."""

from acme_common.ports import NotConfigured


class ProviderNotConfigured(NotConfigured):
    pass


class EmbeddingNotConfigured(NotConfigured):
    pass


class RerankNotConfigured(NotConfigured):
    pass


class KeyStoreNotConfigured(NotConfigured):
    pass


class CacheNotConfigured(NotConfigured):
    pass


class KeyAlreadyExists(Exception):
    """Prefix trùng (xác suất ~0); caller sinh lại key."""


class KeyNotFound(Exception):
    pass
