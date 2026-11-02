// Thuần túy, test được không cần React.
import type { AgentEvent, AnswerStatus, Citation, InterruptRef, Sentence, VerifyInfo } from "../../api/types";

export interface ToolState {
  tool: string;
  status: "running" | "ok" | "failed";
  summary?: string;
}

export interface StreamState {
  phase: "idle" | "streaming" | "awaiting_approval" | "done" | "error";
  threadId: string | null;
  userText: string;
  text: string;
  route?: string;
  tools: Record<string, ToolState>;
  citations: Citation[];
  sentences?: Sentence[];
  answerStatus?: AnswerStatus;
  verify?: VerifyInfo;
  cost?: { turnUsd: number; threadUsd: number };
  interrupt?: InterruptRef;
  error?: { code: string; message: string; retryable: boolean };
}

export const initialStream: StreamState = {
  phase: "idle",
  threadId: null,
  userText: "",
  text: "",
  tools: {},
  citations: [],
};

export type StreamAction =
  | AgentEvent
  | { event: "start"; text: string; threadId: string | null }
  | { event: "resume_start" }
  | { event: "closed" }
  | { event: "settle" }
  | { event: "reset" };

export function streamReducer(s: StreamState, e: StreamAction): StreamState {
  switch (e.event) {
    case "reset":
      return initialStream;
    case "start":
      return { ...initialStream, phase: "streaming", userText: e.text, threadId: e.threadId };
    case "resume_start":
      return { ...s, phase: "streaming", error: undefined };
    case "thread":
      return { ...s, threadId: e.data.thread_id };
    case "run_start":
      return { ...s, phase: "streaming", threadId: e.data.thread_id ?? s.threadId };
    case "route":
      return { ...s, route: e.data.route };
    case "token":
      return { ...s, text: s.text + e.data.text };
    case "tool_start":
      return { ...s, tools: { ...s.tools, [e.data.call_id]: { tool: e.data.tool, status: "running" } } };
    case "tool_end": {
      const prev = s.tools[e.data.call_id] ?? { tool: "?", status: "running" as const };
      return {
        ...s,
        tools: {
          ...s.tools,
          [e.data.call_id]: { ...prev, status: e.data.ok ? "ok" : "failed", summary: e.data.summary },
        },
      };
    }
    case "interrupt":
      return { ...s, phase: "awaiting_approval", interrupt: e.data };
    case "approval":
      return { ...s, phase: "streaming" };
    case "citations":
      return {
        ...s,
        citations: e.data.items,
        sentences: e.data.sentences,
        answerStatus: e.data.answer_status,
        verify: e.data.verify,
      };
    case "cost":
      return { ...s, cost: { turnUsd: e.data.turn_usd, threadUsd: e.data.thread_usd } };
    case "done":
      return { ...s, phase: e.data.status === "interrupted" ? "awaiting_approval" : "done" };
    case "error":
      return { ...s, phase: "error", error: e.data };
    case "closed":
      // Luồng đóng mà chưa có done/error: coi là lỗi.
      return s.phase === "streaming"
        ? { ...s, phase: "error", error: { code: "stream_closed", message: "", retryable: true } }
        : s;
    case "settle":
      // Lịch sử đã làm mới: bỏ phần live, chỉ giữ thẻ duyệt đang chờ.
      return {
        ...initialStream,
        threadId: s.threadId,
        phase: s.phase === "awaiting_approval" && s.interrupt ? "awaiting_approval" : "idle",
        interrupt: s.phase === "awaiting_approval" ? s.interrupt : undefined,
      };
    default:
      return s;
  }
}
