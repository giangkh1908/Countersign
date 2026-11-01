import type { Nodes, Root } from "mdast";
import ReactMarkdown from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { safeText } from "./safeText";

// Allowlist riêng: không img, chỉ https, không HTML thô (không dùng rehype-raw).
const schema = {
  ...defaultSchema,
  tagNames: [
    "p", "br", "strong", "em", "del", "code", "pre", "blockquote", "ul", "ol", "li",
    "h3", "h4", "h5", "h6", "hr", "table", "thead", "tbody", "tr", "th", "td", "a",
  ],
  attributes: { a: ["href"], code: [["className", /^language-[\w-]+$/]] },
  protocols: { href: ["https"] },
  strip: ["script", "style"],
  clobberPrefix: "u-",
};

/** Chuyển node ảnh thành văn bản "[Ảnh bị chặn: alt]" để không phát sinh request (ca exfil). */
function remarkNoImages() {
  const walk = (node: Nodes): void => {
    if (!("children" in node)) return;
    const kids = node.children as Nodes[];
    for (let i = 0; i < kids.length; i++) {
      const k = kids[i]!;
      if (k.type === "image" || k.type === "imageReference") {
        kids[i] = { type: "text", value: `[Ảnh bị chặn: ${k.alt ?? ""}]` };
      } else walk(k);
    }
  };
  return (tree: Root) => walk(tree);
}

function allowed(href: string, hosts: string[]): boolean {
  try {
    const u = new URL(href);
    return u.protocol === "https:" && hosts.includes(u.host);
  } catch {
    return false;
  }
}

export function SafeMarkdown({ text, linkHosts = [] }: { text: string; linkHosts?: string[] }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkNoImages]}
      rehypePlugins={[[rehypeSanitize, schema]]}
      components={{
        h1: "h3",
        h2: "h3",
        a: ({ href = "", children }) =>
          allowed(href, linkHosts) ? (
            <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="underline">
              {children}
            </a>
          ) : (
            <span title={safeText(href)}>
              {children} <span className="text-slate-500">({safeText(href)})</span>
            </span>
          ),
      }}
    >
      {text}
    </ReactMarkdown>
  );
}
