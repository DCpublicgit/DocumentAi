// Shown only in the gap between "sent" and the first real answer token
// arriving — once text starts streaming in, this is replaced by the
// growing answer text + blinking cursor (Message.jsx's isWaitingForFirstToken
// gate). Backs onto app.answering.StageEvent via the SSE "stage" event
// (lib/streamChat.js's onStage) — App.jsx patches the message's `stage` /
// `stageDocumentCount` fields as each one arrives.
//
// No role="status" here (unlike the three-dot indicator this replaced):
// this renders inside MessageList's own role="log" aria-live="polite"
// region (Message.jsx's assistant-content), which already announces text
// changes — a nested live region here would risk a double announcement.
//
// Deliberately plain text, not an icon/spinner + label: a single short
// line at fixed font metrics is what keeps the swap between stages (and
// into the real answer text once streaming starts) free of layout shift —
// see .stage-indicator in index.css, sized to match .assistant-text.
const STAGE_LABELS = {
  retrieving: "Хайж байна…",
  generating: "Хариулт бэлтгэж байна…",
};

export default function StageIndicator({ stage, documentCount }) {
  const label =
    stage === "retrieved"
      ? `${documentCount ?? 0} баримт олдлоо`
      : (STAGE_LABELS[stage] ?? STAGE_LABELS.retrieving);

  return <p className="stage-indicator">{label}</p>;
}
