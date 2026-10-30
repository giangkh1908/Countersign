import { useCallback, useEffect, useReducer, useRef } from "react";
import { useApi } from "../../api/ApiProvider";
import type { AgentEvent, Decision, StreamSink } from "../../api/types";
import { initialStream, streamReducer, type StreamAction } from "./streamReducer";

const raf: (cb: () => void) => void =
  typeof requestAnimationFrame === "function"
    ? (cb) => requestAnimationFrame(() => cb())
    : (cb) => void setTimeout(cb, 33);

export interface DoneInfo {
  threadId: string | null;
  status: "completed" | "interrupted" | "rejected";
}

/** Gom `token` theo khung hình để markdown không parse lại từng token (07 §3.5). */
export function useChatStream(threadId: string | null, onDone?: (d: DoneInfo) => void) {
  const { agent, approvals } = useApi();
  const [state, dispatch] = useReducer(streamReducer, initialStream);
  const abortRef = useRef<AbortController | null>(null);
  const threadRef = useRef<string | null>(threadId);
  const bufRef = useRef("");
  const scheduled = useRef(false);
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  });

  const flush = useCallback(() => {
    if (bufRef.current) {
      const text = bufRef.current;
      bufRef.current = "";
      dispatch({ event: "token", data: { text } });
    }
  }, []);

  const emit = useCallback(
    (a: StreamAction) => {
      flush();
      dispatch(a);
    },
    [flush],
  );

  const makeSink = useCallback(
    (): StreamSink => ({
      onEvent(e: AgentEvent) {
        if (e.event === "thread") threadRef.current = e.data.thread_id;
        if (e.event === "token") {
          bufRef.current += e.data.text;
          if (!scheduled.current) {
            scheduled.current = true;
            raf(() => {
              scheduled.current = false;
              flush();
            });
          }
          return;
        }
        emit(e);
        if (e.event === "done") onDoneRef.current?.({ threadId: threadRef.current, status: e.data.status });
      },
      onError(err) {
        emit({ event: "error", data: { code: err.code, message: err.message, retryable: err.retryable } });
      },
      onClose() {
        emit({ event: "closed" });
      },
    }),
    [emit, flush],
  );

  const begin = useCallback(() => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    return ac.signal;
  }, []);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback(
    (text: string) => {
      threadRef.current = threadId;
      dispatch({ event: "start", text, threadId });
      return agent.run(
        { threadId, text, clientMsgId: crypto.randomUUID() },
        makeSink(),
        begin(),
      );
    },
    [agent, threadId, makeSink, begin],
  );

  const resume = useCallback(
    (interruptId: string, decision: Decision) => {
      const tid = threadRef.current ?? threadId;
      if (!tid) return Promise.resolve();
      dispatch({ event: "resume_start" });
      return agent.resume({ threadId: tid, interruptId, decision }, makeSink(), begin());
    },
    [agent, threadId, makeSink, begin],
  );

  const approve = useCallback(
    (interruptId: string, intentSha256: string) => {
      const tid = threadRef.current ?? threadId;
      if (!tid) return Promise.resolve();
      dispatch({ event: "resume_start" });
      return approvals.approve({ threadId: tid, interruptId, intentSha256 }, makeSink(), begin());
    },
    [approvals, threadId, makeSink, begin],
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
    bufRef.current = "";
    dispatch({ event: "reset" });
  }, []);

  const settle = useCallback(() => dispatch({ event: "settle" }), []);

  return { state, send, resume, approve, abort, settle };
}
