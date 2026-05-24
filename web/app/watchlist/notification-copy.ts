// Pure copy/logic helpers for NotificationSection, split out so vitest can
// transform them without the JSX-bearing component (Next.js requires
// jsx: preserve, which vitest can't transform — same pattern as signals/ranking.ts).

/** "BUY,SELL" → "BUY or SELL"; "BUY" → "BUY"; "" → "actionable". */
export function thresholdLabel(threshold: string): string {
  const parts = threshold.split(",").map((p) => p.trim()).filter(Boolean);
  if (parts.length === 0) return "actionable";
  if (parts.length === 1) return parts[0];
  return parts.slice(0, -1).join(", ") + " or " + parts[parts.length - 1];
}

/** Reason the Enable button is blocked, or null if it can be enabled. */
export function enableDisabledReason(hasEmail: boolean): string | null {
  return hasEmail ? null : "Add an email to your account to enable alerts.";
}
