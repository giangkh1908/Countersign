import { sse } from "../client";
import type { AgentStream, Decision, StreamSink } from "../types";
import { AgentEventSchema } from "../zod";

function decisionBody(d: Decision): Record<string, unknown> {
  if (d.type === "edit") return { type: "edit", edits: d.edits };
  if (d.type === "reject") return d.reason ? { type: "reject", reason: d.reason } : { type: "reject" };
  return { type: "refresh" };
}

export class HttpAgentStream implements AgentStream {
  run(
    req: { threadId: string | null; text: string; clientMsgId: string },
    sink: StreamSink,
    signal: AbortSignal,
  ): Promise<void> {
    return sse("/api/chat", {
      body: {
        ...(req.threadId ? { thread_id: req.threadId } : {}),
        text: req.text,
        client_msg_id: req.clientMsgId,
      },
      schema: AgentEventSchema,
      signal,
      onEvent: (e) => sink.onEvent(e),
      onError: (e) => sink.onError(e),
      onClose: () => sink.onClose(),
    });
  }

  resume(
    req: { threadId: string; interruptId: string; decision: Decision },
    sink: StreamSink,
    signal: AbortSignal,
  ): Promise<void> {
    return sse("/api/resume", {
      body: {
        thread_id: req.threadId,
        interrupt_id: req.interruptId,
        decision: decisionBody(req.decision),
      },
      schema: AgentEventSchema,
      signal,
      onEvent: (e) => sink.onEvent(e),
      onError: (e) => sink.onError(e),
      onClose: () => sink.onClose(),
    });
  }
}
