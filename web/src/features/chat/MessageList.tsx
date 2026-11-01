import type { ChatMessage } from "../../api/types";
import { t } from "../../i18n";
import { SafeMarkdown } from "../../lib/markdown";
import { SafeText } from "../../lib/SafeTextView";
import { Citations } from "./Citations";
import { CostFooter } from "./CostFooter";
import { ToolProgress } from "./ToolProgress";
import type { StreamState } from "./streamReducer";

export function MessageList({
  messages,
  live,
  linkHosts,
}: {
  messages: ChatMessage[];
  live: StreamState;
  linkHosts: string[];
}) {
  const busy = live.phase === "streaming";
  const showLive = live.phase !== "idle";
  return (
    <div role="log" aria-live="off" aria-busy={busy} className="space-y-3">
      {messages.length === 0 && !showLive && <p className="text-slate-600">{t("chat.empty")}</p>}
      {messages.map((m, i) =>
        m.role === "user" ? (
          <div key={i} className="rounded bg-slate-100 p-2" data-role="user">
            <div className="text-xs font-semibold">{t("chat.user")}</div>
            <p className="whitespace-pre-wrap">
              <SafeText value={m.content} allowNewlines />
            </p>
          </div>
        ) : (
          <div key={i} className="p-2" data-role="assistant">
            <div className="text-xs font-semibold">{t("chat.assistant")}</div>
            <SafeMarkdown text={m.content} linkHosts={linkHosts} />
            <Citations items={m.citations ?? []} />
          </div>
        ),
      )}
      {showLive && (
        <>
          {live.userText && (
            <div className="rounded bg-slate-100 p-2" data-role="user">
              <div className="text-xs font-semibold">{t("chat.user")}</div>
              <p className="whitespace-pre-wrap">
                <SafeText value={live.userText} allowNewlines />
              </p>
            </div>
          )}
          <div className="p-2" data-role="assistant-live">
            <div className="text-xs font-semibold">{t("chat.assistant")}</div>
            <ToolProgress tools={live.tools} />
            <SafeMarkdown text={live.text} linkHosts={linkHosts} />
            <Citations items={live.citations} />
            {live.cost && <CostFooter turnUsd={live.cost.turnUsd} threadUsd={live.cost.threadUsd} />}
          </div>
        </>
      )}
    </div>
  );
}
