import { ChatRequestError, ERROR_KIND } from "./chatErrors.js";

// Talks only to our own backend's OpenAI-compatible endpoint — never the
// raw Anthropic/Ollama API — per docs/ARCHITECTURE.md: the UI is a dumb
// frontend, retrieval/grounding live entirely server-side. `history`
// (see lib/messageHistory.js) is everything before this question, oldest
// first — the backend uses it to resolve a followup like "Тэгвэл цалинтай
// юу?" into a standalone query (app.retrieve.query_rewrite) before
// retrieval; this module just forwards it, unaware of what it's for.
//
// onToken fires per SSE content delta as it arrives. onCitations fires once,
// after the text is fully streamed, with the structured citation list
// (app.citations.citation_fields) sent as its own named "citations" SSE
// event — never interleaved with content deltas (app/server.py's
// _stream_chat_completion), and omitted entirely on a refusal. onStage
// fires for each pipeline-progress "stage" event — {stage, documentCount?}
// (app.answering.StageEvent) — always BEFORE any content delta, in the
// order the backend pipeline actually reaches them: "retrieving", then
// "retrieved" (with documentCount) unless a gibberish question skipped
// retrieval entirely, then "generating" unless the question was refused.
// The returned promise resolves once the stream completes ([DONE] or the
// body closes).
//
// A non-2xx or a mid-stream `payload.error` throws a ChatRequestError
// (see lib/chatErrors.js) rather than a bare Error, so App.jsx's runAttempt
// can pick the right retry behavior and Mongolian copy without re-parsing
// a message string. A network-level fetch() rejection (offline, DNS, CORS)
// is NOT classified here — it reaches the caller as whatever fetch threw,
// and chatErrors.classifyThrown sorts that out.
export async function streamChatCompletion(
  question,
  onToken,
  { signal, history = [], onCitations, onStage } = {},
) {
  const response = await fetch("/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify({
      model: "policy-chatbot",
      stream: true,
      messages: [...history, { role: "user", content: question }],
    }),
  });

  if (!response.ok) {
    if (response.status === 429) {
      const retryAfterHeader = response.headers.get("retry-after");
      const parsed = retryAfterHeader ? Number(retryAfterHeader) : NaN;
      throw new ChatRequestError(ERROR_KIND.RATE_LIMIT, `Rate limited (${response.status})`, {
        status: response.status,
        retryAfterSeconds: Number.isFinite(parsed) ? parsed : null,
      });
    }
    if (response.status >= 500) {
      throw new ChatRequestError(ERROR_KIND.SERVER, `Backend returned ${response.status}`, {
        status: response.status,
      });
    }
    throw new ChatRequestError(ERROR_KIND.UNKNOWN, `Backend returned ${response.status}`, {
      status: response.status,
    });
  }
  if (!response.body) {
    throw new ChatRequestError(ERROR_KIND.UNKNOWN, "Backend returned no response body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) return;

    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";

    for (const block of blocks) {
      // A block is one SSE frame, e.g. either:
      //   data: {...}
      // or a NAMED event (app/server.py's _sse_event), two lines:
      //   event: citations
      //   data: {...}
      // Default event name is "message" per the SSE spec when no "event:"
      // line is present — matches every content-delta/finish frame today.
      let eventName = "message";
      let dataLine = null;
      for (const rawLine of block.split("\n")) {
        const line = rawLine.trim();
        if (line.startsWith("event:")) {
          eventName = line.slice("event:".length).trim();
        } else if (line.startsWith("data:")) {
          dataLine = line.slice("data:".length).trim();
        }
      }
      if (dataLine === null) continue;
      if (dataLine === "[DONE]") return;

      const payload = JSON.parse(dataLine);

      if (eventName === "citations") {
        onCitations?.(payload.citations);
        continue;
      }

      if (eventName === "stage") {
        onStage?.(payload);
        continue;
      }

      if (payload.error) {
        // Backend hit an unrecoverable error mid-stream (e.g. the LLM
        // provider call failed) and cleanly ended the stream rather than
        // aborting the connection — treated as a server-side failure since
        // that's what it is, even though it arrived with a 200.
        throw new ChatRequestError(ERROR_KIND.SERVER, payload.error.message || "Stream error");
      }
      const delta = payload.choices?.[0]?.delta?.content;
      if (delta) onToken(delta);
    }
  }
}
