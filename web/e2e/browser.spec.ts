// E2E trình duyệt thật qua BFF: đăng nhập Keycloak, chat một vòng với LLM mock, và các khẳng định
// bảo mật phía trình duyệt. Cần stack compose đang chạy. Tác dụng phụ (dev): đặt lại mật khẩu hoa.ngo
// bằng mật khẩu ngẫu nhiên (chỉ trong bộ nhớ). Backup trước (pg_dumpall).
import { expect, test, type Page, type Response } from "@playwright/test";
import { setRandomPassword } from "./support/stack";

const USER = "hoa.ngo";
const ORIGIN = "http://localhost:8300";
const JWT = /eyJ[\w-]+\.[\w-]+\.[\w-]+/;

/** JWT thật = ba đoạn, đoạn đầu giải mã ra JSON có `alg` (loại JWE/cookie nội bộ của Keycloak, blob base64 JSON). */
function hasJwt(text: string): boolean {
  const g = new RegExp(JWT.source, "g");
  return (text.match(g) ?? []).some((cand) => {
    try {
      const head = JSON.parse(Buffer.from(cand.split(".")[0]!, "base64url").toString("utf-8")) as { alg?: string };
      return typeof head.alg === "string";
    } catch {
      return false;
    }
  });
}
const CHAT_BOX = "Nhập câu hỏi cho trợ lý";

test.describe.configure({ mode: "serial" });

let password = "";
const scans: Promise<string | null>[] = [];
let cspHeader = "";

/** Quét mọi response trang thấy: URL, header, body (SSE có body khi luồng kết thúc). */
function watch(page: Page): void {
  page.on("response", (res: Response) => {
    if (res.url().startsWith(ORIGIN) && !cspHeader) {
      cspHeader = res.headers()["content-security-policy"] ?? "";
    }
    // Chỉ quét bề mặt của BFF. Keycloak tự đặt cookie SSO KEYCLOAK_IDENTITY (JWT, HttpOnly) trên origin của nó:
    // đó là phiên IdP, JS của SPA không đọc được; không thuộc phạm vi "token không xuống trình duyệt" của BFF.
    if (!res.url().startsWith(ORIGIN)) return;
    scans.push(
      (async () => {
        if (hasJwt(res.url())) return `${res.url()} (url)`;
        if (hasJwt(JSON.stringify(await res.allHeaders()))) return `${res.url()} (header)`;
        try {
          return hasJwt((await res.body()).toString("latin1")) ? `${res.url()} (body)` : null;
        } catch {
          return null; // redirect: không có body để đọc
        }
      })(),
    );
  });
}

async function login(page: Page): Promise<void> {
  await page.goto("/");
  await page.waitForURL(/keycloak\.acme\.local:8080\/realms\/acme\//);
  await page.locator("#username").fill(USER);
  await page.locator("#password").fill(password);
  await page.locator("#kc-login").click();
  await page.waitForURL(/localhost:8300\//);
  await expect(page.getByRole("textbox", { name: CHAT_BOX })).toBeVisible();
}

test.beforeAll(async () => {
  ({ password } = await setRandomPassword(USER));
});

test("đăng nhập thật, chat một vòng có stream, và bảo mật phía trình duyệt", async ({ page, context }) => {
  watch(page);
  await login(page);

  const done = page.waitForResponse((r) => r.url().endsWith("/api/chat") && r.request().method() === "POST");
  await page.getByRole("textbox", { name: CHAT_BOX }).fill("Xin chào, bạn có thể giúp gì?");
  await page.getByRole("button", { name: "Gửi" }).click();
  const res = await done;
  expect(res.status()).toBe(200);
  expect(res.headers()["content-type"]).toContain("text/event-stream");
  // Câu trả lời stream từ LLM mock hiện trong khung chat (mock luôn bắt đầu bằng "mock").
  await expect(page.getByRole("log").getByText(/^mock\w+ /)).toBeVisible();

  // ---- storage / cookie đọc được bằng JS ----
  const storage = await page.evaluate(() => ({
    local: JSON.stringify({ ...localStorage }),
    session: JSON.stringify({ ...sessionStorage }),
    cookie: document.cookie,
  }));
  for (const s of [storage.local, storage.session, storage.cookie]) {
    expect(s).not.toMatch(JWT);
    expect(s).not.toMatch(/access_token|refresh_token|id_token/i);
  }
  expect(storage.cookie).not.toMatch(/(^|;\s*)(__Host-)?sid=/);

  // ---- cookie phiên ----
  const cookies = (await context.cookies(ORIGIN)).filter((c) => /(^|-)sid$/.test(c.name));
  expect(cookies).toHaveLength(1);
  const sid = cookies[0]!;
  // Dev chạy http: bff dùng tên `sid` (không tiền tố), không đặt Secure; `__Host-sid` + Secure khi https.
  expect(sid.name).toBe("sid");
  expect(sid.httpOnly).toBe(true);
  expect(sid.sameSite).toBe("Strict");
  expect(sid.path).toBe("/");
  expect(sid.value).not.toMatch(JWT);

  // ---- CSP ----
  const scriptSrc = /script-src([^;]*)/.exec(cspHeader)?.[1] ?? "";
  expect(scriptSrc).toContain("'self'");
  expect(scriptSrc).not.toContain("unsafe-inline");
  expect(scriptSrc).not.toContain("unsafe-eval");

  // ---- không JWT trong response nào ----
  const hits = (await Promise.all(scans)).filter((x) => x !== null);
  expect(hits, "JWT lộ trong response").toEqual([]);
});

test("CSRF: request đổi trạng thái thiếu header X-CSRF-Token bị 403", async ({ page }) => {
  await login(page);
  const ghost = `${ORIGIN}/api/threads/00000000-0000-0000-0000-000000000000`;
  const bad = await page.request.delete(ghost, { headers: { Origin: ORIGIN } });
  expect(bad.status()).toBe(403);
  expect(await bad.text()).toContain("csrf_failed");
  const noHeaderPost = await page.request.post(`${ORIGIN}/api/chat`, {
    headers: { Origin: ORIGIN },
    data: { text: "xin chào" },
  });
  expect(noHeaderPost.status()).toBe(403);

  // đối chứng: có header đúng thì qua tầng CSRF
  const csrf = await page.evaluate(async () => {
    const r = await fetch("/api/me");
    return ((await r.json()) as { csrf_token: string }).csrf_token;
  });
  const ok = await page.request.delete(ghost, { headers: { Origin: ORIGIN, "X-CSRF-Token": csrf } });
  expect(ok.status()).not.toBe(403);
});
