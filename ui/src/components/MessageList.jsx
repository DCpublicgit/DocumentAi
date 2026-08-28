import { useEffect, useRef, useState } from "react";
import Message from "./Message.jsx";

// How close to the bottom (in px of remaining scroll distance) still counts
// as "reading the latest" — inside this band, new content follows the
// reader down; outside it, they've deliberately scrolled up to read back
// through the conversation and nothing should yank their view away.
const NEAR_BOTTOM_PX = 120;

function isNearBottom(el) {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export default function MessageList({ messages, conversationId, onOpenCitation, onRetry, isStreaming }) {
  const containerRef = useRef(null);
  const endRef = useRef(null);
  // Updated by the scroll listener below, read (never subscribed to) by the
  // auto-scroll effect — a ref, not state, so scrolling itself doesn't
  // trigger a re-render on every pixel.
  const isNearBottomRef = useRef(true);
  const prevConversationIdRef = useRef(conversationId);
  const prevCountRef = useRef(messages.length);
  const [showJumpPill, setShowJumpPill] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    isNearBottomRef.current = isNearBottom(el);

    const handleScroll = () => {
      isNearBottomRef.current = isNearBottom(el);
      if (isNearBottomRef.current) setShowJumpPill(false);
    };
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
    // Re-attached per conversation: a fresh container's initial scroll
    // position (jumping into a past conversation, already scrolled to its
    // bottom) needs its own read, not whatever the previous chat left in
    // the ref.
  }, [conversationId]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || messages.length === 0) return;

    const switchedConversation = conversationId !== prevConversationIdRef.current;
    const isNewMessage = messages.length !== prevCountRef.current;
    prevConversationIdRef.current = conversationId;
    prevCountRef.current = messages.length;

    if (switchedConversation) {
      // Opening a different chat always lands at its bottom, instantly —
      // this is a navigation, not a moment to animate through, and there is
      // no "reader mid-scroll" to protect since the view was just mounted.
      endRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
      setShowJumpPill(false);
      return;
    }

    if (!isNearBottomRef.current) {
      // Something arrived below the fold while the reader was scrolled up
      // — surface the pill instead of moving their view out from under them.
      setShowJumpPill(true);
      return;
    }

    // Streamed tokens patch the same message dozens of times a second;
    // smooth-scrolling on each would queue up animations and lag behind.
    // A genuinely new turn (send, or the assistant's reply landing) gets
    // the smooth motion instead — capped by prefers-reduced-motion either
    // way.
    const behavior = isNewMessage && !prefersReducedMotion() ? "smooth" : "auto";
    endRef.current?.scrollIntoView({ behavior, block: "end" });
  }, [messages, conversationId]);

  const jumpToBottom = () => {
    endRef.current?.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "end",
    });
    setShowJumpPill(false);
  };

  if (messages.length === 0) {
    return (
      <div className="message-list-viewport">
        <main className="message-list message-list--empty">
          <div className="empty-state">
            <p>Компанийн бодлогын талаар асуултаа Монгол хэлээр бичнэ үү.</p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="message-list-viewport">
      {/* role="log" + aria-live="polite": every child that shows up here —
          a new user/assistant bubble, the typing indicator, a growing
          streamed answer, an error bubble — gets announced to screen
          readers as it's added, without re-announcing the whole transcript
          each time. aria-relevant="additions text" covers both a brand new
          bubble AND the streamed text growing inside an existing one. */}
      <main
        className="message-list"
        ref={containerRef}
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
      >
        {messages.map((message, index) => (
          <Message
            key={message.id}
            message={message}
            onOpenCitation={onOpenCitation}
            conversationId={conversationId}
            onRetry={onRetry}
            retryDisabled={isStreaming}
            // FeedbackButtons needs the question this answer is FOR — the
            // nearest preceding user turn, not necessarily messages[index-1]
            // (a "stopped"/error turn could sit between them in principle).
            question={
              message.role === "assistant"
                ? messages.slice(0, index).findLast((m) => m.role === "user")?.text
                : undefined
            }
          />
        ))}
        <div ref={endRef} />
      </main>
      {showJumpPill && (
        <button
          type="button"
          className="jump-to-bottom"
          onClick={jumpToBottom}
          aria-label="Шинэ хариултыг харах"
        >
          ↓ шинэ хариулт
        </button>
      )}
    </div>
  );
}
