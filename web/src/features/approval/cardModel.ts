import { z, type ZodType } from "zod";
import type { CardModel } from "../../api/types";
import { inspectText } from "../../lib/safeText";

// Tập chuẩn: 05 mục 5.3. Đổi tập phải sửa 05 trước.
export const KNOWN = ["text", "longtext", "enum", "datetime", "ticket_ref"] as const;
export type FieldKind = (typeof KNOWN)[number];
export type Scalar = string | null;

export type Field =
  | {
      ok: true;
      path: string;
      label: string;
      kind: FieldKind;
      before: Scalar;
      after: Scalar;
      changed: boolean;
      sensitive: boolean;
      blocked: boolean;
      hidden: boolean;
    }
  | { ok: false; path: string; reason: "unknown_type" | "bad_value" };

const RawField = z.object({
  path: z.string(),
  label: z.string(),
  kind: z.string(),
  before: z.unknown(),
  after: z.unknown(),
  changed: z.boolean(),
  sensitive: z.boolean(),
});

const scalarFor: Record<FieldKind, ZodType<Scalar>> = {
  text: z.string().nullable(),
  longtext: z.string().nullable(),
  enum: z.string().nullable(),
  datetime: z.string().datetime({ offset: true }).nullable(),
  ticket_ref: z
    .string()
    .regex(/^[A-Z]{2,5}-\d{4,8}$/)
    .nullable(),
};

function pathOf(raw: unknown): string {
  const p = (raw as { path?: unknown } | null)?.path;
  return typeof p === "string" ? p : "?";
}

export function classify(raw: unknown): Field {
  const r = RawField.safeParse(raw);
  if (!r.success) return { ok: false, path: pathOf(raw), reason: "bad_value" };
  const d = r.data;
  const kind = (KNOWN as readonly string[]).includes(d.kind) ? (d.kind as FieldKind) : null;
  if (!kind) return { ok: false, path: d.path, reason: "unknown_type" };
  const b = scalarFor[kind].safeParse(d.before);
  const a = scalarFor[kind].safeParse(d.after);
  if (!b.success || !a.success) return { ok: false, path: d.path, reason: "bad_value" };
  const nl = kind === "longtext";
  const texts = [d.label, b.data ?? "", a.data ?? ""];
  const ins = texts.map((s) => inspectText(s, nl));
  return {
    ok: true,
    path: d.path,
    label: d.label,
    kind,
    before: b.data,
    after: a.data,
    changed: d.changed,
    sensitive: d.sensitive,
    blocked: ins.some((i) => i.blocked),
    hidden: ins.some((i) => i.hidden),
  };
}

export interface Card {
  raw: CardModel;
  fields: Field[];
  titleBlocked: boolean;
  titleHidden: boolean;
  hasBlockedChars: boolean;
  hasHiddenChars: boolean;
  unrenderablePaths: string[];
}

export function buildCard(raw: CardModel): Card {
  const fields = raw.display_fields.map(classify);
  // sensitive lên đầu, giữ thứ tự ổn định.
  const sorted = [...fields].sort((x, y) => Number(y.ok && y.sensitive) - Number(x.ok && x.sensitive));
  const t = inspectText(raw.title);
  const blocked = t.blocked || sorted.some((f) => f.ok && f.blocked);
  return {
    raw,
    fields: sorted,
    titleBlocked: t.blocked,
    titleHidden: t.hidden,
    hasBlockedChars: blocked,
    hasHiddenChars: t.hidden || sorted.some((f) => f.ok && f.hidden),
    unrenderablePaths: sorted.filter((f) => !f.ok).map((f) => f.path),
  };
}

export type BlockReason = "expired" | "unrenderable" | "blocked_chars" | "empty" | "busy" | "unverified";

/** Lý do khoá nút Duyệt (null = được duyệt). Là đường duy nhất quyết định việc khoá. */
export function approveBlockReason(
  c: Card | null,
  o: { remainingMs: number; busy: boolean; serverUnrenderable: boolean },
): BlockReason | null {
  if (!c) return "unverified";
  if (o.serverUnrenderable) return "unrenderable";
  if (c.fields.length === 0) return "empty";
  if (c.fields.some((f) => !f.ok)) return "unrenderable";
  if (c.hasBlockedChars) return "blocked_chars";
  if (o.remainingMs <= 0) return "expired";
  if (o.busy) return "busy";
  return null;
}

export const canApprove = (...args: Parameters<typeof approveBlockReason>): boolean =>
  approveBlockReason(...args) === null;
