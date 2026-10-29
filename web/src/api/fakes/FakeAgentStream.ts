import type { AgentEvent, AgentStream, StreamSink } from "../types";

// TODO: phát kịch bản sự kiện có độ trễ, hỗ trợ signal.abort.
export class FakeAgentStream implements AgentStream {
  constructor(private readonly script: AgentEvent[] = []) {}

  async run(_req: unknown, sink: StreamSink): Promise<void> {
    this.script.forEach((e) => sink.onEvent(e));
    sink.onClose();
  }
  async resume(_req: unknown, sink: StreamSink): Promise<void> {
    sink.onClose();
  }
}
