"""Factory của approval_signer: chọn adapter theo config bằng registry dict + lazy import.

Quy tắc (contracts §9.1 mục 5): KHÔNG dùng chuỗi if/elif. Mỗi vendor có một hàm loader
import lười (`from .adapters.<vendor> import ...` nằm TRONG hàm). Tên lạ -> raise
`XxxNotConfigured` kèm `sorted(_REGISTRY)`. Factory bọc sẵn decorator cross-cutting.
"""

from collections.abc import Callable

# TODO: điền loader theo bảng port §9.2 khi triển khai milestone tương ứng.
_REGISTRY: dict[str, Callable[..., object]] = {}
