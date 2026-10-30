import { useEffect, useId, useRef, useState } from "react";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import type { Decision, InterruptRef } from "../../api/types";
import { t, type MsgKey } from "../../i18n";
import { SafeText } from "../../lib/SafeTextView";
import { remainingMs } from "../../lib/time";
import { approveBlockReason, type BlockReason } from "./cardModel";
import { Countdown, useNow } from "./Countdown";
import { FieldRow } from "./FieldRow";
import { RejectDialog } from "./RejectDialog";
import { useApproval } from "./useApproval";

const REASON_KEY: Record<BlockReason, MsgKey> = {
  expired: "approval.expired",
  unrenderable: "approval.unrenderable",
  blocked_chars: "approval.blockedChars",
  empty: "approval.unrenderable",
  busy: "approval.processing",
  unverified: "approval.loading",
};

const FLAG_KEY = (f: string): string => `approval.flag.${f}`;

export function ApprovalCard({
  threadId,
  interrupt,
  busy,
  onApprove,
  onDecision,
}: {
  threadId: string;
  interrupt: InterruptRef;
  busy: boolean;
  onApprove: (intentSha256: string) => void;
  onDecision: (d: Decision) => void;
}) {
  const { card, skew, status } = useApproval(threadId, interrupt);
  const now = useNow();
  const [submitting, setSubmitting] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const titleId = useId();
  const reasonId = useId();

  useEffect(() => {
    if (card) titleRef.current?.focus();
  }, [card]);
  useEffect(() => {
    if (!busy) setSubmitting(false);
  }, [busy]);

  const locked = busy || submitting;
  const remaining = card ? remainingMs(card.raw.expires_at, skew, now) : 0;
  const reason = approveBlockReason(card, {
    remainingMs: remaining,
    busy: locked,
    serverUnrenderable: status === "unrenderable",
  });
  const refresh = () => {
    setSubmitting(true);
    onDecision({ type: "refresh" });
  };

  if (status === "loading") {
    return <p role="status">{t("approval.loading")}</p>;
  }

  if (!card) {
    const msg = status === "expired" ? t("approval.error.expired") : status === "unrenderable" ? t("approval.unrenderable") : t("approval.error.generic");
    return (
      <section role="group" aria-labelledby={titleId} className="rounded border border-red-700 bg-red-50 p-3">
        <h3 id={titleId} ref={titleRef} tabIndex={-1} className="font-semibold">
          {t("approval.title")}
        </h3>
        <p role="alert">{msg}</p>
        <div className="mt-2 flex gap-2">
          <Button variant="danger" onClick={() => setRejectOpen(true)} disabled={locked}>
            {t("approval.reject")}
          </Button>
          <Button variant="outline" onClick={refresh} disabled={locked}>
            {t("approval.refresh")}
          </Button>
        </div>
        <RejectDialog
          open={rejectOpen}
          onOpenChange={setRejectOpen}
          onSubmit={(r) => {
            setSubmitting(true);
            onDecision(r ? { type: "reject", reason: r } : { type: "reject" });
          }}
        />
      </section>
    );
  }


  return (
    <section
      role="group"
      aria-labelledby={titleId}
      className="rounded-lg border border-slate-400 bg-white p-3 shadow-sm"
    >
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <h3 id={titleId} ref={titleRef} tabIndex={-1} className="text-base font-semibold">
          <SafeText value={card.raw.title} />
        </h3>
        <Badge tone={card.raw.risk === "high" ? "danger" : "neutral"}>
          {t("approval.risk", { risk: card.raw.risk })}
        </Badge>
        {card.raw.risk_flags.map((f) => (
          <Badge key={f} tone={f === "possible_downgrade" ? "danger" : "warn"}>
            {"⚠ "}
            {tFlag(f)}
          </Badge>
        ))}
        <Countdown remainingMs={remaining} />
      </header>

      {card.raw.risk_flags.includes("possible_downgrade") && (
        <p role="alert" className="mb-2 rounded border border-red-700 bg-red-50 p-2 text-sm">
          {t("approval.flag.possible_downgrade")}
        </p>
      )}
      {card.hasHiddenChars && (
        <p role="alert" className="mb-2 rounded border border-amber-700 bg-amber-50 p-2 text-sm">
          {t("approval.hiddenChars")}
        </p>
      )}
      {(card.unrenderablePaths.length > 0 || card.fields.length === 0 || status === "unrenderable") && (
        <div role="alert" className="mb-2 rounded border border-red-700 bg-red-50 p-2 text-sm">
          <p className="font-semibold">{t("approval.unrenderable")}</p>
          {card.unrenderablePaths.length > 0 && (
            <p>{t("approval.unrenderable.fields", { paths: card.unrenderablePaths.join(", ") })}</p>
          )}
        </div>
      )}

      <div role="list" className="space-y-1">
        {card.fields.map((f) => (
          <FieldRow key={f.path} field={f} />
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          aria-disabled={reason !== null}
          aria-describedby={reason ? reasonId : undefined}
          onClick={() => {
            if (reason !== null) return;
            setSubmitting(true);
            onApprove(card.raw.intent_sha256);
          }}
        >
          {locked ? t("approval.processing") : t("approval.approve")}
        </Button>
        <Button variant="danger" disabled={locked} onClick={() => setRejectOpen(true)}>
          {t("approval.reject")}
        </Button>
        <Button
          variant="outline"
          disabled={locked}
          onClick={refresh}
        >
          {t("approval.refresh")}
        </Button>
        {reason && reason !== "busy" && (
          <span id={reasonId} className="text-sm text-slate-800">
            {t("approval.disabledReason", { reason: t(REASON_KEY[reason]) })}
          </span>
        )}
      </div>

      <RejectDialog
        open={rejectOpen}
        onOpenChange={setRejectOpen}
        onSubmit={(r) => {
          setSubmitting(true);
          onDecision(r ? { type: "reject", reason: r } : { type: "reject" });
        }}
      />
    </section>
  );
}

function tFlag(f: string): string {
  const key = FLAG_KEY(f);
  const known: string[] = ["destructive", "internal_comment", "priority_urgent", "taint_unknown", "possible_downgrade"];
  return known.includes(f) ? t(key as MsgKey) : f;
}
