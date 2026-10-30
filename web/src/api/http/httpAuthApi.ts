import { request } from "../client";
import type { AuthApi, Me } from "../types";
import { LogoutSchema, MeSchema } from "../zod";

export class HttpAuthApi implements AuthApi {
  me(): Promise<Me> {
    return request("/api/me", { schema: MeSchema });
  }
  async logout(): Promise<{ redirectUrl: string }> {
    const r = await request("/auth/logout", { method: "POST", schema: LogoutSchema });
    return { redirectUrl: r.redirect_url };
  }
}
