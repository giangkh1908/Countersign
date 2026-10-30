import { HIDDEN_TOKEN, safeText } from "./safeText";

/** Văn bản thuần đã escape; token ký tự ẩn được tô riêng và có aria-label. */
export function SafeText({ value, allowNewlines = false }: { value: string; allowNewlines?: boolean }) {
  const text = safeText(value, allowNewlines);
  const parts: (string | { token: string })[] = [];
  let last = 0;
  for (const m of text.matchAll(HIDDEN_TOKEN)) {
    const at = m.index ?? 0;
    if (at > last) parts.push(text.slice(last, at));
    parts.push({ token: m[0] });
    last = at + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return (
    <>
      {parts.map((p, i) =>
        typeof p === "string" ? (
          <span key={i}>{p}</span>
        ) : (
          <span
            key={i}
            className="rounded bg-amber-200 px-0.5 font-mono text-xs text-amber-950"
            aria-label={`Ký tự ẩn ${p.token.slice(1, -1)}`}
          >
            {p.token}
          </span>
        ),
      )}
    </>
  );
}
