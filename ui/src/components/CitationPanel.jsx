import { groupCitationsByFile } from "../lib/parseCitations.js";

// Renders the backend's parsed citation block as flat, non-interactive
// lines — one per source file, clause numbers from that file's cited
// chunks listed and deduped. section text, description, policy_version,
// and effective_date stay in the parsed citation data (and the backend's
// "Эх сурвалж:" text block) but are deliberately not shown here.
export default function CitationPanel({ citations }) {
  const groups = groupCitationsByFile(citations);

  return (
    <div className="citation-row" aria-label="Эх сурвалж">
      {groups.map(({ file, clauseNumbers }) => (
        <div key={file} className="citation-line">
          {file}
          {clauseNumbers.length > 0 && ` (Заалт ${clauseNumbers.join(", ")})`}
        </div>
      ))}
    </div>
  );
}
