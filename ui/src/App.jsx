import { useCallback, useEffect, useRef, useState } from "react";
import MessageList from "./components/MessageList.jsx";
import ChatInput from "./components/ChatInput.jsx";
import Sidebar from "./components/Sidebar.jsx";
import SuggestionChips from "./components/SuggestionChips.jsx";
import NewChatIcon from "./components/icons/NewChatIcon.jsx";
import SidebarIcon from "./components/icons/SidebarIcon.jsx";
import { useConversations } from "./hooks/useConversations.js";
import { useIsWideViewport } from "./hooks/useIsWideViewport.js";
import { createId } from "./lib/ids.js";
import { streamChatCompletion } from "./lib/streamChat.js";
import { parseAnswer } from "./lib/parseCitations.js";

const PRODUCT_NAME = "Бодлогын туслах";

export default function App() {
  const {
    conversations,
    activeId,
    activeTitle,
    messages,
    appendToActiveConversation,
    patchMessage,
    renameConversation,
    deleteConversation,
    openConversation,
    startNewConversation,
  } = useConversations();

  const [isStreaming, setIsStreaming] = useState(false);
  // Lives outside React state: it's an imperative handle for the in-flight
  // fetch, not something a render should react to.
  const abortControllerRef = useRef(null);
  const isWideViewport = useIsWideViewport();
  // Open by default where it costs nothing, closed where it would cover the
  // conversation.
  const [isSidebarOpen, setIsSidebarOpen] = useState(isWideViewport);

  // Escape closes the panel only while it is an overlay; on desktop it is
  // part of the layout and Escape belongs to whatever else is focused.
  useEffect(() => {
    if (isWideViewport || !isSidebarOpen) return;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") setIsSidebarOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isWideViewport, isSidebarOpen]);

  const dismissOverlaySidebar = useCallback(() => {
    if (!isWideViewport) setIsSidebarOpen(false);
  }, [isWideViewport]);

  const handleNewChat = useCallback(() => {
    startNewConversation();
    dismissOverlaySidebar();
  }, [startNewConversation, dismissOverlaySidebar]);

  const handleOpenConversation = useCallback(
    (conversationId) => {
      openConversation(conversationId);
      dismissOverlaySidebar();
    },
    [openConversation, dismissOverlaySidebar],
  );

  const sendMessage = useCallback(
    async (question) => {
      const trimmed = question.trim();
      if (!trimmed || isStreaming) return;

      const assistantId = createId();
      // The turn is pinned to the conversation it started in. Opening another
      // chat mid-stream must not redirect the tokens still arriving for this
      // one.
      const conversationId = appendToActiveConversation([
        { id: createId(), role: "user", text: trimmed, kind: "answer", citations: [] },
        {
          id: assistantId,
          role: "assistant",
          text: "",
          streaming: true,
          kind: "answer",
          citations: [],
        },
      ]);

      setIsStreaming(true);
      const controller = new AbortController();
      abortControllerRef.current = controller;
      const updateAssistant = (patch) => patchMessage(conversationId, assistantId, patch);

      let raw = "";
      try {
        await streamChatCompletion(
          trimmed,
          (token) => {
            raw += token;
            updateAssistant({ text: raw });
          },
          { signal: controller.signal },
        );

        const parsed = parseAnswer(raw);
        if (parsed.kind === "refusal") {
          updateAssistant({ kind: "refusal", streaming: false });
        } else {
          updateAssistant({
            kind: "answer",
            text: parsed.text,
            citations: parsed.citations,
            streaming: false,
          });
        }
      } catch (err) {
        if (err.name === "AbortError") {
          // The backend never reaches the citation footer until the full
          // answer has streamed (see app/answering.py stream_answer), so a
          // stopped fetch's `raw` is always plain partial answer text — safe
          // to show as-is, never a truncated citation block.
          updateAssistant({
            kind: "answer",
            text: raw.trim() || "Асуултыг зогсоолоо.",
            citations: [],
            streaming: false,
            stopped: true,
          });
        } else {
          updateAssistant({
            kind: "error",
            text: "Холболтын алдаа гарлаа. Дахин оролдоно уу.",
            streaming: false,
          });
        }
      } finally {
        abortControllerRef.current = null;
        setIsStreaming(false);
      }
    },
    [isStreaming, appendToActiveConversation, patchMessage],
  );

  const stopStreaming = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  return (
    <div className="shell">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onNewChat={handleNewChat}
        onOpenConversation={handleOpenConversation}
        onRenameConversation={renameConversation}
        onDeleteConversation={deleteConversation}
      />

      {isSidebarOpen && !isWideViewport && (
        <div className="shell__scrim" onClick={() => setIsSidebarOpen(false)} aria-hidden="true" />
      )}

      <div className="app">
        <header className="app-header">
          {!isSidebarOpen && (
            <button
              type="button"
              className="icon-btn"
              onClick={() => setIsSidebarOpen(true)}
              aria-label="Түүхийн самбарыг нээх"
            >
              <SidebarIcon />
            </button>
          )}
          <h1 className="app-header__title">{activeTitle ?? PRODUCT_NAME}</h1>
          {!isSidebarOpen && (
            <button
              type="button"
              className="icon-btn app-header__new-chat"
              onClick={handleNewChat}
              aria-label="Шинэ яриа эхлүүлэх"
            >
              <NewChatIcon />
            </button>
          )}
        </header>
        <MessageList messages={messages} />
        {messages.length === 0 && <SuggestionChips onSelect={sendMessage} />}
        <ChatInput onSend={sendMessage} onStop={stopStreaming} disabled={isStreaming} />
      </div>
    </div>
  );
}
