// Schema runtime (zod) cho response và event SSE của BFF. Đối chiếu packages/bff/src/bff/api/*.py.
import { z } from "zod";

export const ErrorBodySchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string().default(""),
    retryable: z.boolean().default(false),
    request_id: z.string().optional(),
  }),
});

export const MeSchema = z.object({
  sub: z.string(),
  name: z.string().default(""),
  email: z.string().default(""),
  roles: z.array(z.string()).default([]),
  server_time: z.string().optional(),
  link_allowlist: z.array(z.string()).default([]),
});

export const LogoutSchema = z.object({ redirect_url: z.string() });

export const InterruptRefSchema = z.object({
  interrupt_id: z.string(),
  intent_id: z.string(),
  op: z.string(),
  expires_at: z.string(),
});

/** Kết luận kiểm chứng; giá trị lạ từ server coi là chưa kiểm chứng (không bao giờ coi là đã hỗ trợ). */
export const VerdictSchema = z.enum(["supported", "partial", "unsupported", "unverified"]).catch("unverified");

/** Một mục trích dẫn (rag-citations.md 5.4). Mọi trường mới đều tuỳ chọn để đọc được dữ liệu cũ. */
export const CitationSchema = z.object({
  n: z.number().int().positive().optional(),
  doc_id: z.string().optional(),
  doc_num: z.string().nullish(),
  title: z.string().default(""),
  article: z.string().nullish(),
  clause: z.string().nullish(),
  chapter: z.string().nullish(),
  heading: z.string().nullish(),
  char_start: z.number().int().nullish(),
  char_end: z.number().int().nullish(),
  snippet: z.string().nullish(),
  passage: z.string().nullish(),
  passage_truncated: z.boolean().nullish(),
  evidence_start: z.number().int().nullish(),
  evidence_end: z.number().int().nullish(),
  verdict: VerdictSchema.optional(),
  sentence_ids: z.array(z.number().int()).optional(),
  score: z.number().nullish(),
});

/** Câu trong văn bản trả lời cuối; start/end là offset theo điểm mã Unicode. verdict null = câu không phải khẳng định. */
export const SentenceSchema = z.object({
  id: z.number().int(),
  start: z.number().int().nonnegative(),
  end: z.number().int().nonnegative(),
  cites: z.array(z.number().int()).default([]),
  verdict: VerdictSchema.nullish(),
});

export const AnswerStatusSchema = z.enum(["answered", "partially_verified", "refused"]);

export const VerifyInfoSchema = z.object({
  enabled: z.boolean(),
  pairs: z.number().optional(),
  judge_calls: z.number().optional(),
  ms: z.number().optional(),
});

/** Dữ liệu của sự kiện `citations`. */
export const CitationsDataSchema = z.object({
  items: z.array(CitationSchema),
  sentences: z.array(SentenceSchema).optional(),
  answer_status: AnswerStatusSchema.optional(),
  verify: VerifyInfoSchema.optional(),
});

export const AgentEventSchema = z.discriminatedUnion("event", [
  z.object({
    event: z.literal("thread"),
    data: z.object({ thread_id: z.string(), title: z.string().optional() }),
  }),
  z.object({
    event: z.literal("run_start"),
    data: z.object({
      run_id: z.string().optional(),
      thread_id: z.string().optional(),
      request_ids: z.array(z.string()).optional(),
    }),
  }),
  z.object({
    event: z.literal("route"),
    data: z.object({
      route: z.string(),
      confidence: z.number().optional(),
      reason: z.string().optional(),
    }),
  }),
  z.object({
    event: z.literal("token"),
    data: z.object({ text: z.string(), node: z.string().optional() }),
  }),
  z.object({
    event: z.literal("tool_start"),
    data: z.object({
      call_id: z.string(),
      agent: z.string().optional(),
      tool: z.string(),
      args_preview: z.string().optional(),
    }),
  }),
  z.object({
    event: z.literal("tool_end"),
    data: z.object({
      call_id: z.string(),
      ok: z.boolean(),
      duration_ms: z.number().optional(),
      summary: z.string().optional(),
    }),
  }),
  z.object({ event: z.literal("interrupt"), data: InterruptRefSchema }),
  z.object({ event: z.literal("approval"), data: z.object({ expires_at: z.string() }) }),
  z.object({
    event: z.literal("citations"),
    data: CitationsDataSchema,
  }),
  z.object({
    event: z.literal("cost"),
    data: z.object({
      turn_usd: z.number(),
      thread_usd: z.number(),
      calls: z.array(z.record(z.string(), z.unknown())).optional(),
    }),
  }),
  z.object({
    event: z.literal("done"),
    data: z.object({
      status: z.enum(["completed", "interrupted", "rejected"]).default("completed"),
      message_id: z.string().optional(),
    }),
  }),
  z.object({
    event: z.literal("error"),
    data: z.object({
      code: z.string(),
      message: z.string().default(""),
      retryable: z.boolean().default(false),
    }),
  }),
]);

/** display_fields giữ dạng thô (unknown) để cardModel.classify phân loại từng phần tử. */
export const CardSchema = z.object({
  interrupt_id: z.string(),
  intent_id: z.string(),
  op: z.string(),
  title: z.string(),
  risk: z.string(),
  risk_flags: z.array(z.string()).default([]),
  expires_at: z.string(),
  server_time: z.string(),
  intent_sha256: z.string(),
  display_fields: z.array(z.unknown()),
});

export const ThreadSummarySchema = z.object({
  thread_id: z.string(),
  title: z.string().nullish(),
  last_active_at: z.string().nullish(),
  total_cost_usd: z.number().nullish(),
});

export const ThreadPageSchema = z.object({
  items: z.array(ThreadSummarySchema),
  next_before: z.string().nullable().default(null),
});

export const MessageSchema = z.object({
  role: z.string(),
  content: z.string().default(""),
  citations: z.array(CitationSchema).optional(),
  sentences: z.array(SentenceSchema).optional(),
  answer_status: AnswerStatusSchema.optional(),
  verify: VerifyInfoSchema.optional(),
  cost_usd: z.number().nullish(),
});

export const ThreadMessagesSchema = z.object({
  messages: z.array(MessageSchema),
  pending_interrupt: InterruptRefSchema.nullable().default(null),
  cost: z.object({ thread_usd: z.number().optional() }).passthrough().default({}),
});

export const RequestCostSchema = z.object({
  request_id: z.string().optional(),
  cost_usd: z.number().nullish(),
  alias: z.string().nullish(),
  tokens_in: z.number().nullish(),
  tokens_out: z.number().nullish(),
  cache: z.unknown().optional(),
});

export const VoidSchema = z.undefined();
