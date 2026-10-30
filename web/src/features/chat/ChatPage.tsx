import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { useApi } from "../../api/ApiProvider";
import type { Decision, InterruptRef } from "../../api/types";
import { Button } from "../../components/ui/button";
import { errorMessage, t } from "../../i18n";
import { ApprovalCard } from "../approval/ApprovalCard";
import { ThreadList } from "../threads/ThreadList";
import { Composer } from "./Composer";
import { MessageList } from "./MessageList";
import { useChatStream } from "./useChatStream";

export function ChatPage() {
  const { threadId = null } = useParams<{ threadId: string }>();
  const api = useApi();
  const qc = useQueryClient();
  const navigate = useNavigate();

  const me = useQuery({ queryKey: ["me"], queryFn: () => api.auth.me(), staleTime: 60_000, retry: false });
  const history = useQuery({
    queryKey: ["messages", threadId],
    queryFn: () => api.threads.messages(threadId!),
    enabled: threadId !== null,
  });

  const { state, send, resume, approve, abort, settle } = useChatStream(threadId, async ({ threadId: tid }) => {
    await qc.invalidateQueries({ queryKey: ["threads"] });
    if (tid) await qc.invalidateQueries({ queryKey: ["messages", tid] });
    settle();
    if (tid && tid !== threadId) navigate(`/t/${tid}`, { replace: true });
  });

  const pending: InterruptRef | null = state.interrupt ?? history.data?.pending_interrupt ?? null;
  const activeThread = state.threadId ?? threadId;
  const busy = state.phase === "streaming";
  const locked = busy || pending !== null;

  const onDecision = (d: Decision) => {
    if (pending) void resume(pending.interrupt_id, d);
  };

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only">
        {t("app.skip")}
      </a>
      <header className="flex items-center justify-between border-b p-3">
        <h1 className="text-lg font-semibold">{t("app.title")}</h1>
        <div className="flex items-center gap-2 text-sm">
          {me.data && <span>{me.data.name || me.data.email}</span>}
          <Button
            variant="outline"
            onClick={async () => {
              const r = await api.auth.logout();
              window.location.assign(r.redirectUrl);
            }}
          >
            {t("app.logout")}
          </Button>
        </div>
      </header>
      <div className="flex flex-1">
        <nav className="w-64 border-r p-3" aria-label={t("threads.title")}>
          <ThreadList activeId={threadId} onOpen={(id) => navigate(`/t/${id}`)} onNew={() => navigate("/")} onDeleted={(id) => id === threadId && navigate("/")} />
        </nav>
        <main id="main" className="flex-1 space-y-3 p-3">
          <MessageList messages={history.data?.messages ?? []} live={state} linkHosts={me.data?.link_allowlist ?? []} />
          {state.phase === "error" && state.error && (
            <div role="alert" className="rounded border border-red-700 bg-red-50 p-2">
              {errorMessage(state.error.code)}
            </div>
          )}
          {pending && activeThread && (
            <ApprovalCard
              key={pending.interrupt_id}
              threadId={activeThread}
              interrupt={pending}
              busy={busy}
              onApprove={(sha) => void approve(pending.interrupt_id, sha)}
              onDecision={onDecision}
            />
          )}
          <Composer disabled={locked} streaming={busy} onSend={(text) => void send(text)} onStop={abort} />
        </main>
      </div>
    </div>
  );
}
