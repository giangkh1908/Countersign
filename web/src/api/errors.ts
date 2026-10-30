import { ErrorBodySchema } from "./zod";

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

/** Đọc `{"error":{code,message,retryable,request_id}}` (contracts §6.4); body lạ -> mã `unknown`. */
export async function parseErrorBody(res: Response): Promise<ApiError> {
  try {
    const parsed = ErrorBodySchema.safeParse(await res.json());
    if (parsed.success) {
      const e = parsed.data.error;
      return new ApiError(res.status, e.code, e.message, e.retryable, e.request_id);
    }
  } catch {
    /* body không phải JSON */
  }
  return new ApiError(res.status, "unknown", "", res.status >= 500);
}
