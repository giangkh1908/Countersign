import type { Sentence, Verdict } from "../../api/types";
import { Badge } from "../../components/ui/badge";
import { t, type MsgKey } from "../../i18n";
import { SafeText } from "../../lib/SafeTextView";
import { flagOf, segmentAnswer } from "./citedText";

export const VERDICT_LABEL: Record<Exclude<Verdict, "supported">, MsgKey> = {
  unverified: "cite.verdict.unverified",
  partial: "cite.verdict.partial",
  unsupported: "cite.verdict.unsupported",
};

/**
 * Câu trả lời có trích dẫn: văn bản thuần (không HTML), mã [n] là nút mở đoạn nguồn,
 * câu chưa được kiểm chứng có nhãn chữ (không chỉ dựa vào màu).
 */
export function CitedAnswer({
  text,
  sentences,
  validNs,
  verifyEnabled,
  openN,
  panelId,
  onOpen,
}: {
  text: string;
  sentences?: Sentence[];
  validNs: ReadonlySet<number>;
  verifyEnabled: boolean;
  openN: number | null;
  panelId: string;
  onOpen: (n: number) => void;
}) {
  const segs = segmentAnswer(text, sentences, validNs);
  return (
    <p className="whitespace-pre-wrap" data-testid="cited-answer">
      {segs.map((seg, i) => {
        const flag = flagOf(verifyEnabled, seg.sentence?.verdict);
        const body = seg.parts.map((p, j) =>
          p.kind === "text" ? (
            <SafeText key={j} value={p.value} allowNewlines />
          ) : (
            <button
              key={j}
              type="button"
              className="mx-0.5 rounded px-0.5 font-medium text-blue-800 underline hover:bg-blue-100 focus-visible:outline focus-visible:outline-2"
              aria-label={t("cite.open", { n: p.n })}
              aria-expanded={openN === p.n}
              aria-controls={panelId}
              onClick={() => onOpen(p.n)}
            >
              [{p.n}]
            </button>
          ),
        );
        if (!flag) return <span key={i}>{body}</span>;
        return (
          <span
            key={i}
            data-verdict={flag}
            className="rounded bg-amber-50 underline decoration-amber-600 decoration-wavy underline-offset-4"
          >
            {body}{" "}
            <Badge tone={flag === "unsupported" ? "danger" : "warn"}>{t(VERDICT_LABEL[flag])}</Badge>
          </span>
        );
      })}
    </p>
  );
}
