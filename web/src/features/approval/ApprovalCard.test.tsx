import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/errors";
import { FakeApprovalApi } from "../../api/fakes/FakeApprovalApi";
import type { CardModel } from "../../api/types";
import { fakeApi, renderWithProviders } from "../../test/renderWithProviders";
import { ApprovalCard } from "./ApprovalCard";

const INTERRUPT = { interrupt_id: "i1", intent_id: "n1", op: "close_ticket", expires_at: "2099-01-01T00:00:00Z" };

function field(over: Record<string, unknown>) {
  return { path: "p", label: "L", kind: "text", before: null, after: "x", changed: true, sensitive: false, ...over };
}

function card(fields: unknown[], over: Partial<CardModel> = {}): CardModel {
  const now = Date.now();
  return {
    interrupt_id: "i1",
    intent_id: "n1",
    op: "close_ticket",
    title: "Đóng ticket TCK-000123",
    risk: "medium",
    risk_flags: [],
    expires_at: new Date(now + 5 * 60_000).toISOString(),
    server_time: new Date(now).toISOString(),
    intent_sha256: "b".repeat(64),
    display_fields: fields,
    ...over,
  };
}

function setup(api: FakeApprovalApi, handlers = { onApprove: vi.fn(), onDecision: vi.fn() }) {
  renderWithProviders(
    <ApprovalCard threadId="t1" interrupt={INTERRUPT} busy={false} {...handlers} />,
    { api: fakeApi({ approvals: api }) },
  );
  return handlers;
}

afterEach(() => vi.useRealTimers());

describe("ApprovalCard", () => {
  it("hiển thị đủ display_fields, đánh dấu changed, che sensitive", async () => {
    setup(
      new FakeApprovalApi(
        card([
          field({ path: "target.ticket_code", label: "Ticket", kind: "ticket_ref", before: "TCK-000123", after: "TCK-000123", changed: false }),
          field({ path: "args.resolution", label: "Cách xử lý", kind: "longtext", before: null, after: "Đã thay mực" }),
          field({ path: "after.status", label: "Trạng thái mới", kind: "enum", before: "in_progress", after: "closed" }),
          field({ path: "args.internal", label: "Nội bộ", kind: "text", before: null, after: "bí-mật-xyz", sensitive: true }),
        ]),
      ),
    );
    expect(await screen.findByText("Ticket")).toBeInTheDocument();
    expect(screen.getByText("Cách xử lý")).toBeInTheDocument();
    expect(screen.getByText("Trạng thái mới")).toBeInTheDocument();
    expect(screen.getByText("Đã thay mực")).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveAttribute("data-sensitive", "true"); // sensitive lên đầu
    expect(items.filter((i) => i.getAttribute("data-changed") === "true")).toHaveLength(3);
    expect(screen.queryByText("bí-mật-xyz")).toBeNull(); // bị che
    await userEvent.click(screen.getByRole("button", { name: "Hiện" }));
    expect(screen.getByText("bí-mật-xyz")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Duyệt" })).not.toHaveAttribute("aria-disabled", "true");
  });

  it("bấm Duyệt gọi onApprove với intent_sha256 của thẻ", async () => {
    const h = setup(new FakeApprovalApi(card([field({})])));
    await userEvent.click(await screen.findByRole("button", { name: "Duyệt" }));
    expect(h.onApprove).toHaveBeenCalledWith("b".repeat(64));
  });

  it("intent_unrenderable (422) khoá Duyệt", async () => {
    const h = setup(new FakeApprovalApi(new ApiError(422, "intent_unrenderable", "", false)));
    expect(await screen.findByRole("alert")).toHaveTextContent("Không thể hiển thị");
    expect(screen.queryByRole("button", { name: "Duyệt" })).toBeNull();
    expect(screen.getByRole("button", { name: "Từ chối" })).toBeInTheDocument();
    expect(h.onApprove).not.toHaveBeenCalled();
  });

  it("kind lạ khoá Duyệt", async () => {
    const h = setup(new FakeApprovalApi(card([field({ kind: "html" })])));
    const btn = await screen.findByRole("button", { name: "Duyệt" });
    expect(btn).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(btn);
    expect(h.onApprove).not.toHaveBeenCalled();
  });

  it("bidi được escape và khoá Duyệt", async () => {
    setup(new FakeApprovalApi(card([field({ kind: "text", after: "tốt‮xấu" })])));
    expect(await screen.findByText("⟦U+202E⟧")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Duyệt" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText("Văn bản chứa ký tự ẩn")).toBeInTheDocument();
  });

  it("đếm ngược theo server_time và khoá khi hết hạn", async () => {
    // Fake timer bật TRƯỚC render để setInterval của Countdown chạy theo đồng hồ giả.
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"], shouldAdvanceTime: true });
    // Đồng hồ máy lệch +1 giờ so với server: hạn vẫn tính theo server_time.
    const serverNow = Date.now() - 3_600_000;
    const api = new FakeApprovalApi(
      card([field({})], {
        server_time: new Date(serverNow).toISOString(),
        expires_at: new Date(serverNow + 61_000).toISOString(),
      }),
    );
    setup(api);
    const cd = await screen.findByTestId("countdown");
    expect(cd.textContent).toMatch(/01:0\d|01:00/);
    expect(screen.getByRole("button", { name: "Duyệt" })).not.toHaveAttribute("aria-disabled", "true");
    // Cho thời gian trôi qua hạn 61 s.
    await act(async () => {
      vi.advanceTimersByTime(62_000);
    });
    expect(screen.getByTestId("countdown")).toHaveTextContent("Đã hết hạn");
    expect(screen.getByRole("button", { name: "Duyệt" })).toHaveAttribute("aria-disabled", "true");
  });

  it("Từ chối gọi onDecision reject kèm lý do", async () => {
    const h = setup(new FakeApprovalApi(card([field({})])));
    await userEvent.click(await screen.findByRole("button", { name: "Từ chối" }));
    await userEvent.type(screen.getByLabelText(/Lý do/), "không đúng");
    await userEvent.click(screen.getAllByRole("button", { name: "Từ chối" }).at(-1)!);
    expect(h.onDecision).toHaveBeenCalledWith({ type: "reject", reason: "không đúng" });
  });
});
