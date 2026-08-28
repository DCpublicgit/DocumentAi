import AssistantMarkdown from "./AssistantMarkdown.jsx";
import CitationPanel from "./CitationPanel.jsx";
import FeedbackButtons from "./FeedbackButtons.jsx";
import StageIndicator from "./StageIndicator.jsx";
import AssistantIcon from "./icons/AssistantIcon.jsx";
import RefusalIcon from "./icons/RefusalIcon.jsx";
import ErrorIcon from "./icons/ErrorIcon.jsx";

function Avatar({ children, spinning }) {
  return (
    <div className={`avatar${spinning ? " avatar--spin" : ""}`} aria-hidden="true">
      {children}
    </div>
  );
}

// Who's speaking is currently conveyed only by bubble color/alignment and
// the avatar icon (aria-hidden, decorative) — none of that reaches a screen
// reader. This makes the role explicit without changing what's visible.
function SrLabel({ children }) {
  return <span className="sr-only">{children}</span>;
}

export default function Message({
  message,
  onOpenCitation,
  question,
  conversationId,
  onRetry,
  retryDisabled,
}) {
  const { id, role, text, streaming, kind, citations, stopped, latencyMs, stage, stageDocumentCount } =
    message;

  // AssistantMarkdown's inline "[N]" markers only know the index (that's
  // all a "[N]" in the text carries) — resolve it to this message's own
  // citation object before handing it up, so CitationDrawer always receives
  // the same shape regardless of which entry point opened it.
  const handleMarkerClick = (index) => {
    const citation = citations?.find((c) => c.index === index);
    if (citation) onOpenCitation?.(citation);
  };

  if (role === "user") {
    return (
      <div className="message message--user">
        <div className="bubble bubble--user">
          <SrLabel>Таны асуулт: </SrLabel>
          {text}
        </div>
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
            <p>
              <SrLabel>Туслахын хариулт: </SrLabel>
              {text}
            </p>
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
            <p>
              <SrLabel>Туслахын хариулт: </SrLabel>
              {text}
            </p>
            {/* Only a failed send carries a retryPayload (the question +
                history needed to resend) — a message that errored for some
                other reason has none, and shows no button. */}
            {message.retryPayload && (
              <button
                type="button"
                className="error-panel__retry"
                onClick={() => onRetry?.(id)}
                disabled={retryDisabled}
              >
                Дахин оролдох
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  const isWaitingForFirstToken = streaming && !text;

  return (
    <div className="message message--assistant">
      <div className="assistant-row">
        {/* Spins the whole time this turn is in flight — from the moment
            the question is sent through retrieval and generation — the
            same "still working" signal a typical chat assistant's icon gives, not just
            during the StageIndicator phase before the first token. */}
        <Avatar spinning={streaming}>
          <AssistantIcon />
        </Avatar>
        <div className="assistant-content">
          <SrLabel>Туслахын хариулт: </SrLabel>
          {isWaitingForFirstToken ? (
            <StageIndicator stage={stage} documentCount={stageDocumentCount} />
          ) : (
            <>
              <div className="assistant-text">
                <AssistantMarkdown text={text} onOpenCitation={handleMarkerClick} />
                {streaming && <span className="cursor" aria-hidden="true" />}
              </div>
              {stopped && <p className="assistant-stopped-note">Хариултыг зогсоосон</p>}
              {!streaming && citations.length > 0 && (
                <CitationPanel citations={citations} onOpenCitation={onOpenCitation} />
              )}
              {!streaming && !stopped && (
                <FeedbackButtons
                  messageId={id}
                  conversationId={conversationId}
                  question={question}
                  answer={text}
                  retrievedChunkIds={citations.map((c) => c.chunkId)}
                  latencyMs={latencyMs ?? null}
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
