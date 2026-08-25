import CitationPanel from "./CitationPanel.jsx";
import FeedbackButtons from "./FeedbackButtons.jsx";
import TypingDots from "./TypingDots.jsx";
import AssistantIcon from "./icons/AssistantIcon.jsx";
import RefusalIcon from "./icons/RefusalIcon.jsx";
import ErrorIcon from "./icons/ErrorIcon.jsx";

function Avatar({ children }) {
  return (
    <div className="avatar" aria-hidden="true">
      {children}
    </div>
  );
}

export default function Message({ message }) {
  const { role, text, streaming, kind, citations, stopped } = message;

  if (role === "user") {
    return (
      <div className="message message--user">
        <div className="bubble bubble--user">{text}</div>
      </div>
    );
  }

  if (kind === "refusal") {
    return (
      <div className="message message--assistant">
        <div className="assistant-row">
          <Avatar>
            <RefusalIcon />
          </Avatar>
          <div className="refusal-panel">
            <p>{text}</p>
          </div>
        </div>
      </div>
    );
  }

  if (kind === "error") {
    return (
      <div className="message message--assistant">
        <div className="assistant-row">
          <Avatar>
            <ErrorIcon />
          </Avatar>
          <div className="error-panel">
            <p>{text}</p>
          </div>
        </div>
      </div>
    );
  }

  const isWaitingForFirstToken = streaming && !text;

  return (
    <div className="message message--assistant">
      <div className="assistant-row">
        <Avatar>
          <AssistantIcon />
        </Avatar>
        <div className="assistant-content">
          {isWaitingForFirstToken ? (
            <TypingDots />
          ) : (
            <>
              <div className="assistant-text">
                {text}
                {streaming && <span className="cursor" aria-hidden="true" />}
              </div>
              {stopped && <p className="assistant-stopped-note">Хариултыг зогсоосон</p>}
              {!streaming && citations.length > 0 && <CitationPanel citations={citations} />}
              {!streaming && !stopped && <FeedbackButtons />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
