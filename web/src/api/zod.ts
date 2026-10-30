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
  features: z.object({ admin: z.boolean().default(false) }).default({ admin: false }),
});

export const LogoutSchema = z.object({ redirect_url: z.string() });

export const InterruptRefSchema = z.object({
  interrupt_id: z.string(),
  intent_id: z.string(),
  op: z.string(),
  expires_at: z.string(),
});

export const CitationSchema = z.object({
  doc_id: z.string().optional(),
  title: z.string().default(""),
  heading: z.string().nullish(),
  snippet: z.string().nullish(),
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
    data: z.object({ items: z.array(CitationSchema) }),
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
