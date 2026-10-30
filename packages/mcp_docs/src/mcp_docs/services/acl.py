"""`AclPolicy`: hàm thuần kiểm quyền đọc chunk (cùng quy tắc contracts §3.2 / RLS `chunk_acl`).

`DocumentService` dùng để kiểm lại mọi `RetrievedChunk` do retriever trả về (lớp ACL thứ ba,
độc lập adapter): thiếu thông tin ACL hoặc principal không có clearance => từ chối (fail-closed).
"""

from __future__ import annotations

from collections.abc import Collection

from acme_common.ports import Principal


class AclPolicy:
    @staticmethod
    def can_read(
        principal: Principal,
        department: str | None,
        classification: int | None,
        allowed_roles: Collection[str] | None,
    ) -> bool:
        if department is None or classification is None or allowed_roles is None:
            return False
        if principal.clearance is None or classification > principal.clearance:
            return False
        if department != "ALL" and department not in principal.dept:
            return False
        return not allowed_roles or bool(set(allowed_roles) & set(principal.roles))
