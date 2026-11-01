import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { FakeAgentStream } from "../../api/fakes/FakeAgentStream";
import { FakeThreadApi } from "../../api/fakes/FakeThreadApi";
import type { Api } from "../../api/types";
import { fakeApi, renderWithProviders } from "../../test/renderWithProviders";
import { ChatPage } from "./ChatPage";

const TID = "11111111-1111-1111-1111-111111111111";

function renderChat(agent: FakeAgentStream, over: Partial<Api> = {}) {
  renderWithProviders(
    <Routes>
      <Route path="/" element={<ChatPage />} />
      <Route path="/t/:threadId" element={<ChatPage />} />
    </Routes>,
    { api: fakeApi({ agent, ...over }) },
  );
}

async function ask(text: string) {
  await userEvent.type(screen.getByLabelText("Nhập câu hỏi cho trợ lý"), text);
  await userEvent.click(screen.getByRole("button", { name: "Gửi" }));
}

describe("ChatPage", () => {
  it("luồng token/tool/citations/cost rồi done; lịch sử làm mới thay phần live", async () => {
    const agent = new FakeAgentStream([
      { event: "thread", data: { thread_id: TID } },
      { event: "run_start", data: {} },
      { event: "tool_start", data: { call_id: "c1", tool: "search_docs" } },
      { event: "tool_end", data: { call_id: "c1", ok: true, summary: "5 đoạn" } },
      { event: "token", data: { text: "Xin " } },
      { event: "token", data: { text: "**chào**" } },
      { event: "citations", data: { items: [{ title: "Quy chế", heading: "Điều 1" }] } },
      { event: "cost", data: { turn_usd: 0.0031, thread_usd: 0.0214 } },
      { event: "done", data: { status: "completed", message_id: "m1" } },
    ]);
    const threads = new FakeThreadApi([], {
      [TID]: {
        messages: [
          { role: "user", content: "chào bạn" },
          { role: "assistant", content: "Xin **chào**", citations: [{ title: "Quy chế", heading: "Điều 1" }] },
        ],
        pending_interrupt: null,
        cost: {},
      },
    });
    renderChat(agent, { threads });
    await ask("chào bạn");
    await waitFor(() => expect(agent.runs[0]).toMatchObject({ threadId: null, text: "chào bạn" }));
    expect(await screen.findByText("chào", { selector: "strong" })).toBeInTheDocument();
    expect(await screen.findByText(/Quy chế/)).toBeInTheDocument();
  });

  it("lỗi theo mã khi luồng báo error, giữ phần đã nhận", async () => {
    const agent = new FakeAgentStream([
      { event: "run_start", data: {} },
      { event: "token", data: { text: "một phần" } },
      { event: "error", data: { code: "rate_limited", message: "raw", retryable: false } },
    ]);
    renderChat(agent);
    await ask("hi");
    expect(await screen.findByRole("alert")).toHaveTextContent("Bạn thao tác quá nhanh");
    expect(screen.getByText("một phần")).toBeInTheDocument();
  });

  it("luồng đóng mà không có done -> báo lỗi", async () => {
    renderChat(new FakeAgentStream([{ event: "run_start", data: {} }]));
    await ask("hi");
    expect(await screen.findByRole("alert")).toHaveTextContent("Luồng trả lời bị ngắt");
  });

  it("interrupt dựng thẻ duyệt từ verify", async () => {
    const agent = new FakeAgentStream([
      { event: "thread", data: { thread_id: TID } },
      { event: "run_start", data: {} },
      {
        event: "interrupt",
        data: { interrupt_id: "i1", intent_id: "n1", op: "close_ticket", expires_at: "2099-01-01T00:00:00Z" },
      },
      { event: "done", data: { status: "interrupted", message_id: "m1" } },
    ]);
    renderChat(agent);
    await ask("đóng ticket");
    expect(await screen.findByRole("group")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Từ chối" })).toBeInTheDocument();
  });
});
