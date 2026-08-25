// Replaces the design comp's "👍" emoji.
export default function ThumbUpIcon({ filled }) {
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
      <path d="M7 22V11M2 13v7a2 2 0 0 0 2 2h13.4a2 2 0 0 0 2-1.6l1.4-7A2 2 0 0 0 19 11h-5.5l1-5.5a1.5 1.5 0 0 0-2.6-1.3L7 11" />
    </svg>
  );
}
