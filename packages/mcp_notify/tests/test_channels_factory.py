"""Cấu hình kênh (max_class <= 1), factory registry, decorator retry."""

from __future__ import annotations

import pytest
from mcp_notify.adapters.fake import FakeMessageChannel
from mcp_notify.channels import ChannelConfigError, env_chat_resolver, load_channels, parse_channels
from mcp_notify.factory import (
    build_delivery_log,
    build_message_channel,
    build_replay_guard,
    build_senders,
)
from mcp_notify.ports import (
    ChannelSendError,
    DeliveryLogNotConfigured,
    MessageChannel,
    MessageChannelNotConfigured,
)
from mcp_notify.retrying import RetryingMessageChannel
from mcp_notify.settings import Settings


def ch(**over):
    base = {"adapter": "fake", "chat_ref": "TG_CHAT_X", "scope": "company", "max_class": 0}
    return {"channels": {"kenh-a": {**base, **over}}}


def test_valid_config() -> None:
    cfg = parse_channels(
        {
            "channels": {
                "dept-eng": {
                    "adapter": "telegram",
                    "chat_ref": "TG_CHAT_ENG",
                    "scope": "dept",
                    "dept": "ENG",
                    "max_class": 1,
                },
                "company-all": {
                    "adapter": "telegram",
                    "chat_ref": "TG_CHAT_ALL",
                    "scope": "company",
                    "max_class": 0,
                },
            }
        }
    )
    assert cfg["dept-eng"].max_class == 1 and cfg["company-all"].dept is None


@pytest.mark.parametrize("mc", [2, 3, -1, True, "1", None, 1.5])
def test_max_class_above_one_or_invalid_rejected(mc) -> None:
    with pytest.raises(ChannelConfigError):
        parse_channels(ch(max_class=mc))


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"channels": {}},
        {"channels": []},
        ch(scope="all"),
        ch(scope="dept"),  # thiếu dept
        ch(scope="company", dept="ENG"),
        ch(chat_ref="-100123456"),  # ID thật, không phải tên biến
        ch(chat_ref="lower"),
        ch(adapter=""),
        ch(extra="x"),
        {"channels": {"Bad Alias": ch()["channels"]["kenh-a"]}},
    ],
)
def test_bad_config_rejected(raw) -> None:
    with pytest.raises(ChannelConfigError):
        parse_channels(raw)


def test_load_channels_file_errors(tmp_path) -> None:
    with pytest.raises(ChannelConfigError):
        load_channels(tmp_path / "khong-co.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("channels: [unclosed", encoding="utf-8")
    with pytest.raises(ChannelConfigError):
        load_channels(bad)
    good = tmp_path / "ok.yaml"
    good.write_text(
        "channels:\n  kenh-a: {adapter: fake, chat_ref: TG_X, scope: company, max_class: 1}\n",
        encoding="utf-8",
    )
    assert load_channels(good)["kenh-a"].max_class == 1


def test_env_chat_resolver(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TG_CHAT_X", "-100999")
    assert env_chat_resolver("TG_CHAT_X") == "-100999"
    f = tmp_path / "chat"
    f.write_text("-100777\n", encoding="utf-8")
    monkeypatch.setenv("TG_CHAT_X_FILE", str(f))
    assert env_chat_resolver("TG_CHAT_X") == "-100777"
    monkeypatch.setenv("TG_CHAT_X_FILE", str(tmp_path / "none"))
    assert env_chat_resolver("TG_CHAT_X") is None
    assert env_chat_resolver("TG_NOPE") is None


# ---------------------------------------------------------------- factory
def test_factory_registry_unknown_lists_known() -> None:
    s = Settings()
    with pytest.raises(MessageChannelNotConfigured) as e:
        build_message_channel("whatsapp", s)
    assert "telegram" in str(e.value) and "fake" in str(e.value)
    with pytest.raises(DeliveryLogNotConfigured):
        build_delivery_log("mysql", s)


def test_factory_builds_fake_wrapped_in_retry() -> None:
    ch_ = build_message_channel("fake", Settings())
    assert isinstance(ch_, RetryingMessageChannel) and isinstance(ch_, MessageChannel)


def test_telegram_without_token_not_configured() -> None:
    with pytest.raises(MessageChannelNotConfigured):
        build_message_channel("telegram", Settings(telegram_bot_token=""))


def test_build_senders_one_per_adapter() -> None:
    cfg = parse_channels(
        {
            "channels": {
                "a-a": {"adapter": "fake", "chat_ref": "TG_A", "scope": "company", "max_class": 0},
                "b-b": {"adapter": "fake", "chat_ref": "TG_B", "scope": "company", "max_class": 0},
            }
        }
    )
    assert list(build_senders(cfg, Settings())) == ["fake"]


def test_replay_guard_unknown() -> None:
    from acme_common.ports import ReplayGuardNotConfigured

    with pytest.raises(ReplayGuardNotConfigured):
        build_replay_guard("x", Settings(), redis=None, clock=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------- retry
class _Flaky(FakeMessageChannel):
    def __init__(self, errors: list[ChannelSendError]) -> None:
        super().__init__()
        self.errors = errors

    async def send(self, chat_ref, text):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return await super().send(chat_ref, text)


async def _nosleep_factory(inner, waits, **kw):
    async def sleep(w: float) -> None:
        waits.append(w)

    return RetryingMessageChannel(inner, sleep=sleep, rng=lambda: 1.0, **kw)


async def test_retry_connect_error_then_ok() -> None:
    waits: list[float] = []
    inner = _Flaky([ChannelSendError("connect", delivered="no")])
    r = await _nosleep_factory(inner, waits)
    await r.send("REF", "x")
    assert len(waits) == 1


async def test_retry_honors_retry_after() -> None:
    waits: list[float] = []
    inner = _Flaky([ChannelSendError("rate_limited", status=429, delivered="no", retry_after_s=2)])
    r = await _nosleep_factory(inner, waits)
    await r.send("REF", "x")
    assert waits == [2.0]


async def test_retry_after_too_long_raises() -> None:
    inner = _Flaky([ChannelSendError("rate_limited", status=429, delivered="no", retry_after_s=60)])
    r = await _nosleep_factory(inner, [], max_wait_s=5)
    with pytest.raises(ChannelSendError):
        await r.send("REF", "x")
    assert inner.calls == 1


@pytest.mark.parametrize(
    "err",
    [
        ChannelSendError("timeout"),
        ChannelSendError("http_5xx", status=502),
        ChannelSendError("http_4xx", status=403, delivered="no"),
        ChannelSendError("transport"),
    ],
)
async def test_no_retry_when_not_certain_or_not_retryable(err) -> None:
    inner = _Flaky([err])
    r = await _nosleep_factory(inner, [])
    with pytest.raises(ChannelSendError):
        await r.send("REF", "x")
    assert inner.calls == 1  # không bao giờ gửi lại khi không chắc


async def test_retry_gives_up_after_max_attempts() -> None:
    inner = _Flaky([ChannelSendError("connect", delivered="no") for _ in range(5)])
    r = await _nosleep_factory(inner, [], max_attempts=3)
    with pytest.raises(ChannelSendError):
        await r.send("REF", "x")
    assert inner.calls == 3


def test_retry_invalid_attempts() -> None:
    with pytest.raises(ValueError):
        RetryingMessageChannel(FakeMessageChannel(), max_attempts=0)
