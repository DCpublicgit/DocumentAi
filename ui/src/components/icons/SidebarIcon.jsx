// Panel-toggle mark: a frame with the sidebar rail drawn in, so the button
// reads as "the left panel" rather than a generic hamburger.
export default function SidebarIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="4" width="18" height="16" rx="3" />
      <path d="M9.5 4V20" />
    </svg>
  );
}
