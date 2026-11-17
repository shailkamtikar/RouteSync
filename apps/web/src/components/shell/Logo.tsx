/** RouteSync mark: a rounded tile with a route that bends through a stop. */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="RouteSync" fill="none">
      <rect width="32" height="32" rx="9" fill="var(--brand)" />
      <path
        d="M9 22.5c0-4.5 6-3.2 6-7.2 0-2.6-3-2.4-3-4.6 0-1.4 1.2-2.2 2.6-2.2h6.9"
        stroke="var(--brand-contrast)"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <circle cx="9" cy="23" r="2.6" fill="var(--brand-contrast)" />
      <circle cx="22.5" cy="8.5" r="2.6" fill="var(--brand-contrast)" opacity=".85" />
    </svg>
  );
}
