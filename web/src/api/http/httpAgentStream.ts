import type { AgentStream } from "../types";

// TODO: implement bằng sse() của client.ts.
export class HttpAgentStream implements AgentStream {
  run(): Promise<void> {
    return Promise.reject(new Error("TODO"));
  }
  resume(): Promise<void> {
    return Promise.reject(new Error("TODO"));
  }
}
