import { request } from "../client";
import type { RequestCost, ThreadApi, ThreadMessages, ThreadPage } from "../types";
import { RequestCostSchema, ThreadMessagesSchema, ThreadPageSchema, VoidSchema } from "../zod";

export class HttpThreadApi implements ThreadApi {
  list(p: { limit: number; before?: string }): Promise<ThreadPage> {
    const q = new URLSearchParams({ limit: String(p.limit) });
    if (p.before) q.set("before", p.before);
    return request(`/api/threads?${q.toString()}`, { schema: ThreadPageSchema });
  }
  messages(threadId: string): Promise<ThreadMessages> {
    return request(`/api/threads/${encodeURIComponent(threadId)}/messages`, {
      schema: ThreadMessagesSchema,
    });
  }
  remove(threadId: string): Promise<void> {
    return request(`/api/threads/${encodeURIComponent(threadId)}`, {
      method: "DELETE",
      schema: VoidSchema,
    });
  }
  requestCost(requestId: string): Promise<RequestCost> {
    return request(`/api/requests/${encodeURIComponent(requestId)}`, { schema: RequestCostSchema });
  }
}
