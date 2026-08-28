import SendIcon from "./icons/SendIcon.jsx";
import StopIcon from "./icons/StopIcon.jsx";

// Controlled by App.jsx (not local state) so a send that fails before the
// request leaves the browser can hand the question back into this field
// instead of it being gone for good — see App.jsx's sendMessage.
export default function ChatInput({ value, onChange, onSend, onStop, disabled }) {
  const handleSubmit = () => {
    if (!value.trim() || disabled) return;
    onSend(value);
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  };

  return (
    <footer className="chat-input">
      <div className="chat-input__row">
        <textarea
          className="chat-input__field"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Асуултаа бичнэ үү..."
          disabled={disabled}
          rows={1}
          aria-label="Асуулт"
        />
        {disabled ? (
          <button
            type="button"
            className="chat-input__send"
            onClick={onStop}
            aria-label="Зогсоох"
          >
            <StopIcon />
          </button>
        ) : (
          <button
            type="button"
            className="chat-input__send"
            onClick={handleSubmit}
            disabled={!value.trim()}
            aria-label="Илгээх"
          >
            <SendIcon />
          </button>
        )}
      </div>
      <p className="chat-input__disclaimer">
        AI нь алдаа гаргах магадлалтай тул чухал мэдээллийг давхар шалгана уу.
      </p>
    </footer>
  );
}
