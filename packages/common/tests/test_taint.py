import fakeredis
import pytest
from acme_common.services.taint import forget_thread, get_taint, raise_taint, recent_key, thread_key
from redis.exceptions import ConnectionError as RedisConnectionError


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


async def test_writes_thread_and_recent(redis) -> None:
    assert await raise_taint(redis, "u1", "T", 2, {"HR"}, "doc-1")
    view = await get_taint(redis, "u1", "T")
    assert view is not None
    for st in (view.thread, view.recent):
        assert st.max_class == 2 and st.dept_set == {"HR"} and st.sources == ("doc-1",)
    assert 0 < await redis.ttl(thread_key("u1", "T")) <= 30 * 86400
    assert 0 < await redis.ttl(recent_key("u1")) <= 86400


async def test_merge_max_class_and_union_depts(redis) -> None:
    await raise_taint(redis, "u1", "T", 1, {"HR"}, "a")
    await raise_taint(redis, "u1", "T", 3, {"IT", "HR"}, "b")
    await raise_taint(redis, "u1", "T", 0, set(), "c")
    v = await get_taint(redis, "u1", "T")
    assert v.thread.max_class == 3 and v.thread.dept_set == {"HR", "IT"}
    assert v.thread.sources == ("a", "b", "c")


async def test_sources_capped_at_20(redis) -> None:
    for i in range(30):
        await raise_taint(redis, "u1", "T", 1, {"HR"}, f"s{i}")
    v = await get_taint(redis, "u1", "T")
    assert len(v.thread.sources) == 20 and len(v.recent.sources) == 20


async def test_other_thread_visible_through_recent(redis) -> None:
    await raise_taint(redis, "u1", "T", 2, {"HR"}, "x")
    v = await get_taint(redis, "u1", "FAKE-T2")
    assert v.thread.max_class == 0 and v.recent.max_class == 2 and v.recent.dept_set == {"HR"}


async def test_no_thread_id_writes_recent_only(redis) -> None:
    await raise_taint(redis, "u1", None, 1, {"CS"}, "x")
    assert await redis.keys("mcp:taint:u1:*") == [recent_key("u1")]
    v = await get_taint(redis, "u1", None)
    assert v.recent.sources == ("x",) and v.thread.max_class == 0


async def test_users_isolated_and_empty_state(redis) -> None:
    await raise_taint(redis, "u1", "T", 2, {"HR"})
    v = await get_taint(redis, "u2", "T")
    assert v.thread.max_class == 0 and v.recent.dept_set == frozenset()


async def test_empty_depts_roundtrip(redis) -> None:
    await raise_taint(redis, "u1", "T", 1, set(), "s")
    assert (await get_taint(redis, "u1", "T")).thread.dept_set == frozenset()


async def test_forget_thread_leaves_recent(redis) -> None:
    await raise_taint(redis, "u1", "T", 2, {"HR"})
    assert await forget_thread(redis, "u1", "T")
    v = await get_taint(redis, "u1", "T")
    assert v.thread.max_class == 0 and v.recent.max_class == 2
    assert not await forget_thread(redis, "u1", "recent")


class BrokenRedis:
    async def eval(self, *a, **k):
        raise RedisConnectionError("down")

    async def hgetall(self, *a, **k):
        raise RedisConnectionError("down")


async def test_infra_error_returns_none_or_false() -> None:
    assert await get_taint(BrokenRedis(), "u1", "T") is None
    assert await raise_taint(BrokenRedis(), "u1", "T", 1, {"HR"}) is False
