"""Lỗi cấu hình của factory docs-mcp (tên adapter lạ)."""

from __future__ import annotations

from acme_common.ports.errors import NotConfigured


class RetrieverNotConfigured(NotConfigured):
    pass


class RerankerNotConfigured(NotConfigured):
    pass


class DocumentLoaderNotConfigured(NotConfigured):
    pass


class EmbedderNotConfigured(NotConfigured):
    pass


class DocumentIndexerNotConfigured(NotConfigured):
    pass
