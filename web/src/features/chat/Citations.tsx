import type { Citation } from "../../api/types";
import { t } from "../../i18n";
import { SafeText } from "../../lib/SafeTextView";

export function Citations({ items }: { items: Citation[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-label={t("chat.citations")} className="mt-2 text-sm">
      <h4 className="font-medium">{t("chat.citations")}</h4>
      <ol className="list-decimal pl-5">
        {items.map((c, i) => (
          <li key={`${c.doc_id ?? i}-${i}`}>
            <SafeText value={c.title} />
            {c.heading ? (
              <>
                {" › "}
                <SafeText value={c.heading} />
              </>
            ) : null}
            {c.snippet ? (
              <details>
                <summary className="cursor-pointer text-xs">snippet</summary>
                <p className="text-xs text-slate-700">
                  <SafeText value={c.snippet.slice(0, 300)} allowNewlines />
                </p>
              </details>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
