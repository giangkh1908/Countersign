import pytest
from acme_common.testing import FakeClock
from gateway.adapters.openai_chat import OpenAIChatProvider
from gateway.factory import _PROVIDERS, ProviderPool, build_key_store, build_provider
from gateway.ports import ChatProvider, KeyStore, KeyStoreNotConfigured, ProviderNotConfigured
from gw_support import make_settings


def test_known_provider_builds_and_inherits_port() -> None:
    p = build_provider("mock", make_settings())
    assert isinstance(p, ChatProvider) and isinstance(p, OpenAIChatProvider)


def test_anthropic_requires_key_and_inherits_port() -> None:
    with pytest.raises(ProviderNotConfigured, match="ANTHROPIC_API_KEY"):
        build_provider("anthropic", make_settings(anthropic_api_key=None))
    p = build_provider("anthropic", make_settings(anthropic_api_key="k"))
    assert isinstance(p, ChatProvider) and p.name == "anthropic"


def test_unknown_provider_lists_known_names() -> None:
    with pytest.raises(ProviderNotConfigured) as e:
        build_provider("nope", make_settings())
    assert "anthropic" in str(e.value) and "mock" in str(e.value)


def test_key_store_known_and_unknown() -> None:
    ks = build_key_store(
        "postgres", make_settings(gw_database_url="postgresql://u:p@h/db"), clock=FakeClock()
    )
    assert isinstance(ks, KeyStore)
    with pytest.raises(KeyStoreNotConfigured, match="postgres"):
        build_key_store("nope", make_settings(), clock=FakeClock())
    with pytest.raises(KeyStoreNotConfigured, match="GW_DATABASE_URL"):
        build_key_store("postgres", make_settings(), clock=FakeClock())


async def test_provider_pool_caches_instances() -> None:
    pool = ProviderPool(make_settings())
    assert pool.get("mock") is pool.get("mock")
    await pool.aclose()


def test_openrouter_requires_key_and_builds() -> None:
    with pytest.raises(ProviderNotConfigured, match="OPENROUTER_API_KEY"):
        build_provider("openrouter", make_settings(openrouter_api_key=None))
    p = build_provider("openrouter", make_settings(openrouter_api_key="k"))
    assert isinstance(p, ChatProvider) and p.name == "openrouter"
    assert "openrouter" in _PROVIDERS
    assert str(p._client.base_url).startswith("https://openrouter.ai/api")  # type: ignore[attr-defined]
