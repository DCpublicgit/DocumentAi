import { CITATION_HEADER, REFUSAL_STRING } from "./constants.js";

// Matches "[file · section · version (date)]" lines produced by
// app/citations.py's format_citation(). The separator is a real middle dot
// (U+00B7), not a hyphen.
const CITATION_LINE = /^\[(.+?) · (.+?) · (.+?) \((.+?)\)\]$/;

// Splits a completed backend reply into either the refusal state or an
// answer body plus structured citations. Called once per message, after
// streaming finishes — not per token.
// Mirrors app/contract.py's is_refusal(): normalize cosmetics, then compare.
// An exact === here disagrees with the backend, which already suppresses the
// citation block for a drifted refusal — the UI would then render a refusal as
// an ordinary answer with an empty citation panel. Deliberately not a
// substring test: an answer that mentions the refusal wording and then answers
// is a real answer and keeps its citations.
function normalizeRefusal(text) {
  return text
    .split(/\s+/)
    .join(" ")
    .replace(/^["'«»„“”]+|["'«»„“”]+$/g, "")
    .replace(/\.+$/, "")
    .trim()
    .toLowerCase();
}

export function isRefusal(text) {
  return normalizeRefusal(text) === normalizeRefusal(REFUSAL_STRING);
}

export function parseAnswer(fullText) {
  const trimmed = fullText.trim();

  if (isRefusal(trimmed)) {
    return { kind: "refusal" };
  }

  const headerIndex = trimmed.indexOf(CITATION_HEADER);
  if (headerIndex === -1) {
    return { kind: "answer", text: trimmed, citations: [] };
  }

  const answerText = trimmed.slice(0, headerIndex).trim();
  const citationBlock = trimmed.slice(headerIndex + CITATION_HEADER.length).trim();

  const citations = citationBlock
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(CITATION_LINE);
      if (!match) return null;
      const [, file, section, version, effectiveDate] = match;
      return { file, section, version, effectiveDate };
    })
    .filter(Boolean);

  return { kind: "answer", text: answerText, citations };
}

// app/citations.py's format_citation() puts "Заалт {number}: {description}"
// in the section slot when the chunk had an inline clause number, else the
// plain section heading (see Docs/DATA_CONTRACT.md's "Clause-level
// citation"). Only the number is needed for grouping — this pulls it back
// out of that slot.
const CLAUSE_PREFIX = /^Заалт\s+([\d.]+):/;

// Numeric-aware compare so "4.2" sorts before "4.10" (a plain string sort
// would put "4.10" first). Missing trailing segments compare as 0, so
// "4" sorts before "4.1".
function compareClauseNumbers(a, b) {
  const partsA = a.split(".").map(Number);
  const partsB = b.split(".").map(Number);
  const length = Math.max(partsA.length, partsB.length);
  for (let i = 0; i < length; i++) {
    const diff = (partsA[i] ?? 0) - (partsB[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

// Groups the flat per-chunk citation list from parseAnswer() into one entry
// per file_name, with that file's cited clause numbers deduped and
// numerically sorted. A file with no inline clause number on any of its
// citations (chunk fell back to the section-only citation) gets an empty
// clauseNumbers array. Preserves the file order citations first appear in.
export function groupCitationsByFile(citations) {
  const fileOrder = [];
  const clauseNumbersByFile = new Map();

  for (const citation of citations) {
    if (!clauseNumbersByFile.has(citation.file)) {
      clauseNumbersByFile.set(citation.file, new Set());
      fileOrder.push(citation.file);
    }
    const match = citation.section.match(CLAUSE_PREFIX);
    if (match) {
      clauseNumbersByFile.get(citation.file).add(match[1]);
    }
  }

  return fileOrder.map((file) => ({
    file,
    clauseNumbers: [...clauseNumbersByFile.get(file)].sort(compareClauseNumbers),
  }));
}
