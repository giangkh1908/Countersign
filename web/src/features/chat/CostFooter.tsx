import { t } from "../../i18n";
import { formatUsd } from "../../lib/format";

export function CostFooter({ turnUsd, threadUsd }: { turnUsd: number; threadUsd: number }) {
  return (
    <p className="mt-1 text-xs text-slate-600">
      {t("chat.cost", { turn: formatUsd(turnUsd), thread: formatUsd(threadUsd) })}
    </p>
  );
}
