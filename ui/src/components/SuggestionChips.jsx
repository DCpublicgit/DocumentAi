// Starter prompts shown only before the first message — once a real
// conversation is underway they'd just be clutter competing with it.
const SUGGESTIONS = ["Цалингийн бодлого", "Ажлын цагийн хуваарь", "Чөлөөний хүсэлт гаргах"];

export default function SuggestionChips({ onSelect }) {
  return (
    <div className="suggestion-chips">
      {SUGGESTIONS.map((label) => (
        <button
          key={label}
          type="button"
          className="suggestion-chip"
          onClick={() => onSelect(label)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
