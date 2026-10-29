import type { ApprovalApi, CardModel } from "../types";

// TODO: trả CardModel dựng sẵn hoặc ném ApiError (410, 422).
export class FakeApprovalApi implements ApprovalApi {
  async verify(): Promise<CardModel> {
    return {};
  }
  async approve(): Promise<void> {}
}
