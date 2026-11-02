import { useEffect, useRef } from "react";
import type { Citation } from "../../api/types";
import { Button } from "../../components/ui/button";
import { t } from "../../i18n";
import { cleanPassage, splitEvidence } from "../../lib/passage";
import { SafeText } from "../../lib/SafeTextView";

/** Vị trí pháp lý: "Điều 38, khoản 2" từ trường có cấu trúc. */
export function locationOf(c: Citation): string {
  const parts: string[] = [];
  if (c.article) parts.push(t("cite.article", { v: c.article }));
  if (c.clause) parts.push(t("cite.clause", { v: c.clause }));
  return parts.join(", ");
}

/** Panel đoạn nguồn: văn bản, Điều, khoản và đoạn chứa câu được trích (tô bằng offset, không dùng HTML). */
export function SourcePanel({
  id,
  n,
  citation,
  onClose,
}: {
  id: string;
  n: number;
  citation: Citation;
  onClose: () => void;
}) {
  const head = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    head.current?.focus();
  }, [n]);

  const raw = citation.passage || citation.snippet || "";
  const cleaned = cleanPassage(raw);
  // Chỉ tô trên `passage` gốc chưa bị sửa: offset của server chỉ đúng với văn bản thô.
  const split =
    citation.passage && !cleaned.altered
      ? splitEvidence(cleaned.text, citation.char_start, citation.evidence_start, citation.evidence_end)
      : null;
  const loc = locationOf(citation);

  return (
    <section
      id={id}
      aria-labelledby={`${id}-h`}
      className="mt-2 rounded border border-slate-400 bg-white p-3 text-sm"
      data-testid="source-panel"
    >
      <div className="flex items-start justify-between gap-2">
        <h5 id={`${id}-h`} ref={head} tabIndex={-1} className="font-semibold">
          {t("cite.source", { n })}
        </h5>
        <Button variant="outline" onClick={onClose}>
          {t("cite.close")}
        </Button>
      </div>
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 text-xs text-slate-700">
        <dt>{t("cite.doc")}</dt>
        <dd>
          <SafeText value={citation.title} />
          {citation.doc_num ? (
            <>
              {" ("}
              <SafeText value={citation.doc_num} />
              {")"}
            </>
          ) : null}
        </dd>
        {citation.chapter ? (
          <>
            <dt>{t("cite.chapter")}</dt>
            <dd>
              <SafeText value={citation.chapter} />
            </dd>
          </>
        ) : null}
        {loc || citation.heading ? (
          <>
            <dt>{t("cite.location")}</dt>
            <dd>
              {loc}
              {loc && citation.heading ? " · " : null}
              {citation.heading ? <SafeText value={citation.heading} /> : null}
            </dd>
          </>
        ) : null}
      </dl>
      {cleaned.text ? (
        <blockquote className="mt-2 whitespace-pre-wrap border-l-4 border-slate-300 pl-2" data-testid="passage">
          {split ? (
            <>
              <SafeText value={split.before} allowNewlines />
              <mark className="bg-yellow-200 px-0.5 text-slate-900" data-testid="evidence">
                <SafeText value={split.hit} allowNewlines />
              </mark>
              <SafeText value={split.after} allowNewlines />
            </>
          ) : (
            <SafeText value={cleaned.text} allowNewlines />
          )}
        </blockquote>
      ) : null}
      {citation.passage_truncated ? <p className="mt-1 text-xs text-slate-600">{t("cite.truncated")}</p> : null}
      {cleaned.text && !split && citation.verdict && citation.verdict !== "unverified" ? (
        <p className="mt-1 text-xs text-slate-600">{t("cite.no_highlight")}</p>
      ) : null}
    </section>
  );
}
