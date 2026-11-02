// E2E trích dẫn (R2): bấm [n] mở đoạn nguồn và tô câu được trích; câu chưa kiểm chứng có nhãn;
// trạng thái "không tìm thấy". API của BFF được giả bằng page.route nên không cần đăng nhập Keycloak,
// nhưng cần SPA đang được phục vụ ở baseURL (stack compose hoặc `pnpm dev` trỏ cùng origin).
import { expect, test, type Page } from "@playwright/test";

const TID = "11111111-1111-1111-1111-111111111111";
const PASSAGE = "Người lao động có quyền đơn phương chấm dứt hợp đồng lao động. Phải báo trước theo quy định.";
const EVIDENCE = "Phải báo trước theo quy định.";
const CHAR_START = 500;

function sse(events: { event: string; data: unknown }[]): string {
  return events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join("");
}

async function mockBff(page: Page, citations: unknown, text: string): Promise<void> {
  await page.route("**/api/me", (r) =>
    r.fulfill({ json: { sub: "u", name: "Hoa", email: "h@acme.local", roles: [], link_allowlist: [] } }),
  );
  await page.route("**/api/threads?*", (r) => r.fulfill({ json: { items: [], next_before: null } }));
  // Sau `done` SPA nạp lại lịch sử: trả về cùng nội dung để giao diện không biến mất.
  const c = citations as Record<string, unknown>;
  await page.route(`**/api/threads/${TID}/messages`, (r) =>
    r.fulfill({
      json: {
        messages: [
          { role: "user", content: "hỏi" },
          { role: "assistant", content: text, citations: c.items, sentences: c.sentences, answer_status: c.answer_status, verify: c.verify },
        ],
        pending_interrupt: null,
        cost: {},
      },
    }),
  );
  await page.route("**/api/chat", (r) =>
    r.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body: sse([
        { event: "thread", data: { thread_id: TID } },
        { event: "token", data: { text } },
        { event: "citations", data: citations },
        { event: "done", data: { status: "completed" } },
      ]),
    }),
  );
}

async function ask(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("Nhập câu hỏi cho trợ lý").fill("hỏi");
  await page.getByRole("button", { name: "Gửi" }).click();
}

test("bấm [n] mở đoạn nguồn, tô đúng câu; câu không được hỗ trợ có nhãn", async ({ page }) => {
  const text = "Người lao động được nghỉ việc [1]. Bồi thường 3 tháng lương [2].";
  const cut = Array.from(text).indexOf(".") + 1;
  await mockBff(
    page,
    {
      items: [
        {
          n: 1, title: "Bộ luật Lao động", doc_num: "45/2019/QH14", article: "35", clause: "1",
          passage: PASSAGE, char_start: CHAR_START, char_end: CHAR_START + PASSAGE.length,
          evidence_start: CHAR_START + PASSAGE.indexOf(EVIDENCE), evidence_end: CHAR_START + PASSAGE.indexOf(EVIDENCE) + EVIDENCE.length,
          verdict: "supported",
        },
        { n: 2, title: "Nghị định 145", passage: "Không nói về bồi thường.", verdict: "unsupported" },
      ],
      sentences: [
        { id: 0, start: 0, end: cut, cites: [1], verdict: "supported" },
        { id: 1, start: cut + 1, end: Array.from(text).length, cites: [2], verdict: "unsupported" },
      ],
      answer_status: "partially_verified",
      verify: { enabled: true },
    },
    text,
  );
  await ask(page);
  await page.getByRole("button", { name: "Mở nguồn 1" }).first().click();
  await expect(page.getByTestId("source-panel")).toContainText("Điều 35, khoản 1");
  await expect(page.getByTestId("evidence")).toHaveText(EVIDENCE);
  await expect(page.getByText("Không được nguồn hỗ trợ").first()).toBeVisible();
});

test("câu hỏi ngoài tài liệu hiện trạng thái không tìm thấy", async ({ page }) => {
  await mockBff(
    page,
    { items: [], answer_status: "refused", verify: { enabled: true } },
    "Không tìm thấy trong tài liệu. Hãy nêu rõ tên văn bản.",
  );
  await ask(page);
  await expect(page.getByRole("status")).toContainText("Không tìm thấy trong tài liệu");
});
