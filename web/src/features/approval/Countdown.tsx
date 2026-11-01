import { useEffect, useState } from "react";
import { t } from "../../i18n";
import { formatMmSs } from "../../lib/time";

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** Hiện mm:ss; aria-live chỉ báo ở mốc 60s và khi hết hạn (không đọc từng giây). */
export function Countdown({ remainingMs }: { remainingMs: number }) {
  const expired = remainingMs <= 0;
  const warn = !expired && remainingMs <= 60_000;
  const announce = expired ? t("approval.expired") : warn ? t("approval.warn60") : "";
  return (
    <div className={warn || expired ? "font-semibold text-amber-900" : "text-slate-700"}>
      <span data-testid="countdown">
        {expired ? t("approval.expired") : t("approval.expiresIn", { time: formatMmSs(remainingMs) })}
      </span>
      <span className="sr-only" role="status" aria-live="polite">
        {announce}
      </span>
    </div>
  );
}
