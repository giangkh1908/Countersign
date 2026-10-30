/** Lệch giờ máy chủ - máy khách (ms), tính lúc nhận thẻ. Không tin đồng hồ máy (07 §3.6 mục 6). */
export function clockSkew(serverTime: string, clientNow: number = Date.now()): number {
  const t = Date.parse(serverTime);
  return Number.isNaN(t) ? 0 : t - clientNow;
}

/** ms còn lại tới `expiresAt`; hạn không hợp lệ coi như đã hết. */
export function remainingMs(expiresAt: string, skew: number, now: number = Date.now()): number {
  const exp = Date.parse(expiresAt);
  if (Number.isNaN(exp)) return 0;
  return exp - (now + skew);
}

export function formatMmSs(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
