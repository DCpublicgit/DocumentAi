// Replaces the design comp's "👎" emoji.
export default function ThumbDownIcon({ filled }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M17 2v11M22 11V4a2 2 0 0 0-2-2H6.6a2 2 0 0 0-2 1.6l-1.4 7A2 2 0 0 0 5 13h5.5l-1 5.5a1.5 1.5 0 0 0 2.6 1.3L17 13" />
    </svg>
  );
}
