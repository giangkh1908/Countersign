import type { RequestCost, ThreadApi, ThreadMessages, ThreadPage } from "../types";

// TODO: implement bằng request() của client.ts.
export class HttpThreadApi implements ThreadApi {
  list(): Promise<ThreadPage> {
    return Promise.reject(new Error("TODO"));
  }
  messages(): Promise<ThreadMessages> {
    return Promise.reject(new Error("TODO"));
  }
  remove(): Promise<void> {
    return Promise.reject(new Error("TODO"));
  }
  requestCost(): Promise<RequestCost> {
    return Promise.reject(new Error("TODO"));
  }
}
