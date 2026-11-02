import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CitationsDataSchema } from "../../api/zod";
import { CitedMessage, type CitationInfo } from "./CitedMessage";

const PASSAGE = "Người lao động có quyền đơn phương chấm dứt hợp đồng lao động. Phải báo trước theo quy định.";
const CHAR_START = 1204;
const EV = "Phải báo trước theo quy định.";
const EV_START = CHAR_START + PASSAGE.indexOf(EV);

const ANSWER = "Người lao động được nghỉ việc [1]. Mức bồi thường là 3 tháng lương [2].";
const S1_END = ANSWER.indexOf(".") + 1;

function info(over: Partial<CitationInfo> = {}): CitationInfo {
  return {
    items: [
      {
        n: 1,
        doc_id: "d1",
        doc_num: "45/2019/QH14",
        title: "Bộ luật Lao động",
        article: "35",
        clause: "1",
        chapter: "Chương IV",
        heading: "Điều 35. Quyền đơn phương chấm dứt",
        char_start: CHAR_START,
        char_end: CHAR_START + PASSAGE.length,
        snippet: PASSAGE.slice(0, 50),
        passage: PASSAGE,
        evidence_start: EV_START,
        evidence_end: EV_START + EV.length,
        verdict: "supported",
      },
      { n: 2, doc_id: "d2", title: "Nghị định 145", passage: "Không nói về bồi thường.", verdict: "unsupported" },
    ],
    sentences: [
      { id: 0, start: 0, end: S1_END, cites: [1], verdict: "supported" },
      { id: 1, start: S1_END + 1, end: Array.from(ANSWER).length, cites: [2], verdict: "unsupported" },
    ],
    answerStatus: "partially_verified",
    verify: { enabled: true, pairs: 2, judge_calls: 2, ms: 900 },
    ...over,
  };
}

function view(text: string, i: CitationInfo) {
  return render(<CitedMessage text={text} info={i} linkHosts={[]} />);
}

