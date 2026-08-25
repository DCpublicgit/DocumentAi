import { useState } from "react";
import ThumbUpIcon from "./icons/ThumbUpIcon.jsx";
import ThumbDownIcon from "./icons/ThumbDownIcon.jsx";

// Local-only UI state — there is no feedback-collection endpoint on the
// backend, so this deliberately does not claim to save or submit anything
// (no confirmation toast). Clicking just marks which reaction is selected,
// same session only.
export default function FeedbackButtons() {
  const [selected, setSelected] = useState(null);

  const toggle = (value) => {
    setSelected((current) => (current === value ? null : value));
  };

  return (
    <div className="feedback-buttons" role="group" aria-label="Хариултын үнэлгээ">
      <button
        type="button"
        className="feedback-buttons__btn"
        aria-pressed={selected === "up"}
        aria-label="Ашигтай хариулт"
        onClick={() => toggle("up")}
      >
        <ThumbUpIcon filled={selected === "up"} />
      </button>
      <button
        type="button"
        className="feedback-buttons__btn"
        aria-pressed={selected === "down"}
        aria-label="Ашиггүй хариулт"
        onClick={() => toggle("down")}
      >
        <ThumbDownIcon filled={selected === "down"} />
      </button>
    </div>
  );
}
