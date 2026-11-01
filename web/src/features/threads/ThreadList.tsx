import { useState } from "react";
import { Button } from "../../components/ui/button";
import { t } from "../../i18n";
import { formatDateTime } from "../../lib/format";
import { SafeText } from "../../lib/SafeTextView";
import { DeleteThreadDialog } from "./DeleteThreadDialog";
import { useDeleteThread, useThreads } from "./useThreads";

export function ThreadList({
  activeId,
  onOpen,
  onNew,
  onDeleted,
}: {
  activeId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
  onDeleted: (id: string) => void;
}) {
  const q = useThreads();
  const del = useDeleteThread();
  const [toDelete, setToDelete] = useState<string | null>(null);
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div>
      <Button className="mb-2 w-full" onClick={onNew}>
        {t("app.newChat")}
      </Button>
      {items.length === 0 && !q.isLoading && <p className="text-sm text-slate-600">{t("threads.empty")}</p>}
      <ul className="space-y-1">
        {items.map((th) => (
          <li key={th.thread_id} className="flex items-center gap-1">
            <button
              type="button"
              className="flex-1 truncate rounded p-1 text-left text-sm hover:bg-slate-100 aria-[current=true]:bg-slate-200"
              aria-current={th.thread_id === activeId}
              onClick={() => onOpen(th.thread_id)}
            >
              <SafeText value={th.title || t("threads.untitled")} />
              <span className="block text-xs text-slate-600">{formatDateTime(th.last_active_at)}</span>
            </button>
            <Button variant="ghost" onClick={() => setToDelete(th.thread_id)}>
              {t("threads.delete")}
            </Button>
          </li>
        ))}
      </ul>
      {q.hasNextPage && (
        <Button variant="outline" className="mt-2" onClick={() => void q.fetchNextPage()}>
          {t("threads.more")}
        </Button>
      )}
      <DeleteThreadDialog
        open={toDelete !== null}
        onOpenChange={(o) => !o && setToDelete(null)}
        onConfirm={() => {
          if (toDelete) {
            del.mutate(toDelete);
            onDeleted(toDelete);
          }
        }}
      />
    </div>
  );
}
