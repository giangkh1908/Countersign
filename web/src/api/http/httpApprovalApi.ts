import { request, sse } from "../client";
import type { ApprovalApi, CardModel, StreamSink } from "../types";
import { AgentEventSchema, CardSchema } from "../zod";

export class HttpApprovalApi implements ApprovalApi {
  verify(threadId: string, interruptId: string): Promise<CardModel> {
    return request("/api/intents/verify", {
      method: "POST",
      body: { thread_id: threadId, interrupt_id: interruptId },
      schema: CardSchema,
    });
  }

  approve(
    req: { threadId: string; interruptId: string; intentSha256: string },
    sink: StreamSink,
    signal: AbortSignal,
  ): Promise<void> {
    return sse("/api/approvals", {
      body: {
        thread_id: req.threadId,
        interrupt_id: req.interruptId,
        intent_sha256: req.intentSha256,
      },
      schema: AgentEventSchema,
      signal,
      onEvent: (e) => sink.onEvent(e),
      onError: (e) => sink.onError(e),
      onClose: () => sink.onClose(),
    });
  }
}
