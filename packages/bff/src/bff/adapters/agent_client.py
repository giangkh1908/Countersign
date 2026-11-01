"""AgentClient: lớp HTTP thường (không port, D11/§9.2) gọi API nội bộ của agent (03 §1.3).

Giao tiếp JSON qua `RetryingHttpClient` (composition); luồng SSE mở bằng `httpx.AsyncClient.stream`
riêng, không retry tự động vì POST không idempotent.
"""

from __future__ import annotations

from typing import Any

import httpx
from acme_common.http import HttpError, RetryingHttpClient
from acme_common.log import get_request_id

from ..services.errors import UpstreamStatus


def error_code_of(resp: httpx.Response) -> str | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("code"), str):
            return err["code"]
        if isinstance(body.get("code"), str):
            return body["code"]
    return None


def auth_headers(token: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if rid := get_request_id():
        headers["X-Request-Id"] = rid
    return headers


class AgentClient:
    def __init__(self, base_url: str, http: RetryingHttpClient, stream: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._http = http
        self._stream = stream

    async def _json(
        self, method: str, path: str, token: str, *, expect: int | None = None, **kw: Any
    ) -> Any:
        resp = await self._http.request(
            method, f"{self._base}{path}", headers=auth_headers(token), **kw
        )
        if resp.status_code >= 400:
            raise UpstreamStatus(
                "agent", resp.status_code, error_code_of(resp), resp.headers.get("retry-after")
            )
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            raise HttpError("bad_body", retryable=False) from None

    async def create_thread(self, token: str, title: str | None) -> dict[str, Any]:
        body = await self._json("POST", "/v1/threads", token, json={"title": title})
        if not isinstance(body, dict) or "thread_id" not in body:
            raise HttpError("bad_body", retryable=False)
        return body

    async def list_threads(self, token: str, limit: int, before: str | None) -> Any:
        params: dict[str, Any] = {"limit": limit}
        if before:
            params["before"] = before
        return await self._json("GET", "/v1/threads", token, params=params)

    async def messages(self, token: str, thread_id: str) -> dict[str, Any]:
        body = await self._json("GET", f"/v1/threads/{thread_id}/messages", token)
        if not isinstance(body, dict):
            raise HttpError("bad_body", retryable=False)
        return body

    async def delete_thread(self, token: str, thread_id: str) -> None:
        await self._json("DELETE", f"/v1/threads/{thread_id}", token)

    async def request_cost(self, token: str, request_id: str) -> Any:
        return await self._json("GET", f"/v1/requests/{request_id}", token)

    async def evict(self, token: str) -> None:
        await self._json("POST", "/v1/internal/evict", token)

    async def _open_stream(self, path: str, token: str, body: dict[str, Any]) -> httpx.Response:
        req = self._stream.build_request(
            "POST",
            f"{self._base}{path}",
            json=body,
            headers={**auth_headers(token), "Accept": "text/event-stream"},
        )
        try:
            resp = await self._stream.send(req, stream=True)
        except httpx.HTTPError:
            raise HttpError("connection", retryable=True) from None
        if resp.status_code != 200:
            try:
                await resp.aread()
                raise UpstreamStatus(
                    "agent", resp.status_code, error_code_of(resp), resp.headers.get("retry-after")
                )
            finally:
                await resp.aclose()
        return resp

    async def run(
        self, token: str, thread_id: str, text: str, client_msg_id: str
    ) -> httpx.Response:
        return await self._open_stream(
            f"/v1/threads/{thread_id}/runs",
            token,
            {"input": {"text": text}, "client_msg_id": client_msg_id},
        )

    async def resume(
        self, token: str, thread_id: str, interrupt_id: str, decision: dict[str, Any]
    ) -> httpx.Response:
        return await self._open_stream(
            f"/v1/threads/{thread_id}/resume",
            token,
            {"interrupt_id": interrupt_id, "decision": decision},
        )
