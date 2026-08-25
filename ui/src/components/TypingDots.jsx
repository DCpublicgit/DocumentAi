// Shown only in the gap between "sent" and the first SSE token arriving —
// once real text starts streaming in, this is replaced by the growing
// answer text + blinking cursor.
export default function TypingDots() {
  return (
    <div className="typing-dots" role="status" aria-label="Бичиж байна">
      <span className="typing-dots__dot" />
      <span className="typing-dots__dot" />
      <span className="typing-dots__dot" />
    </div>
  );
}
