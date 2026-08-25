import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { loadConversations, saveConversations } from "../lib/conversationStore.js";
import { deriveTitle } from "../lib/conversationTitle.js";
import { PERSIST_DEBOUNCE_MS } from "../lib/historyConfig.js";
import { createId } from "../lib/ids.js";

const NO_MESSAGES = [];

/*
  Owns the conversation list, which one is open, and getting both to disk.

  Every mutation that touches a specific chat takes an explicit
  conversationId rather than acting on "the active one". Streaming is
  asynchronous and the user can open another chat while tokens are still
  arriving — an implicit "active" target would write those tokens into
  whichever chat they happened to be looking at.
*/
export function useConversations() {
  // Read once, synchronously, on mount: history that pops in a frame after
  // the first paint reads as a glitch.
  const [conversations, setConversations] = useState(loadConversations);
  const [activeId, setActiveId] = useState(null);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? null,
    [conversations, activeId],
  );

  const isFirstRender = useRef(true);
  useEffect(() => {
    // Nothing changed yet on mount — writing here would rewrite the payload
    // we just read for no reason.
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    const timer = setTimeout(() => saveConversations(conversations), PERSIST_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [conversations]);

  // Flush on unload so the last few hundred milliseconds of a streamed
  // answer are not lost if the tab closes inside the debounce window.
  const latestConversations = useRef(conversations);
  latestConversations.current = conversations;
  useEffect(() => {
    const flush = () => saveConversations(latestConversations.current);
    window.addEventListener("pagehide", flush);
    return () => window.removeEventListener("pagehide", flush);
  }, []);

  // Appends to `activeId`, creating the conversation on the first turn, and
  // returns the id the caller must use for the rest of that turn.
  const appendToActiveConversation = useCallback(
    (newMessages) => {
      const now = Date.now();

      if (activeId) {
        setConversations((prev) =>
          prev.map((conversation) =>
            conversation.id === activeId
              ? {
                  ...conversation,
                  updatedAt: now,
                  messages: [...conversation.messages, ...newMessages],
                }
              : conversation,
          ),
        );
        return activeId;
      }

      const id = createId();
      const firstUserMessage = newMessages.find((message) => message.role === "user");
      setConversations((prev) => [
        {
          id,
          title: deriveTitle(firstUserMessage?.text),
          createdAt: now,
          updatedAt: now,
          messages: newMessages,
        },
        ...prev,
      ]);
      setActiveId(id);
      return id;
    },
    [activeId],
  );

  const patchMessage = useCallback((conversationId, messageId, patch) => {
    setConversations((prev) =>
      prev.map((conversation) =>
        conversation.id === conversationId
          ? {
              ...conversation,
              updatedAt: Date.now(),
              messages: conversation.messages.map((message) =>
                message.id === messageId ? { ...message, ...patch } : message,
              ),
            }
          : conversation,
      ),
    );
  }, []);

  const renameConversation = useCallback((conversationId, title) => {
    const trimmed = title.trim();
    if (!trimmed) return;
    setConversations((prev) =>
      prev.map((conversation) =>
        conversation.id === conversationId ? { ...conversation, title: trimmed } : conversation,
      ),
    );
  }, []);

  const deleteConversation = useCallback(
    (conversationId) => {
      setConversations((prev) =>
        prev.filter((conversation) => conversation.id !== conversationId),
      );
      // Deleting the open chat drops you on a fresh one rather than an empty
      // view pointing at a record that no longer exists.
      if (conversationId === activeId) setActiveId(null);
    },
    [activeId],
  );

  const startNewConversation = useCallback(() => setActiveId(null), []);

  return {
    conversations,
    activeId,
    activeTitle: activeConversation?.title ?? null,
    messages: activeConversation?.messages ?? NO_MESSAGES,
    appendToActiveConversation,
    patchMessage,
    renameConversation,
    deleteConversation,
    openConversation: setActiveId,
    startNewConversation,
  };
}