describe("CitedMessage", () => {
  it("[n] là nút; bấm mở đoạn nguồn với văn bản, Điều, khoản và tô đúng câu được trích", async () => {
    view(ANSWER, info());
    expect(screen.queryByTestId("source-panel")).toBeNull();
    await userEvent.click(screen.getAllByRole("button", { name: "Mở nguồn 1" })[0]!);
    const panel = screen.getByTestId("source-panel");
    expect(within(panel).getByText(/Bộ luật Lao động/)).toBeInTheDocument();
    expect(within(panel).getByText(/45\/2019\/QH14/)).toBeInTheDocument();
    expect(within(panel).getByText(/Điều 35, khoản 1/)).toBeInTheDocument();
    expect(within(panel).getByTestId("evidence").textContent).toBe(EV);
    expect(screen.getByTestId("passage").textContent).toBe(PASSAGE);
  });

  it("bấm lại cùng [n] hoặc nút Đóng thì đóng panel; mở nguồn khác thì đổi nội dung", async () => {
    view(ANSWER, info());
    await userEvent.click(screen.getAllByRole("button", { name: "Mở nguồn 1" })[0]!);
    await userEvent.click(screen.getAllByRole("button", { name: "Mở nguồn 2" })[0]!);
    expect(screen.getByTestId("passage").textContent).toBe("Không nói về bồi thường.");
    expect(screen.queryByTestId("evidence")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Đóng" }));
    expect(screen.queryByTestId("source-panel")).toBeNull();
  });

  it("câu không được hỗ trợ có nhãn chữ; câu supported thì không", () => {
    view(ANSWER, info());
    const flagged = document.querySelectorAll("[data-verdict]");
    expect(flagged).toHaveLength(1);
    expect(flagged[0]!.textContent).toContain("Mức bồi thường là 3 tháng lương");
    expect(within(flagged[0] as HTMLElement).getByText("Không được nguồn hỗ trợ")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/chưa được kiểm chứng/);
  });

  it("nhãn 'Chưa kiểm chứng' cho verdict unverified", () => {
    const i = info();
    i.sentences![1]!.verdict = "unverified";
    view(ANSWER, i);
    expect(within(document.querySelector("[data-verdict]") as HTMLElement).getByText("Chưa kiểm chứng")).toBeInTheDocument();
  });

  it("verify.enabled=false thì không hiện cảnh báo nào", () => {
    view(
      ANSWER,
      info({ verify: { enabled: false }, answerStatus: "answered", sentences: [] }),
    );
    expect(document.querySelectorAll("[data-verdict]")).toHaveLength(0);
    expect(screen.queryByText("Chưa kiểm chứng")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("answer_status=refused hiện trạng thái không tìm thấy trong tài liệu", () => {
    view("Không tìm thấy trong tài liệu. Hãy thử nêu rõ tên văn bản.", {
      items: [],
      answerStatus: "refused",
      verify: { enabled: true },
    });
    expect(screen.getByRole("status")).toHaveTextContent("Không tìm thấy trong tài liệu.");
    expect(screen.queryByRole("button", { name: /Mở nguồn/ })).toBeNull();
  });

  it("[n] không có trong items giữ là chữ, không thành nút", () => {
    view("Có nguồn [1] và nguồn lạ [9].", info({ sentences: undefined }));
    expect(screen.getAllByRole("button", { name: "Mở nguồn 1" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Mở nguồn 9" })).toBeNull();
    expect(screen.getByTestId("cited-answer").textContent).toContain("[9]");
  });

  it("dữ liệu cũ không có n/passage: đánh số theo vị trí, dùng snippet", async () => {
    view("Theo quy chế [1].", { items: [{ title: "Quy chế", heading: "Điều 1", snippet: "Nội dung ngắn" }] });
    await userEvent.click(screen.getAllByRole("button", { name: "Mở nguồn 1" })[0]!);
    expect(screen.getByTestId("passage").textContent).toBe("Nội dung ngắn");
  });

  it("offset lệch phạm vi thì không tô, vẫn hiện đoạn", async () => {
    const i = info();
    i.items[0]!.evidence_start = 99999;
    i.items[0]!.evidence_end = 100010;
    view(ANSWER, i);
    await userEvent.click(screen.getAllByRole("button", { name: "Mở nguồn 1" })[0]!);
    expect(screen.queryByTestId("evidence")).toBeNull();
    expect(screen.getByTestId("passage").textContent).toBe(PASSAGE);
  });

  it("không lộ delimiter/datamark spotlight ra người đọc", async () => {
    const marked = "<<BEGIN_UNTRUSTED:xyz>>^Người^lao^động^có^quyền^<<END_UNTRUSTED:xyz>>";
    view("Có quyền [1].", { items: [{ n: 1, title: "Luật", passage: marked, char_start: 0, evidence_start: 0, evidence_end: 5 }] });
    await userEvent.click(screen.getAllByRole("button", { name: "Mở nguồn 1" })[0]!);
    const text = screen.getByTestId("passage").textContent ?? "";
    expect(text).not.toMatch(/UNTRUSTED|\^/);
    expect(text.trim().replace(/\s+/g, " ")).toBe("Người lao động có quyền");
    expect(screen.queryByTestId("evidence")).toBeNull();
  });

  it("nội dung chứa HTML/script hiển thị thành chữ, không sinh phần tử", async () => {
    const evil = '<script>window.__pwn=1</script><img src="https://evil.test/x.png" onerror="window.__pwn=1"><b>đậm</b>';
    view("Theo tài liệu <i>x</i> [1].", {
      items: [
        {
          n: 1,
          title: '<img src=x onerror="window.__pwn=1">Luật',
          heading: "<u>Điều 1</u>",
          chapter: "<script>1</script>",
          passage: evil,
          snippet: evil,
        },
      ],
    });
    await userEvent.click(screen.getAllByRole("button", { name: "Mở nguồn 1" })[0]!);
    const root = document.body;
    expect(screen.getByTestId("passage").textContent).toBe(evil);
    expect(root.querySelector("script")).toBeNull();
    expect(root.querySelector("img")).toBeNull();
    expect(root.querySelector("b")).toBeNull();
    expect(root.querySelector("u")).toBeNull();
    expect(root.querySelector("i")).toBeNull();
    expect((window as unknown as { __pwn?: number }).__pwn).toBeUndefined();
    expect(screen.getByTestId("cited-answer").textContent).toContain("<i>x</i>");
  });
});

describe("CitationsDataSchema", () => {
  it("nhận khung citations theo mục 5.4 và dữ liệu cũ", () => {
    const full = CitationsDataSchema.parse({
      items: [{ n: 1, title: "T", passage: "p", evidence_start: 1, evidence_end: 2, verdict: "supported", sentence_ids: [0], score: 0.03 }],
      sentences: [{ id: 0, start: 0, end: 5, cites: [1], verdict: "supported" }],
      answer_status: "answered",
      verify: { enabled: true, pairs: 1, judge_calls: 1, ms: 5 },
    });
    expect(full.items[0]!.verdict).toBe("supported");
    expect(CitationsDataSchema.parse({ items: [{ title: "Cũ" }] }).items[0]!.title).toBe("Cũ");
  });
  it("verdict lạ coi là unverified, không bao giờ supported", () => {
    const r = CitationsDataSchema.parse({ items: [{ title: "T", verdict: "great" }] });
    expect(r.items[0]!.verdict).toBe("unverified");
  });
  it("answer_status ngoài tập cho phép bị từ chối", () => {
    expect(CitationsDataSchema.safeParse({ items: [], answer_status: "weird" }).success).toBe(false);
  });
});
