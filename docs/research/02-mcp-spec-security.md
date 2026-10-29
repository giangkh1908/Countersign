# Research 02 — MCP spec, SDK, bảo mật (reader/Haiku, 2026-10-28)

## Spec & transport
- Spec hiện hành: **2026-07-28** (https://modelcontextprotocol.io/specification/versioning). Spec chuyển sang **stateless**: bỏ `initialize`, `Mcp-Session-Id`, SSE resumability; mỗi request mang `protocolVersion` trong `_meta`; thêm `server/discover`. Thêm MRTR (`resultType: "input_required"`) thay cho request do server khởi tạo. Deprecated: Roots, Sampling, Logging, HTTP+SSE, Dynamic Client Registration (thay bằng Client ID Metadata Documents). Changelog: https://modelcontextprotocol.io/specification/2026-07-28/changelog
- Transport: stdio, Streamable HTTP.

## Authorization (https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- MCP server = OAuth 2.1 **resource server**, bắt buộc Protected Resource Metadata (RFC 9728). Client gửi `resource` (RFC 8707).
- Server **MUST** kiểm tra audience của token là chính nó và **MUST NOT** chấp nhận hay chuyển tiếp token khác (cấm token passthrough). Step-up qua `WWW-Authenticate: insufficient_scope`.

## SDK Python
- `mcp` **2.3.0** (2026-10-02): `from mcp.server import MCPServer`, `@mcp.tool()`. https://pypi.org/project/mcp/
- `fastmcp` **4.1.4** (2026-10-26). Docs cũ: `FastMCP(auth=...)`, `get_access_token()` từ `fastmcp.server.dependencies`. **Chưa xác minh trên 4.x / mcp 2.x → cần spike.**

## Rủi ro
- Tool poisoning / rug pull (https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks). Biện pháp: pin version, băm mô tả tool.
- Confused deputy, token passthrough: https://modelcontextprotocol.io/specification/latest/basic/security_best_practices
- Injection qua kết quả tool: GitHub MCP 05/2025 (https://invariantlabs.ai/blog/mcp-github-vulnerability); "lethal trifecta" Supabase MCP (https://simonwillison.net/2025/Jul/6/supabase-mcp-lethal-trifecta/).
- CVE: CVE-2025-6514 mcp-remote (9.6, command injection); CVE-2025-49596 MCP Inspector (RCE).
- Annotation (`readOnlyHint`, `destructiveHint`) = gợi ý, **không đáng tin** → không dùng để phân quyền. Elicitation (accept/decline/cancel) dùng được cho xác nhận, nhưng spec 2026-07-28 đổi sang MRTR → kiểm tra SDK.

## DB chỉ đọc
- Postgres RLS: `ENABLE` + `FORCE ROW LEVEL SECURITY`; superuser và `BYPASSRLS` vượt qua RLS; bật RLS mà không có policy thì không thấy dòng nào (https://www.postgresql.org/docs/current/ddl-rowsecurity.html).
- sqlglot 30.25.0 để parse AST. Pattern: role chỉ SELECT trên view, RLS, chỉ cho `Select` ở gốc, cấm nhiều câu lệnh, cấm schema hệ thống, ép LIMIT, `statement_timeout`. Ưu tiên tool có tham số thay cho raw SQL.
