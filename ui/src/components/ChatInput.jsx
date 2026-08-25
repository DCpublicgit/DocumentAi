import { useState } from "react";
import SendIcon from "./icons/SendIcon.jsx";
import StopIcon from "./icons/StopIcon.jsx";

export default function ChatInput({ onSend, onStop, disabled }) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    if (!value.trim() || disabled) return;
    onSend(value);
    setValue("");
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
          onChange={(event) => setValue(event.target.value)}
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
