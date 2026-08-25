// Magnifying glass with an X — "searched, not found" — deliberately not an
// alert/error glyph, since a refusal is correct behavior, not a failure.
export default function RefusalIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="10" cy="10" r="6.5" />
      <path d="M14.5 14.5L20 20" />
      <path d="M7.5 7.5L12.5 12.5" />
      <path d="M12.5 7.5L7.5 12.5" />
    </svg>
  );
}
