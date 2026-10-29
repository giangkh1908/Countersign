export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly retryable: boolean,
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// TODO: đọc {code, message, retryable, request_id} từ body lỗi; ánh xạ mã -> thông điệp i18n.
export async function parseErrorBody(res: { status: number }): Promise<ApiError> {
  return new ApiError(res.status, "unknown", "", false);
}
