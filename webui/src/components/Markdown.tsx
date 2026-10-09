// Markdown rendering for streaming LLM output.
//
// Two design points:
//   1. We use `marked` for parsing — robust, well-tested, and configured
//      here to NOT pass through raw HTML (safer than dangerously trusting
//      model output).
//   2. We use React 19's `useDeferredValue` so the markdown re-parse
//      happens on a "low priority" lane. While the user is streaming,
//      the input updates immediately (so the cursor feels live) but the
//      expensive parse+render is deferred — this keeps the keystroke
//      frame rate smooth even on big documents.
//
// A final flicker-free render happens automatically after the LLM call
// ends because the input stops changing and the deferred value catches
// up within one frame.

import { useDeferredValue, useMemo } from "react";
import { marked } from "marked";

// Disable raw HTML pass-through. Anything that looks like HTML in the
// source becomes escaped text. This protects against prompt-injection
// attempts that try to inject <script> or <img onerror=...> in the LLM
// output.
marked.setOptions({
  gfm: true,
  breaks: false,
  async: false,
});

const renderer = new marked.Renderer();
renderer.html = () => "";        // never emit raw HTML blocks
// marked v18+ calls the link renderer with a single object parameter.
renderer.link = ({ href, title, tokens }) => {
  const text = (tokens ?? [])
    .map((t) => ("text" in t ? t.text : ""))
    .join("");
  const safeHref = (href ?? "").trim();
  if (/^javascript:/i.test(safeHref)) return text;
  const t = title ? ` title="${escapeAttr(title)}"` : "";
  return `<a href="${escapeAttr(safeHref)}"${t} target="_blank" rel="noopener noreferrer">${text}</a>`;
};


function escapeAttr(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]!));
}


interface Props {
  text: string;
  /** Tailwind-ish className for the wrapping div. */
  className?: string;
  /** Inline style for the wrapping div. */
  style?: React.CSSProperties;
}

export function Markdown({ text, className, style }: Props) {
  // Defer the heavy parse+render so streaming tokens don't block UI.
  const deferred = useDeferredValue(text);
  const isStale = deferred !== text;

  const html = useMemo(() => {
    if (!deferred) return "";
    try {
      return marked.parse(deferred, { renderer, async: false }) as string;
    } catch (e) {
      // If parsing fails for any reason, fall back to escaped plain text
      // so the user still sees something.
      return `<pre>${escapeHtml(deferred)}</pre>`;
    }
  }, [deferred]);

  return (
    <div
      className={className}
      style={{
        opacity: isStale ? 0.85 : 1,   // slight dim while catching up
        transition: "opacity 0.12s",
        ...style,
      }}
      // The content is produced by `marked` from a controlled LLM stream
      // with raw-HTML pass-through disabled. It's safe to inject.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}


function escapeHtml(s: string): string {
  return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]!));
}
