import { useState } from "react";
import { t } from "../../i18n";
import { SafeText } from "../../lib/SafeTextView";
import type { FieldKind, Scalar } from "./cardModel";

function formatDatetime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "medium" }).format(d);
}

export function FieldValue({ kind, value }: { kind: FieldKind; value: Scalar }) {
  const [expanded, setExpanded] = useState(false);
  if (value === null || value === "") {
    return <span className="italic text-slate-600">{t("approval.empty")}</span>;
  }
  switch (kind) {
    case "longtext":
      return (
        <div>
          <div
            className={expanded ? "whitespace-pre-wrap break-words" : "max-h-24 overflow-auto whitespace-pre-wrap break-words"}
            tabIndex={0}
          >
            <SafeText value={value} allowNewlines />
          </div>
          <button type="button" className="text-xs underline" onClick={() => setExpanded((v) => !v)}>
            {expanded ? t("approval.showLess") : t("approval.showAll")}
          </button>
        </div>
      );
    case "ticket_ref":
      return (
        <code className="font-mono">
          <SafeText value={value} />
        </code>
      );
    case "datetime":
      return (
        <span>
          <SafeText value={formatDatetime(value)} /> <span className="font-mono text-xs text-slate-600">({value})</span>
        </span>
      );
    case "enum":
      return (
        <span>
          <SafeText value={value} />
        </span>
      );
    default:
      return (
        <span className="break-words">
          <SafeText value={value} />
        </span>
      );
  }
}
