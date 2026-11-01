import type { AgentEvent, AgentStream, Decision, StreamSink } from "../types";

export type RunReq = { threadId: string | null; text: string; clientMsgId: string };
export type ResumeReq = { threadId: string; interruptId: string; decision: Decision };

/** Phát kịch bản sự kiện, hỗ trợ signal.abort. `resumeScript` dùng cho resume. */
export class FakeAgentStream implements AgentStream {
  readonly runs: RunReq[] = [];
  readonly resumes: ResumeReq[] = [];

  constructor(
    private readonly script: AgentEvent[] = [],
    private readonly resumeScript: AgentEvent[] = [],
  ) {}

  private async play(events: AgentEvent[], sink: StreamSink, signal: AbortSignal): Promise<void> {
    for (const e of events) {
      if (signal.aborted) return;
      await Promise.resolve();
      sink.onEvent(e);
    }
    if (!signal.aborted) sink.onClose();
  }

  run(req: RunReq, sink: StreamSink, signal: AbortSignal): Promise<void> {
    this.runs.push(req);
    return this.play(this.script, sink, signal);
  }
  resume(req: ResumeReq, sink: StreamSink, signal: AbortSignal): Promise<void> {
    this.resumes.push(req);
    return this.play(this.resumeScript, sink, signal);
  }
}
