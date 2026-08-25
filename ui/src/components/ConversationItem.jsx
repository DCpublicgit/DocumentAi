import { useEffect, useLayoutEffect, useRef, useState } from "react";
import MoreIcon from "./icons/MoreIcon.jsx";
import PencilIcon from "./icons/PencilIcon.jsx";
import TrashIcon from "./icons/TrashIcon.jsx";

const MENU_EDGE_PADDING = 8;

/*
  One history row: open, rename, delete.

  The actions menu is `position: fixed` and coordinates are measured from the
  trigger, because the row lives inside the scrolling history list — an
  absolutely positioned menu would be clipped by that `overflow-y: auto`
  ancestor. Anything that invalidates those coordinates (scroll, resize) or
  moves the user's attention elsewhere (Escape, a click outside) closes it
  instead of leaving a detached menu floating over the page.

  Delete confirms inline, in the menu itself. A modal for deleting one chat
  row would interrupt a task that needs no protection, and window.confirm()
  cannot be styled or made to match the surface.
*/
export default function ConversationItem({ conversation, isActive, onOpen, onRename, onDelete }) {
  const [menuState, setMenuState] = useState("closed"); // closed | open | confirming-delete
  const [menuPosition, setMenuPosition] = useState(null);
  const [draftTitle, setDraftTitle] = useState(null); // non-null while renaming

  const triggerRef = useRef(null);
  const menuRef = useRef(null);

  const isMenuOpen = menuState !== "closed";

  const closeMenu = ({ restoreFocus = true } = {}) => {
    setMenuState("closed");
    setMenuPosition(null);
    if (restoreFocus) triggerRef.current?.focus();
  };

  const openMenu = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setMenuPosition({ top: rect.bottom + 4, left: rect.left });
    setMenuState("open");
  };

  // Keep the menu on screen: measured after paint, when its real width and
  // height are known, so a row near the viewport edge does not push it out.
  useLayoutEffect(() => {
    if (!isMenuOpen || !menuPosition || !menuRef.current) return;
    const menu = menuRef.current.getBoundingClientRect();
    const maxLeft = window.innerWidth - menu.width - MENU_EDGE_PADDING;
    const maxTop = window.innerHeight - menu.height - MENU_EDGE_PADDING;
    const left = Math.max(MENU_EDGE_PADDING, Math.min(menuPosition.left, maxLeft));
    const top = Math.max(MENU_EDGE_PADDING, Math.min(menuPosition.top, maxTop));
    if (left !== menuPosition.left || top !== menuPosition.top) {
      setMenuPosition({ top, left });
    }
  }, [isMenuOpen, menuPosition]);

  useEffect(() => {
    if (!isMenuOpen) return;

    const handlePointerDown = (event) => {
      if (menuRef.current?.contains(event.target)) return;
      if (triggerRef.current?.contains(event.target)) return;
      closeMenu({ restoreFocus: false });
    };
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        closeMenu();
      }
    };
    const handleReflow = () => closeMenu({ restoreFocus: false });

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    // Capture phase: the history list scrolls, and a scroll on it does not
    // bubble to window.
    window.addEventListener("scroll", handleReflow, true);
    window.addEventListener("resize", handleReflow);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("scroll", handleReflow, true);
      window.removeEventListener("resize", handleReflow);
    };
  }, [isMenuOpen]);

  const startRenaming = () => {
    setDraftTitle(conversation.title);
    closeMenu({ restoreFocus: false });
  };

  const commitRename = () => {
    if (draftTitle === null) return;
    onRename(draftTitle);
    setDraftTitle(null);
  };

  if (draftTitle !== null) {
    return (
      <li className="conversation-item conversation-item--renaming">
        <input
          className="conversation-item__rename"
          value={draftTitle}
          autoFocus
          onFocus={(event) => event.target.select()}
          onChange={(event) => setDraftTitle(event.target.value)}
          onBlur={commitRename}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commitRename();
            } else if (event.key === "Escape") {
              event.preventDefault();
              setDraftTitle(null);
            }
          }}
          aria-label="Ярианы нэр"
        />
      </li>
    );
  }

  return (
    <li
      className={[
        "conversation-item",
        isActive ? "conversation-item--active" : "",
        isMenuOpen ? "conversation-item--menu-open" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <button
        type="button"
        className="conversation-item__open"
        onClick={onOpen}
        aria-current={isActive ? "true" : undefined}
      >
        <span className="conversation-item__title">{conversation.title}</span>
      </button>

      <button
        type="button"
        ref={triggerRef}
        className="conversation-item__trigger"
        onClick={() => (isMenuOpen ? closeMenu() : openMenu())}
        aria-haspopup="menu"
        aria-expanded={isMenuOpen}
        aria-label={`${conversation.title} — үйлдлүүд`}
      >
        <MoreIcon />
      </button>

      {isMenuOpen && menuPosition && (
        <div
          ref={menuRef}
          className="conversation-menu"
          role="menu"
          style={{ top: `${menuPosition.top}px`, left: `${menuPosition.left}px` }}
        >
          {menuState === "open" ? (
            <>
              <button
                type="button"
                role="menuitem"
                className="conversation-menu__item"
                autoFocus
                onClick={startRenaming}
              >
                <PencilIcon />
                Нэр өөрчлөх
              </button>
              <button
                type="button"
                role="menuitem"
                className="conversation-menu__item conversation-menu__item--danger"
                onClick={() => setMenuState("confirming-delete")}
              >
                <TrashIcon />
                Устгах
              </button>
            </>
          ) : (
            <div className="conversation-menu__confirm">
              <p className="conversation-menu__confirm-text">Энэ яриаг устгах уу?</p>
              <div className="conversation-menu__confirm-actions">
                <button
                  type="button"
                  className="conversation-menu__confirm-btn conversation-menu__confirm-btn--danger"
                  autoFocus
                  onClick={() => {
                    closeMenu({ restoreFocus: false });
                    onDelete();
                  }}
                >
                  Устгах
                </button>
                <button
                  type="button"
                  className="conversation-menu__confirm-btn"
                  onClick={() => setMenuState("open")}
                >
                  Болих
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </li>
  );
}
