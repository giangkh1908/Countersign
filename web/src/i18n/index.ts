import en from "./en.json";
import vi from "./vi.json";

export type MsgKey = keyof typeof vi;

const dicts: Record<string, Record<string, string>> = { vi, en };
let locale = "vi";

export function setLocale(l: string): void {
  if (l in dicts) locale = l;
}

export function t(key: MsgKey, params?: Record<string, string | number>): string {
  const raw = dicts[locale]?.[key] ?? dicts.vi?.[key] ?? key;
  if (!params) return raw;
  return raw.replace(/\{(\w+)\}/g, (_, k: string) => String(params[k] ?? ""));
}

/** Thông điệp theo mã lỗi; không hiện chuỗi thô của server nếu không có bản dịch (07 §3.6). */
export function errorMessage(code: string): string {
  const key = `error.${code}`;
  return key in vi ? t(key as MsgKey) : t("error.unknown");
}
