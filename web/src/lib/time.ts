// TODO: định dạng thời gian / đếm ngược hết hạn phê duyệt.
export function secondsUntil(iso: string, now: number = Date.now()): number {
  return Math.max(0, Math.round((Date.parse(iso) - now) / 1000));
}
