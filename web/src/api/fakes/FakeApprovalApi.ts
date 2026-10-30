import type { ApiError } from "../errors";
import type { AgentEvent, ApprovalApi, CardModel, StreamSink } from "../types";

/** Trả CardModel dựng sẵn hoặc ném ApiError (410, 422). */
export class FakeApprovalApi implements ApprovalApi {
  readonly approvals: { threadId: string; interruptId: string; intentSha256: string }[] = [];

  constructor(
    private readonly card: CardModel | ApiError,
    private readonly approveScript: AgentEvent[] = [],
  ) {}

  async verify(): Promise<CardModel> {
    if (this.card instanceof Error) throw this.card;
    return this.card;
  }
  async approve(
    req: { threadId: string; interruptId: string; intentSha256: string },
    sink: StreamSink,
    signal: AbortSignal,
  ): Promise<void> {
    this.approvals.push(req);
    for (const e of this.approveScript) {
      if (signal.aborted) return;
      sink.onEvent(e);
    }
    sink.onClose();
  }
}
