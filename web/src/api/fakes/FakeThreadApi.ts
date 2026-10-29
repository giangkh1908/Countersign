import type { RequestCost, ThreadApi, ThreadMessages, ThreadPage } from "../types";

// TODO: giữ danh sách thread trong bộ nhớ.
export class FakeThreadApi implements ThreadApi {
  async list(): Promise<ThreadPage> {
    return { items: [] };
  }
  async messages(): Promise<ThreadMessages> {
    return { items: [] };
  }
  async remove(): Promise<void> {}
  async requestCost(): Promise<RequestCost> {
    return {};
  }
}
