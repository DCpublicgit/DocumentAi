import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import remarkCitationMarkers from "../lib/remarkCitationMarkers.js";

// react-markdown never interprets embedded HTML as real markup unless
// rehype-raw is added — it isn't, here, so raw HTML is stripped by
// construction, not by a sanitizer pass. This allowlist is the second,
// independent layer: even a markdown CONSTRUCT outside this set (an image,
// a "#" heading, an hr, a footnote) renders as nothing more than its own
// text content, never as the element it would normally become.
// thead/tbody/tr/th/td and pre ride along with table/code, not named in
// the spec but required for either to render as anything but broken —
// a table isn't a table without rows, and a fenced code block is
// indistinguishable from inline code without its <pre> wrapper.
// "citation-marker" isn't real Markdown at all — it's the custom node
// remarkCitationMarkers.js turns a "[N]" text match into.
const ALLOWED_ELEMENTS = [
  "p",
  "strong",
  "em",
  "ul",
  "ol",
  "li",
  "table",
  "thead",
  "tbody",
  "tr",
  "th",
  "td",
  "code",
  "pre",
  "blockquote",
  "a",
  "citation-marker",
];

const REMARK_PLUGINS = [remarkGfm, remarkBreaks, remarkCitationMarkers];

// Renders one assistant message's text as sanitized Markdown. Streaming-safe
// by construction, not by any special-casing here: this is a pure function
// of `text`, so React re-renders — and remark re-parses from scratch — on
// every token. That's also why a partial "**Товч" with no closing "**"
// never throws: remark treats the stray asterisks as literal text until the
// closing marker arrives, the same way it would in a finished document.
//
// `onOpenCitation(index)`, when given, is called when the reader clicks an
// inline "[N]" marker (SYSTEM_PROMPT rule 8) — Message.jsx wires this to
// the same handler CitationPanel's buttons use, so both entry points open
// the same drawer for the same citation.
export default function AssistantMarkdown({ text, onOpenCitation }) {
  const components = useMemo(
    () => ({
      // Tables can run wider than the message column (many columns, long
      // cell text) — scope the scrollbar to the table itself rather than
      // letting it push the whole message, or the page, sideways.
      table: ({ children }) => (
        <div className="assistant-table-scroll">
          <table>{children}</table>
        </div>
      ),
      // Every link opens in a new tab so following one never navigates the
      // employee away from their conversation. react-markdown's own URL
      // transform already neutralizes dangerous schemes (javascript:, etc.)
      // before this ever renders.
      a: ({ children, href }) => (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      ),
      "citation-marker": ({ index }) => (
        <button
          type="button"
          className="citation-marker"
          onClick={() => onOpenCitation?.(index)}
          aria-label={`${index}-р эх сурвалжийг харах`}
        >
          [{index}]
        </button>
      ),
    }),
    [onOpenCitation],
  );

  return (
    <ReactMarkdown
      remarkPlugins={REMARK_PLUGINS}
      allowedElements={ALLOWED_ELEMENTS}
      unwrapDisallowed
      components={components}
    >
      {text}
    </ReactMarkdown>
  );
}
