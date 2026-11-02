import { useId, useState } from "react";
import type { AnswerStatus, Citation, Sentence, VerifyInfo } from "../../api/types";
import { t } from "../../i18n";
import { SafeMarkdown } from "../../lib/markdown";
import { CitedAnswer } from "./CitedAnswer";
import { splitCites } from "./citedText";
import { Citations, numberOf } from "./Citations";
import { SourcePanel } from "./SourcePanel";

export interface CitationInfo {
  items: Citation[];
  sentences?: Sentence[];
  answerStatus?: AnswerStatus;
  verify?: VerifyInfo;
}

/** Nội dung trợ lý: câu trả lời + trạng thái + danh sách nguồn + panel đoạn nguồn đang mở. */
export function CitedMessage({
  text,
  info,
  linkHosts,
}: {
  text: string;
  info: CitationInfo;
  linkHosts: string[];
}) {
  const panelId = useId();
  const [openN, setOpenN] = useState<number | null>(null);
  const { items } = info;
  const verifyEnabled = info.verify?.enabled === true;
  const refused = info.answerStatus === "refused";
  const byN = new Map(items.map((c, i) => [numberOf(c, i), c]));
  const open = openN !== null ? byN.get(openN) : undefined;
  // Chỉ chuyển sang văn bản thuần khi câu trả lời thật sự có mã [n] hợp lệ; còn lại giữ markdown như thường.
  const hasCiteCodes = splitCites(text, new Set(byN.keys())).some((p) => p.kind === "cite");

  return (
    <>
      {refused && (
        <div role="status" className="mb-1 rounded border border-slate-500 bg-slate-50 p-2 text-sm font-medium">
          {t("cite.refused")}
        </div>
      )}
      {!refused && verifyEnabled && info.answerStatus === "partially_verified" && (
        <div role="status" className="mb-1 rounded border border-amber-600 bg-amber-50 p-2 text-sm">
          {t("cite.partially")}
        </div>
      )}
      {hasCiteCodes ? (
        <CitedAnswer
          text={text}
          sentences={info.sentences}
          validNs={new Set(byN.keys())}
          verifyEnabled={verifyEnabled}
          openN={openN}
          panelId={panelId}
          onOpen={(n) => setOpenN((cur) => (cur === n ? null : n))}
        />
      ) : (
        <SafeMarkdown text={text} linkHosts={linkHosts} />
      )}
      <Citations
        items={items}
        verifyEnabled={verifyEnabled}
        openN={openN}
        panelId={panelId}
        onOpen={(n) => setOpenN((cur) => (cur === n ? null : n))}
      />
      {open && openN !== null && (
        <SourcePanel id={panelId} n={openN} citation={open} onClose={() => setOpenN(null)} />
      )}
    </>
  );
}
