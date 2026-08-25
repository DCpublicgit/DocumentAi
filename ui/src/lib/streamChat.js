// Talks only to our own backend's OpenAI-compatible endpoint — never the
// raw Anthropic/Ollama API — per docs/ARCHITECTURE.md: the UI is a dumb
// frontend, retrieval/grounding live entirely server-side.
//
// onToken fires per SSE content delta as it arrives; the returned promise
// resolves once the stream completes ([DONE] or the body closes).
export async function streamChatCompletion(question, onToken, { signal } = {}) {
  const response = await fetch("/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify({
      model: "policy-chatbot",
      stream: true,
      messages: [{ role: "user", content: question }],
    }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`Backend returned ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) return;

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const event of events) {
      const line = event.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice("data:".length).trim();
      if (payload === "[DONE]") return;

      const chunk = JSON.parse(payload);
      if (chunk.error) {
        // Backend hit an unrecoverable error mid-stream (e.g. the LLM
        // provider call failed) and cleanly ended the stream rather than
        // aborting the connection. Surface it the same way a network
        // failure is surfaced, via the caller's catch block.
        throw new Error(chunk.error.message || "Stream error");
      }
      const delta = chunk.choices?.[0]?.delta?.content;
      if (delta) onToken(delta);
    }
  }
}
