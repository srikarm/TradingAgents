// Pure ranking helpers for the /signals feed. Lives in its own .ts file
// (separate from SignalsFeed.tsx) so vitest can import it without having
// to transform JSX — the project tsconfig uses `jsx: preserve` for Next.
import type { SignalOut } from "@/lib/types";

/**
 * A signal is "actionable" if it warrants attention from the user:
 *  - BUY  → potential entry
 *  - SELL → potential exit
 *  - null → still in-flight (rating not yet known)
 * HOLDs are non-actionable; they get visually de-emphasized below.
 */
export function isActionable(s: SignalOut): boolean {
  return s.final_rating === "BUY" || s.final_rating === "SELL" || s.final_rating === null;
}
