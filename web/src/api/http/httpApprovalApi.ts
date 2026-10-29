import type { ApprovalApi, CardModel } from "../types";

// TODO: implement bằng request()/sse() của client.ts.
export class HttpApprovalApi implements ApprovalApi {
  verify(): Promise<CardModel> {
    return Promise.reject(new Error("TODO"));
  }
  approve(): Promise<void> {
    return Promise.reject(new Error("TODO"));
  }
}
