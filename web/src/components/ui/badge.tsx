import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

type Tone = "neutral" | "warn" | "danger" | "info";
const tones: Record<Tone, string> = {
  neutral: "bg-slate-200 text-slate-900",
  warn: "bg-amber-200 text-amber-950",
  danger: "bg-red-100 text-red-900 border border-red-700",
  info: "bg-blue-100 text-blue-900",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium", tones[tone])}>
      {children}
    </span>
  );
}
