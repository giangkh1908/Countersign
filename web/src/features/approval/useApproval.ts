import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useApi } from "../../api/ApiProvider";
import { ApiError } from "../../api/errors";
import type { InterruptRef } from "../../api/types";
import { clockSkew } from "../../lib/time";
import { buildCard, type Card } from "./cardModel";

export type ApprovalStatus = "loading" | "ready" | "expired" | "unrenderable" | "error";

/** Thẻ chỉ dựng từ verify (dữ liệu của signer); không đọc gì khác từ payload agent. */
export function useApproval(threadId: string, interrupt: InterruptRef) {
  const { approvals } = useApi();
  const q = useQuery({
    queryKey: ["verify", threadId, interrupt.interrupt_id],
    queryFn: () => approvals.verify(threadId, interrupt.interrupt_id),
    retry: false,
    gcTime: 0,
    staleTime: Infinity,
  });

  const card: Card | null = useMemo(() => (q.data ? buildCard(q.data) : null), [q.data]);
  const [skew, setSkew] = useState(0);
  useEffect(() => {
    if (q.data) setSkew(clockSkew(q.data.server_time));
  }, [q.data]);

  const err = q.error instanceof ApiError ? q.error : null;
  let status: ApprovalStatus = "loading";
  if (card) status = "ready";
  else if (err?.code === "intent_expired" || err?.status === 410) status = "expired";
  else if (err?.code === "intent_unrenderable" || err?.code === "intent_mismatch") status = "unrenderable";
  else if (q.isError) status = "error";

  return { card, skew, status, error: err, refetch: q.refetch };
}
