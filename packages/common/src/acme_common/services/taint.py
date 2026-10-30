"""Taint theo `(sub, thread_id)` + `recent` (contracts §2.1, 02 §5.7, D8/D17). Module thường, không phải port.

`raise_taint` gộp nguyên tử bằng Lua `taint_merge`: max `max_class`, hợp `dept_set`, nối `sources`
(tối đa 20), ghi CẢ khoá thread LẪN `:recent` trong một lần gọi. `get_taint` đọc cả hai; lỗi hạ tầng
=> `None` (phía gọi gắn `taint_unknown`). Client Redis là `redis.asyncio.Redis` (hoặc fakeredis).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError

MAX_SOURCES = 20
DEFAULT_RETENTION_S = 30 * 86400
DEFAULT_RECENT_TTL_S = 86400

# KEYS = [thread?, recent]; ARGV = cls, depts_json, now, source, ttl_1[, ttl_2]
_TAINT_MERGE_LUA = """
local cls = tonumber(ARGV[1]); local now = ARGV[3]; local src = ARGV[4]
local new_depts = cjson.decode(ARGV[2])
for i = 1, #KEYS do
  local key = KEYS[i]; local ttl = tonumber(ARGV[4 + i])
  local cur = redis.call('HMGET', key, 'max_class', 'dept_set', 'sources')
  local mc = math.max(tonumber(cur[1]) or 0, cls)
  local depts = {}
  if cur[2] then depts = cjson.decode(cur[2]) end
  local seen = {}
  for _, d in ipairs(depts) do seen[d] = true end
  for _, d in ipairs(new_depts) do if not seen[d] then seen[d] = true; depts[#depts + 1] = d end end
  local srcs = {}
  if cur[3] then srcs = cjson.decode(cur[3]) end
  local have = false
  for _, s in ipairs(srcs) do if s == src then have = true end end
  if src ~= '' and not have and #srcs < 20 then srcs[#srcs + 1] = src end
  local depts_json = '[]'; if #depts > 0 then depts_json = cjson.encode(depts) end
  local srcs_json = '[]'; if #srcs > 0 then srcs_json = cjson.encode(srcs) end
  redis.call('HSET', key, 'max_class', mc, 'dept_set', depts_json, 'sources', srcs_json, 'updated_at', now)
  redis.call('EXPIRE', key, ttl)
end
return 1
"""


@dataclass(frozen=True, slots=True)
class TaintState:
    max_class: int = 0
    dept_set: frozenset[str] = frozenset()
    sources: tuple[str, ...] = ()
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TaintView:
    thread: TaintState  # rỗng nếu không có thread_id hoặc chưa có khoá
    recent: TaintState


def thread_key(sub: str, thread_id: str) -> str:
    return f"mcp:taint:{sub}:{thread_id}"


def recent_key(sub: str) -> str:
    return f"mcp:taint:{sub}:recent"


async def raise_taint(
    redis: Any,
    sub: str,
    thread_id: str | None,
    max_class: int,
    depts: set[str] | frozenset[str],
    source: str = "",
    *,
    retention_s: int = DEFAULT_RETENTION_S,
    recent_ttl_s: int = DEFAULT_RECENT_TTL_S,
    now: datetime | None = None,
) -> bool:
    """Ghi taint. `True` = đã ghi; `False` = lỗi hạ tầng (caller quyết định fail-closed cho class >= 1)."""
    if thread_id and thread_id != "recent":
        keys = [thread_key(sub, thread_id), recent_key(sub)]
        ttls = [retention_s, recent_ttl_s]
    else:
        keys, ttls = [recent_key(sub)], [recent_ttl_s]
    stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    try:
        await redis.eval(
            _TAINT_MERGE_LUA,
            len(keys),
            *keys,
            int(max_class),
            json.dumps(sorted(depts)),
            stamp,
            source,
            *ttls,
        )
    except (RedisError, OSError, TimeoutError):
        return False
    return True


def _parse(h: dict[Any, Any]) -> TaintState:
    if not h:
        return TaintState()

    def s(v: Any) -> str:
        return v.decode() if isinstance(v, bytes) else str(v)

    g = {s(k): s(v) for k, v in h.items()}
    return TaintState(
        max_class=int(float(g.get("max_class", "0"))),
        dept_set=frozenset(json.loads(g.get("dept_set", "[]"))),
        sources=tuple(json.loads(g.get("sources", "[]"))),
        updated_at=g.get("updated_at"),
    )


async def get_taint(redis: Any, sub: str, thread_id: str | None) -> TaintView | None:
    """`None` = lỗi hạ tầng (=> `taint_unknown`). Khoá chưa có => trạng thái rỗng (max_class 0)."""
    try:
        recent = _parse(await redis.hgetall(recent_key(sub)))
        thread = TaintState()
        if thread_id and thread_id != "recent":
            thread = _parse(await redis.hgetall(thread_key(sub, thread_id)))
    except (RedisError, OSError, TimeoutError, ValueError):
        return None
    return TaintView(thread=thread, recent=recent)


async def forget_thread(redis: Any, sub: str, thread_id: str) -> bool:
    """Xoá khoá thread (không đụng `:recent`). `sub` phải lấy từ JWT, không từ body."""
    if thread_id == "recent":
        return False
    try:
        await redis.delete(thread_key(sub, thread_id))
    except (RedisError, OSError, TimeoutError):
        return False
    return True
