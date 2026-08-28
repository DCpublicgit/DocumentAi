import { useCallback, useRef, useState } from "react";
import MessageList from "./components/MessageList.jsx";
import ChatInput from "./components/ChatInput.jsx";
import CitationDrawer from "./components/CitationDrawer.jsx";
import NewChatIcon from "./components/icons/NewChatIcon.jsx";
import { createId } from "./lib/ids.js";
import { streamChatCompletion } from "./lib/streamChat.js";
import { isRefusal } from "./lib/refusal.js";
import { buildHistoryMessages } from "./lib/messageHistory.js";
import { classifyThrown, errorCopyFor, isAutoRetryable, ChatRequestError, ERROR_KIND } from "./lib/chatErrors.js";

const PRODUCT_NAME = "Бодлогын туслах";

// Inactivity timeout: aborted (and classified as ERROR_KIND.TIMEOUT, not a
// user-initiated stop) if no token/citations event arrives within this long
// of the previous one — covers both "never got a response" and "stream
// stalled partway through."
const RESPONSE_TIMEOUT_MS = 30_000;

// Exactly one automatic retry happens (network/timeout only, see
// isAutoRetryable) — a single fixed pause before it, not an exponential
// schedule, since there's nothing to escalate with only one step.
const AUTO_RETRY_DELAY_MS = 1500;

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export default function App() {
  // A flat, in-memory conversation — nothing here is persisted (no
  // localStorage, no history list). This is embedded as a small chat
  // surface on hamtdaa.app, not a standalone page with saved history to
  // browse back through, so there is exactly one conversation for the
  // lifetime of this component: no sidebar, no switching between chats.
  const [messages, setMessages] = useState([]);
  // Groups this browser tab's feedback/audit records together server-side
  // (app.feedback, app.audit) — not a navigable id, just a session tag.
  // Regenerated on "Шинэ яриа" so a fresh conversation gets its own group.
  const [conversationId, setConversationId] = useState(() => createId());

  const [isStreaming, setIsStreaming] = useState(false);
  // Lifted out of ChatInput so a send that fails before the request ever
  // leaves the browser can hand the question back to the composer instead
  // of losing it silently.
  const [composerValue, setComposerValue] = useState("");
  // Lives outside React state: it's an imperative handle for the in-flight
  // fetch, not something a render should react to.
  const abortControllerRef = useRef(null);
  // The citation drawer is a single global overlay, not per-message state —
  // only one can be open at a time regardless of which message's marker or
  // CitationPanel button opened it.
  const [openCitation, setOpenCitation] = useState(null);
  const closeCitation = useCallback(() => setOpenCitation(null), []);

  const patchMessage = useCallback((messageId, patch) => {
    setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, ...patch } : m)));
  }, []);

  const stopStreaming = useCallback(() => {
    abortControllerRef.current?.abort("user-stop");
  }, []);

  const handleNewChat = useCallback(() => {
    stopStreaming();
    setIsStreaming(false);
    setMessages([]);
    setComposerValue("");
    setConversationId(createId());
  }, [stopStreaming]);

  // Runs one question through the backend and settles the (already-appended)
  // assistant message one way or another — success, user-stopped, or a
  // classified error with enough on the message (`retryPayload`) to resend
  // later. Shared by a fresh send and a manual "Дахин оролдох" retry, since
  // both need identical attempt/timeout/auto-retry handling.
  const runAttempt = useCallback(
    async ({ assistantId, trimmed, history }) => {
      const updateAssistant = (patch) => patchMessage(assistantId, patch);
      // Client-observed wall-clock time — how long the answer actually took
      // to arrive from this employee's seat, for FeedbackButtons' latencyMs.
      // Not persisted across reloads, and reset per attempt so a retry's
      // latency doesn't include the time spent on the failed first try.
      const startedAt = Date.now();
      const MAX_ATTEMPTS = 2; // 1 initial + 1 automatic retry

      for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
        const controller = new AbortController();
        abortControllerRef.current = controller;
        let timeoutId;
        const armTimeout = () => {
          clearTimeout(timeoutId);
          timeoutId = setTimeout(() => controller.abort("timeout"), RESPONSE_TIMEOUT_MS);
        };
        armTimeout();

        // A retry (manual or automatic) restarts the bubble clean — nothing
        // from the failed attempt should linger under the new one, and the
        // stage indicator goes back to the very start of the pipeline.
        if (attempt > 1) {
          updateAssistant({
            text: "",
            citations: [],
            streaming: true,
            stage: "retrieving",
            stageDocumentCount: null,
          });
        }

        let raw = "";
        let citations = [];
        try {
          await streamChatCompletion(
            trimmed,
            (token) => {
              raw += token;
              armTimeout();
              updateAssistant({ text: raw });
            },
            {
              signal: controller.signal,
              history,
              // Arrives once, after the text is fully streamed (app/server.py
              // sends it as its own SSE event, never interleaved with content
              // deltas) — never on a refusal, so `citations` only ever gets
              // set here for a real answer.
              onCitations: (received) => {
                citations = received;
                armTimeout();
              },
              // "retrieving" → "retrieved" (+documentCount) → "generating"
              // (app.answering.StageEvent) — always arrives before any
              // content delta, and stops mattering once one does: Message.jsx
              // only renders StageIndicator while streaming && !text.
              onStage: (received) => {
                armTimeout();
                updateAssistant({
                  stage: received.stage,
                  stageDocumentCount: received.documentCount ?? null,
                });
              },
            },
          );
          clearTimeout(timeoutId);
          abortControllerRef.current = null;

          const latencyMs = Date.now() - startedAt;
          if (isRefusal(raw.trim())) {
            updateAssistant({ kind: "refusal", streaming: false, latencyMs });
          } else {
            updateAssistant({
              kind: "answer",
              text: raw.trim(),
              citations,
              streaming: false,
              latencyMs,
            });
          }
          return;
        } catch (err) {
          clearTimeout(timeoutId);
          abortControllerRef.current = null;

          if (err.name === "AbortError" && controller.signal.reason !== "timeout") {
            // User pressed Stop — never auto-retried, no error copy, no
            // retry button. Citations never arrive for a stopped answer
            // (that event is sent only after the full text finishes).
            updateAssistant({
              kind: "answer",
              text: raw.trim() || "Асуултыг зогсоолоо.",
              citations: [],
              streaming: false,
              stopped: true,
            });
            return;
          }

          const classified =
            err.name === "AbortError"
              ? new ChatRequestError(ERROR_KIND.TIMEOUT, "Timed out waiting for a response")
              : classifyThrown(err);

          const isLastAttempt = attempt === MAX_ATTEMPTS;
          if (!isLastAttempt && isAutoRetryable(classified.kind)) {
            await delay(AUTO_RETRY_DELAY_MS);
            continue;
          }

          // retryPayload carries exactly what's needed to resend later —
          // the question and the history as it stood at send time — so a
          // manual retry reproduces the same turn even if the conversation
          // has since grown (a new message sent while this one sat failed).
          updateAssistant({
            kind: "error",
            text: errorCopyFor(classified),
            streaming: false,
            retryPayload: { question: trimmed, history },
          });
          return;
        }
      }
    },
    [patchMessage],
  );

  const sendMessage = useCallback(
    async (question) => {
      const trimmed = question.trim();
      if (!trimmed || isStreaming) return;

      setComposerValue("");

      // Captured before the new turn's own messages are appended below —
      // this is exactly "everything before the current question," which is
      // what history is.
      const history = buildHistoryMessages(messages);
      const assistantId = createId();
      setMessages((prev) => [
        ...prev,
        { id: createId(), role: "user", text: trimmed, kind: "answer", citations: [] },
        {
          id: assistantId,
          role: "assistant",
          text: "",
          streaming: true,
          kind: "answer",
          citations: [],
          // Set immediately, client-side, rather than waiting for the
          // server's own "retrieving" stage event — that event is only a
          // few ms behind this either way, but there's no reason to leave
          // StageIndicator with nothing to show for that gap.
          stage: "retrieving",
        },
      ]);

      setIsStreaming(true);
      try {
        await runAttempt({ assistantId, trimmed, history });
      } finally {
        setIsStreaming(false);
      }
    },
    [isStreaming, messages, runAttempt],
  );

  const retryMessage = useCallback(
    (assistantId) => {
      if (isStreaming) return;
      const target = messages.find((m) => m.id === assistantId);
      const payload = target?.retryPayload;
      if (!payload) return;

      // Without this, the error bubble (and its stale error text) would
      // just sit there, unchanged, for the entire in-flight retry — nothing
      // else resets it to a loading state until the attempt finishes one
      // way or another. runAttempt's own attempt>1 reset only covers its
      // OWN internal automatic retry loop, not a fresh call from here.
      patchMessage(assistantId, {
        kind: "answer",
        text: "",
        citations: [],
        streaming: true,
        stage: "retrieving",
        stageDocumentCount: null,
      });

      setIsStreaming(true);
      runAttempt({
        assistantId,
        trimmed: payload.question,
        history: payload.history,
      }).finally(() => setIsStreaming(false));
    },
    [isStreaming, messages, patchMessage, runAttempt],
  );

  // A single handler for both entry points into the same citation — an
  // inline "[N]" marker in the answer text, or a CitationPanel button —
  // both end up here with the resolved citation object itself, not just
  // its index.
  const handleOpenCitation = useCallback((citation) => setOpenCitation(citation), []);

  return (
    <div className="shell">
      <div className="app">
        <header className="app-header">
          <h1 className="app-header__title">{PRODUCT_NAME}</h1>
          <button
            type="button"
            className="icon-btn app-header__new-chat"
            onClick={handleNewChat}
            aria-label="Шинэ яриа эхлүүлэх"
          >
            <NewChatIcon />
          </button>
        </header>
        <MessageList
          messages={messages}
          conversationId={conversationId}
          onOpenCitation={handleOpenCitation}
          onRetry={retryMessage}
          isStreaming={isStreaming}
        />
        <ChatInput
          value={composerValue}
          onChange={setComposerValue}
          onSend={sendMessage}
          onStop={stopStreaming}
          disabled={isStreaming}
        />
      </div>

      {openCitation && <CitationDrawer citation={openCitation} onClose={closeCitation} />}
    </div>
  );
}
