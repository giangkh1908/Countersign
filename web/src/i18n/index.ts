import en from "./en.json";
import vi from "./vi.json";

const dicts: Record<string, Record<string, string>> = { vi, en };
let locale = "vi";

export function setLocale(l: string): void {
  if (l in dicts) locale = l;
}

export function t(key: string): string {
  return dicts[locale]?.[key] ?? dicts.vi?.[key] ?? key;
}
