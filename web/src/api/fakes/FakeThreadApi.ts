import type {
  AuthApi,
  Me,
  RequestCost,
  ThreadApi,
  ThreadMessages,
  ThreadPage,
  ThreadSummary,
} from "../types";

/** Giữ danh sách thread trong bộ nhớ. */
export class FakeThreadApi implements ThreadApi {
  constructor(
    public items: ThreadSummary[] = [],
    public history: Record<string, ThreadMessages> = {},
  ) {}

  async list(): Promise<ThreadPage> {
    return { items: [...this.items], next_before: null };
  }
  async messages(threadId: string): Promise<ThreadMessages> {
    return this.history[threadId] ?? { messages: [], pending_interrupt: null, cost: {} };
  }
  async remove(threadId: string): Promise<void> {
    this.items = this.items.filter((t) => t.thread_id !== threadId);
  }
  async requestCost(requestId: string): Promise<RequestCost> {
    return { request_id: requestId, cost_usd: 0 };
  }
}

export class FakeAuthApi implements AuthApi {
  loggedOut = false;
  constructor(
    private readonly user: Me = {
      sub: "u1",
      name: "Người Dùng",
      email: "u@example.com",
      roles: [],
      link_allowlist: [],
    },
  ) {}
  async me(): Promise<Me> {
    return this.user;
  }
  async logout(): Promise<{ redirectUrl: string }> {
    this.loggedOut = true;
    return { redirectUrl: "/" };
  }
}
