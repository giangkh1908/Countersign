"""Adapter `fake` cho `MessageChannel`: không gửi đi đâu, chỉ ghi nhớ (test, eval, demo không token).

Có thể chèn lỗi để thử các nhánh `ChannelSendError`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ports import ChannelSendError, DeliveryReceipt, MessageChannel


@dataclass(frozen=True, slots=True)
class SentMessage:
    chat_ref: str
    text: str


class FakeMessageChannel(MessageChannel):
    def __init__(self) -> None:
        self.sent: list[SentMessage] = []
        self.fail_with: ChannelSendError | None = None  # lỗi ném ở lần gọi kế tiếp (rồi tự xoá)
        self.fail_after_send: ChannelSendError | None = (
            None  # đã ghi nhận tin rồi mới ném (mô phỏng timeout)
        )
        self.calls = 0

    async def send(self, chat_ref: str, text: str) -> DeliveryReceipt:
        self.calls += 1
        if self.fail_with is not None:
            err, self.fail_with = self.fail_with, None
            raise err
        self.sent.append(SentMessage(chat_ref, text))
        if self.fail_after_send is not None:
            err, self.fail_after_send = self.fail_after_send, None
            raise err
        return DeliveryReceipt(message_ref=f"fake-{len(self.sent)}")
