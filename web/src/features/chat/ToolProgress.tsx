import { t } from "../../i18n";
import { SafeText } from "../../lib/SafeTextView";
import type { ToolState } from "./streamReducer";

export function ToolProgress({ tools }: { tools: Record<string, ToolState> }) {
  const entries = Object.entries(tools);
  if (entries.length === 0) return null;
  return (
    <ul className="my-1 space-y-0.5 text-sm text-slate-700" aria-label="tools">
      {entries.map(([id, tool]) => (
        <li key={id} data-status={tool.status}>
          <SafeText
            value={t(
              tool.status === "running" ? "chat.tool.running" : tool.status === "ok" ? "chat.tool.ok" : "chat.tool.failed",
              { tool: tool.tool, summary: tool.summary ?? "" },
            )}
          />
        </li>
      ))}
    </ul>
  );
}
