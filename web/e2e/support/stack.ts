// Helper E2E: nói chuyện với stack compose đang chạy và Keycloak Admin API.
// Cùng ý tưởng với eval/e2e/close_ticket.py, nhưng gọn: không giữ token người dùng, không in secret.
import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const KC = "http://localhost:8080";
const REALM = "acme";

export function secret(name: string): string {
  // worktree không có secrets/: cho phép trỏ về thư mục của repo chính (cùng quy ước với eval/e2e/close_ticket.py)
  const dir = process.env.SECRETS_DIR ?? path.join(ROOT, "secrets");
  return readFileSync(path.join(dir, name), "utf-8").trim();
}

/** Đặt mật khẩu ngẫu nhiên (chỉ trong bộ nhớ) cho user test qua Keycloak Admin API. */
export async function setRandomPassword(username: string): Promise<{ password: string; sub: string }> {
  const tok = await fetch(`${KC}/realms/master/protocol/openid-connect/token`, {
    method: "POST",
    body: new URLSearchParams({
      grant_type: "password",
      client_id: "admin-cli",
      username: "admin",
      password: secret("kc_admin_password"),
    }),
  });
  if (!tok.ok) throw new Error(`keycloak admin token: ${tok.status}`);
  const headers = { Authorization: `Bearer ${((await tok.json()) as { access_token: string }).access_token}` };
  const base = `${KC}/admin/realms/${REALM}`;
  const users = (await (
    await fetch(`${base}/users?username=${encodeURIComponent(username)}&exact=true`, { headers })
  ).json()) as { id: string }[];
  const uid = users[0]?.id;
  if (!uid) throw new Error(`user ${username} not found`);
  const password = randomBytes(18).toString("base64url");
  const r = await fetch(`${base}/users/${uid}/reset-password`, {
    method: "PUT",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ type: "password", value: password, temporary: false }),
  });
  if (!r.ok) throw new Error(`reset-password: ${r.status}`);
  return { password, sub: uid };
}
