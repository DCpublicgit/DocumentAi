import { useEffect, useState } from "react";
import { SIDEBAR_BREAKPOINT_PX } from "../lib/historyConfig.js";

const QUERY = `(min-width: ${SIDEBAR_BREAKPOINT_PX}px)`;

// True when the viewport is wide enough for the history panel to sit beside
// the conversation instead of over it. Drives behavior CSS cannot express:
// the panel's initial state, and whether opening a chat should dismiss the
// panel (it should, when the panel is covering the chat).
export function useIsWideViewport() {
  const [isWide, setIsWide] = useState(() => window.matchMedia(QUERY).matches);

  useEffect(() => {
    const mediaQuery = window.matchMedia(QUERY);
    const handleChange = (event) => setIsWide(event.matches);
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  return isWide;
}
