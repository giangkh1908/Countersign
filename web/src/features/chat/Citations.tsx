import type { Citation } from "../../api/types";
import { Badge } from "../../components/ui/badge";
import { t } from "../../i18n";
import { SafeText } from "../../lib/SafeTextView";
import { VERDICT_LABEL } from "./CitedAnswer";
import { locationOf } from "./SourcePanel";

/** Số hiển thị của mục: server gán `n`, dữ liệu cũ không có thì theo vị trí. */
export function numberOf(c: Citation, index: number): number {
  return c.n ?? index + 1;
}

/** Danh sách nguồn; bấm một mục mở panel đoạn nguồn giống bấm [n] trong câu trả lời. */
export function Citations({
  items,
  verifyEnabled,
  openN,
  panelId,
  onOpen,
}: {
  items: Citation[];
  verifyEnabled: boolean;
  openN: number | null;
  panelId: string;
  onOpen: (n: number) => void;
}) {
  if (items.length === 0) return null;
  return (
    <section aria-label={t("chat.citations")} className="mt-2 text-sm">
      <h4 className="font-medium">{t("chat.citations")}</h4>
      <ol className="space-y-0.5">
        {items.map((c, i) => {
          const n = numberOf(c, i);
          const flag = verifyEnabled && c.verdict && c.verdict !== "supported" ? c.verdict : null;
          const loc = locationOf(c);
          return (
            <li key={`${c.doc_id ?? "x"}-${n}`}>
              <button
                type="button"
                className="text-left underline-offset-2 hover:underline"
                aria-expanded={openN === n}
                aria-controls={panelId}
                onClick={() => onOpen(n)}
              >
                <span className="font-medium">[{n}]</span> <SafeText value={c.title} />
                {loc ? ` › ${loc}` : null}
                {!loc && c.heading ? (
                  <>
                    {" › "}
                    <SafeText value={c.heading} />
                  </>
                ) : null}
              </button>
              {flag ? (
                <>
                  {" "}
                  <Badge tone={flag === "unsupported" ? "danger" : "warn"}>{t(VERDICT_LABEL[flag])}</Badge>
                </>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
