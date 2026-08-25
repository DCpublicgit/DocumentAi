import { useEffect, useRef } from "react";
import Message from "./Message.jsx";

export default function MessageList({ messages }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <main className="message-list message-list--empty">
        <div className="empty-state">
          <p>Компанийн бодлогын талаар асуултаа Монгол хэлээр бичнэ үү.</p>
        </div>
      </main>
    );
  }

  return (
    <main className="message-list">
      {messages.map((message) => (
        <Message key={message.id} message={message} />
      ))}
      <div ref={endRef} />
    </main>
  );
}
