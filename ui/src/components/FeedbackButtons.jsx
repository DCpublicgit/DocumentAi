import { useState } from "react";
import { submitFeedback } from "../lib/feedback.js";
import ThumbUpIcon from "./icons/ThumbUpIcon.jsx";
import ThumbDownIcon from "./icons/ThumbDownIcon.jsx";

// Mirrors app.feedback.KNOWN_REASONS (app/feedback.py) exactly — the backend
// rejects any other value with a 422, so these two lists must stay in sync.
const REASONS = ["буруу мэдээлэл", "олдсонгүй", "ойлгомжгүй", "бусад"];

// 👍 sends immediately. 👎 ALSO sends immediately (the vote itself is never
// gated behind the follow-up) and opens a small optional "Юу нь буруу
// байсан бэ?" panel; picking a reason and/or typing a note and hitting
// "Илгээх" sends a SECOND feedback row with that detail attached — see
// CREATE_FEEDBACK_SCHEMA_SQL in app/db.py for why that's two rows, not an
// edit of one. Retracting a vote (clicking it again) only resets the local
// button state; the row already sent stays, same append-only reasoning.
export default function FeedbackButtons({
  messageId,
  conversationId,
  question,
  answer,
  retrievedChunkIds,
  latencyMs,
}) {
  const [selected, setSelected] = useState(null);
  const [showFollowUp, setShowFollowUp] = useState(false);
  const [reason, setReason] = useState(null);
  const [reasonText, setReasonText] = useState("");
  const [followUpSubmitted, setFollowUpSubmitted] = useState(false);

  const send = (verdict, extra = {}) => {
    submitFeedback({
      messageId,
      conversationId,
      verdict,
      question,
      answer,
      retrievedChunkIds,
      latencyMs,
      ...extra,
    }).catch(() => {
      // Best-effort: a failed POST must not disrupt reading the answer. The
      // button's own toggled state is already the visible confirmation —
      // there's no good place to surface a network error for something
      // this low-stakes.
    });
  };

  const handleUp = () => {
    const next = selected === "up" ? null : "up";
    setSelected(next);
    setShowFollowUp(false);
    if (next === "up") send("up");
  };

  const handleDown = () => {
    const next = selected === "down" ? null : "down";
    setSelected(next);
    if (next === "down") {
      send("down");
      setShowFollowUp(true);
      setReason(null);
      setReasonText("");
      setFollowUpSubmitted(false);
    } else {
      setShowFollowUp(false);
    }
  };

  const handleSubmitFollowUp = () => {
    send("down", { reason, reasonText: reasonText.trim() || null });
    setFollowUpSubmitted(true);
  };

  const canSubmitFollowUp = reason !== null || reasonText.trim().length > 0;

  return (
    <div className="feedback">
      <div className="feedback-buttons" role="group" aria-label="Хариултын үнэлгээ">
        <button
          type="button"
          className="feedback-buttons__btn"
          aria-pressed={selected === "up"}
          aria-label="Ашигтай хариулт"
          onClick={handleUp}
        >
          <ThumbUpIcon filled={selected === "up"} />
        </button>
        <button
          type="button"
          className="feedback-buttons__btn"
          aria-pressed={selected === "down"}
          aria-label="Ашиггүй хариулт"
          onClick={handleDown}
        >
          <ThumbDownIcon filled={selected === "down"} />
        </button>
      </div>

      {showFollowUp && !followUpSubmitted && (
        <div className="feedback-followup">
          <p className="feedback-followup__prompt">Юу нь буруу байсан бэ?</p>
          <div className="feedback-followup__reasons">
            {REASONS.map((r) => (
              <button
                key={r}
                type="button"
                className="feedback-followup__reason"
                aria-pressed={reason === r}
                onClick={() => setReason((current) => (current === r ? null : r))}
              >
                {r}
              </button>
            ))}
          </div>
          <textarea
            className="feedback-followup__text"
            placeholder="Нэмэлт тайлбар (заавал биш)..."
            value={reasonText}
            onChange={(event) => setReasonText(event.target.value)}
            rows={2}
          />
          <div className="feedback-followup__actions">
            <button
              type="button"
              className="feedback-followup__submit"
              disabled={!canSubmitFollowUp}
              onClick={handleSubmitFollowUp}
            >
              Илгээх
            </button>
            <button
              type="button"
              className="feedback-followup__skip"
              onClick={() => setShowFollowUp(false)}
            >
              Алгасах
            </button>
          </div>
        </div>
      )}

      {followUpSubmitted && <p className="feedback-followup__thanks">Санал хүсэлтэд баярлалаа.</p>}
    </div>
  );
}
