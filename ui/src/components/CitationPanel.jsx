// Each citation the backend returned (app.citations.citation_fields —
// {index, docId, title, clause, snippet, charStart, charEnd}) rendered as
// its own clickable button, opening the same drawer an inline "[N]" marker
// in the answer text does (AssistantMarkdown.jsx) for that same citation —
// two entry points into the same data, not two different things.
export default function CitationPanel({ citations, onOpenCitation }) {
  return (
    <div className="citation-row" aria-label="Эх сурвалж">
      {citations.map((citation) => (
        <button
          key={citation.index}
          type="button"
          className="citation-line"
          onClick={() => onOpenCitation(citation)}
        >
          [{citation.index}] {citation.title}
          {citation.clause && ` (Заалт ${citation.clause})`}
        </button>
      ))}
    </div>
  );
}
