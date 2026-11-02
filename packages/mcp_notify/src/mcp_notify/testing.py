"""`Fake<Port>` của notify-mcp cho test nghiệp vụ (contracts §9.1 mục 9). Kế thừa port tường minh.

`FakeMessageChannel` nằm ở `adapters/fake.py` (là adapter chọn được bằng registry).
"""

from __future__ import annotations

from acme_common.ports import DuplicateIntent

from .ports import DeliveryLog, DeliveryLogUnavailable, DeliveryRecord, DeliveryStatus


class FakeDeliveryLog(DeliveryLog):
    def __init__(self) -> None:
        self.rows: dict[str, DeliveryRecord] = {}
        self.fail_begin: DeliveryLogUnavailable | None = None  # chèn lỗi ở `begin`
        self.fail_finish = False
        self.fail_find = False

    async def begin(
        self, intent_id: str, channel: str, text_sha256: str, actor_sub: str, approval_jti: str
    ) -> None:
        if self.fail_begin is not None:
            raise self.fail_begin
        if intent_id in self.rows:
            raise DuplicateIntent
        self.rows[intent_id] = DeliveryRecord(intent_id, channel, text_sha256, "sending")

    async def finish(self, intent_id: str, status: DeliveryStatus, detail: str = "") -> None:
        if self.fail_finish:
            raise DeliveryLogUnavailable("update")
        cur = self.rows[intent_id]
        if cur.status == "sending":
            self.rows[intent_id] = DeliveryRecord(
                intent_id, cur.channel, cur.text_sha256, status, detail
            )

    async def find(self, intent_id: str) -> DeliveryRecord | None:
        if self.fail_find:
            raise DeliveryLogUnavailable("select")
        return self.rows.get(intent_id)
