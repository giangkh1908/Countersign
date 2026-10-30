import { useState } from "react";
import { Badge } from "../../components/ui/badge";
import { t } from "../../i18n";
import { SafeText } from "../../lib/SafeTextView";
import type { Field } from "./cardModel";
import { FieldValue } from "./FieldValue";

export function FieldRow({ field }: { field: Field }) {
  const [revealed, setRevealed] = useState(false);

  if (!field.ok) {
    return (
      <div role="listitem" className="rounded border border-red-700 bg-red-50 p-2 text-sm">
        <code>{field.path}</code>: {field.reason}
      </div>
    );
  }
  const masked = field.sensitive && !revealed;
  return (
    <div
      role="listitem"
      className={
        field.changed
          ? "rounded border-l-4 border-blue-700 bg-blue-50 p-2"
          : "rounded border-l-4 border-transparent p-2"
      }
      data-changed={field.changed}
      data-sensitive={field.sensitive}
    >
      <div className="mb-1 flex flex-wrap items-center gap-2 text-sm font-medium">
        <span>
          <SafeText value={field.label} />
        </span>
        {field.changed && <Badge tone="info">{"Δ "}{t("approval.changed")}</Badge>}
        {field.sensitive && <Badge tone="warn">{"⚠ "}{t("approval.sensitive")}</Badge>}
        {field.sensitive && (
          <button
            type="button"
            className="text-xs underline"
            aria-pressed={revealed}
            onClick={() => setRevealed((v) => !v)}
          >
            {revealed ? t("approval.hide") : t("approval.reveal")}
          </button>
        )}
      </div>
      {masked ? (
        <p className="text-sm italic text-slate-700">{t("approval.masked")}</p>
      ) : (
        <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
          <div>
            <div className="text-xs uppercase text-slate-600">{t("approval.before")}</div>
            <FieldValue kind={field.kind} value={field.before} />
          </div>
          <div>
            <div className="text-xs uppercase text-slate-600">{t("approval.after")}</div>
            <FieldValue kind={field.kind} value={field.after} />
          </div>
        </div>
      )}
    </div>
  );
}
