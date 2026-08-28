// POST /api/feedback (app/server.py). Never sends `model` — the backend
// stamps its own current settings.llm_model rather than trusting the client
// to know which one actually answered (see app.feedback.build_record).
export async function submitFeedback({
  messageId,
  conversationId,
  verdict,
  question,
  answer,
  retrievedChunkIds = [],
  latencyMs = null,
  reason = null,
  reasonText = null,
}) {
  const response = await fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messageId,
      conversationId,
      verdict,
      question,
      answer,
      retrievedChunkIds,
      latencyMs,
      reason,
      reasonText,
      ts: new Date().toISOString(),
    }),
  });

  if (!response.ok) {
    throw new Error(`Feedback submit failed: ${response.status}`);
  }
}
