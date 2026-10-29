# web — SPA trợ lý AI nội bộ

Vite + React 18 + TypeScript strict, pnpm. Thiết kế: `docs/design/07-web-bff.md` §3.

```
pnpm install
pnpm dev          # http://localhost:5173, proxy /api và /auth -> http://localhost:8300 (BFF)
pnpm typecheck && pnpm lint && pnpm test
pnpm build        # tsc -b && vite build
pnpm gen:api      # sinh src/api/schema.d.ts từ BFF (cần BFF đang chạy)
pnpm e2e          # Playwright (cần `playwright install` trước)
```

Quy tắc: `src/api/client.ts` là file DUY NHẤT được dùng `fetch`/SSE (kể cả import
`@microsoft/fetch-event-source`). Component nhận `AgentStream`/`ApprovalApi`/`ThreadApi` qua context;
test dùng `api/fakes/*` hoặc MSW. Không lưu token ở trình duyệt, không `dangerouslySetInnerHTML`.
