from fastapi.testclient import TestClient
from mcp_docs.main import _LazyApp, build_runtime
from mcp_docs.settings import Settings


def test_healthz_and_unauthenticated_mcp(monkeypatch) -> None:
    monkeypatch.setenv("MCP_DATABASE_URL", "postgresql://kn_app@localhost:1/knowledge")
    with TestClient(_LazyApp()) as c:  # chạy lifespan của host
        assert c.get("/healthz").json() == {"status": "ok"}
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 401
        assert c.post("/internal/taint/forget", json={"thread_id": "t"}).status_code == 401


def test_tool_registered_with_readonly_annotations() -> None:
    rt = build_runtime(Settings(mcp_database_url="postgresql://x@localhost:1/k", mcp_host="fake"))
    (tool,) = rt.host.tool_manifest()
    assert tool["name"] == "search_documents"
    assert tool["inputSchema"]["additionalProperties"] is False
    assert set(tool["inputSchema"]["properties"]) == {"query", "top_k", "department_filter"}
