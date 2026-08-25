import { useMemo, useState } from "react";
import ConversationItem from "./ConversationItem.jsx";
import NewChatIcon from "./icons/NewChatIcon.jsx";
import SearchIcon from "./icons/SearchIcon.jsx";
import SidebarIcon from "./icons/SidebarIcon.jsx";
import { filterConversations, groupConversationsByRecency } from "../lib/groupConversations.js";

/*
  History panel. Persistent column on desktop, overlay drawer below the
  breakpoint (see index.css).

  Closed state keeps the panel mounted so it can animate, and CSS sets
  `visibility: hidden` on it — that also takes its buttons out of the tab
  order, so a collapsed panel is not a keyboard trap of invisible controls.
*/
export default function Sidebar({
  conversations,
  activeId,
  isOpen,
  onClose,
  onNewChat,
  onOpenConversation,
  onRenameConversation,
  onDeleteConversation,
}) {
  const [query, setQuery] = useState("");

  const groups = useMemo(
    () => groupConversationsByRecency(filterConversations(conversations, query)),
    [conversations, query],
  );

  const hasHistory = conversations.length > 0;
  const isSearching = query.trim().length > 0;

  return (
    <aside className={`sidebar${isOpen ? " sidebar--open" : ""}`}>
      <div className="sidebar__top">
        <div className="sidebar__brand">
          <img src="/logo-mark.png" alt="" className="sidebar__logo" />
          <span className="sidebar__brand-name">Бодлогын туслах</span>
        </div>
        <button
          type="button"
          className="icon-btn"
          onClick={onClose}
          aria-label="Түүхийн самбарыг хаах"
        >
          <SidebarIcon />
        </button>
      </div>

      <button type="button" className="sidebar__new-chat" onClick={onNewChat}>
        <NewChatIcon />
        Шинэ яриа
      </button>

      {hasHistory && (
        <div className="sidebar__search">
          <SearchIcon />
          <input
            type="search"
            className="sidebar__search-field"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Түүхээс хайх"
            aria-label="Түүхээс хайх"
          />
        </div>
      )}

      <nav className="sidebar__history" aria-label="Ярианы түүх">
        {groups.map((group) => (
          <section key={group.id} className="sidebar__group">
            <h2 className="sidebar__group-label">{group.label}</h2>
            <ul className="sidebar__group-list">
              {group.conversations.map((conversation) => (
                <ConversationItem
                  key={conversation.id}
                  conversation={conversation}
                  isActive={conversation.id === activeId}
                  onOpen={() => onOpenConversation(conversation.id)}
                  onRename={(title) => onRenameConversation(conversation.id, title)}
                  onDelete={() => onDeleteConversation(conversation.id)}
                />
              ))}
            </ul>
          </section>
        ))}

        {groups.length === 0 && (
          <p className="sidebar__empty">
            {isSearching
              ? `«${query.trim()}» хайлтад тохирох яриа олдсонгүй.`
              : "Хадгалсан яриа алга. Асуулт асуумагц энд хадгалагдана."}
          </p>
        )}
      </nav>

      <p className="sidebar__note">Түүх зөвхөн энэ хөтөч дээр хадгалагдана.</p>
    </aside>
  );
}
