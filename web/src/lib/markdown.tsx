import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";

// Markdown luôn qua rehype-sanitize; không bao giờ render HTML thô.
export function Markdown({ children }: { children: string }) {
  return <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{children}</ReactMarkdown>;
}
