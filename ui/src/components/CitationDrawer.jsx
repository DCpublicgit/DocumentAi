import { useEffect, useRef } from "react";
import CloseIcon from "./icons/CloseIcon.jsx";

// Mounted only while a citation is open (App.jsx: {openCitation && <CitationDrawer .../>}) —
// every open is a fresh mount, which is what lets the effect below capture
// "whatever was focused right before this one opened" freshly each time,
// and hand focus back to exactly that element when this one closes.
export default function CitationDrawer({ citation, onClose }) {
  const closeButtonRef = useRef(null);
  const triggerRef = useRef(null);
  // A ref, not a dependency, so this effect runs exactly once per mount —
  // re-running it on every `onClose` identity change would re-capture
  // document.activeElement (as itself, the close button) and re-steal focus.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    triggerRef.current = document.activeElement;
    closeButtonRef.current?.focus();

    const handleKeyDown = (event) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      // The trigger (an inline "[N]" marker or a CitationPanel button) is
      // still in the DOM — the message it belongs to isn't going anywhere —
      // so focus has somewhere real to land back on.
      triggerRef.current?.focus?.();
    };
  }, []);

  if (!citation) return null;

  const { title, clause, snippet, charStart, charEnd, docId } = citation;
  const hasHighlight = charStart != null && charEnd != null && charEnd > charStart;

  return (
    <>
      <div className="citation-drawer__scrim" onClick={onClose} aria-hidden="true" />
      <div className="citation-drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="citation-drawer__header">
          <div className="citation-drawer__heading">
            <h2 className="citation-drawer__title">{title}</h2>
            {clause && <p className="citation-drawer__clause">Заалт {clause}</p>}
          </div>
          <button
            type="button"
            ref={closeButtonRef}
            className="citation-drawer__close icon-btn"
            onClick={onClose}
            aria-label="Хаах"
          >
            <CloseIcon />
          </button>
        </div>
        <p className="citation-drawer__snippet">
          {hasHighlight ? (
            <>
              {snippet.slice(0, charStart)}
              <mark>{snippet.slice(charStart, charEnd)}</mark>
              {snippet.slice(charEnd)}
            </>
          ) : (
            snippet
          )}
        </p>
        <a
          className="citation-drawer__doc-link"
          href={`/v1/documents/${encodeURIComponent(docId)}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          Бүтэн баримт бичгийг харах ↗
        </a>
      </div>
    </>
  );
}
