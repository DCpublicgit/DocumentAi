import { visit } from "unist-util-visit";

// Matches the inline "[N]" markers the model places in its own prose per
// SYSTEM_PROMPT rule 8 (app/answering.py) — N is the citation's ORIGINAL
// 1-based position in the numbered context blocks shown to the model, which
// app.answering._resolve_used_context preserves through narrowing
// specifically so these markers keep resolving correctly.
const MARKER_RE = /\[(\d+)\]/g;

// Splits every text node containing "[N]" into plain text plus a custom
// "citationMarker" node per match, tagged via hName/hProperties so
// react-markdown's mdast-to-hast pipeline turns each into a
// <citation-marker index="N"> element — which AssistantMarkdown.jsx then
// maps to an actual clickable button via its `components` prop. Operating
// at the AST level (not on react-markdown's rendered children) means a
// marker inside emphasis, a list item, a table cell, etc. is caught
// uniformly, not just in top-level paragraphs.
export default function remarkCitationMarkers() {
  return (tree) => {
    visit(tree, "text", (node, index, parent) => {
      if (!parent || index === null || index === undefined) return;

      const matches = [...node.value.matchAll(MARKER_RE)];
      if (matches.length === 0) return;

      const replacement = [];
      let cursor = 0;
      for (const match of matches) {
        const start = match.index;
        if (start > cursor) {
          replacement.push({ type: "text", value: node.value.slice(cursor, start) });
        }
        replacement.push({
          type: "citationMarker",
          data: {
            hName: "citation-marker",
            hProperties: { index: Number(match[1]) },
          },
          children: [],
        });
        cursor = start + match[0].length;
      }
      if (cursor < node.value.length) {
        replacement.push({ type: "text", value: node.value.slice(cursor) });
      }

      parent.children.splice(index, 1, ...replacement);
      return index + replacement.length;
    });
  };
}
