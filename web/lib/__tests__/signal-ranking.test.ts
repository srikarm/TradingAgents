import { describe, expect, it } from "vitest";
// isActionable lives in ranking.ts (re-exported from SignalsFeed.tsx).
// We import the .ts directly because vitest can't transform .tsx under
// Next's `jsx: preserve` tsconfig.
import { isActionable } from "@/app/signals/ranking";
import type { SignalOut } from "@/lib/types";

function s(rating: SignalOut["final_rating"]): SignalOut {
  return {
    run_id: "00000000-0000-0000-0000-000000000000",
    ticker: "X",
    trade_date: "2026-05-24",
    status: "succeeded",
    final_rating: rating,
    created_at: "2026-05-24T00:00:00Z",
    completed_at: null,
    notes: null,
  };
}

describe("isActionable", () => {
  it("returns true for BUY, SELL, null (in-flight)", () => {
    expect(isActionable(s("BUY"))).toBe(true);
    expect(isActionable(s("SELL"))).toBe(true);
    expect(isActionable(s(null))).toBe(true);
  });

  it("returns false for HOLD", () => {
    expect(isActionable(s("HOLD"))).toBe(false);
  });
});

describe("actionable/neutral split", () => {
  it("splits a mixed list 3/1", () => {
    const items = [s("BUY"), s("SELL"), s("HOLD"), s(null)];
    const actionable = items.filter(isActionable);
    const neutral = items.filter((x) => !isActionable(x));
    expect(actionable.length).toBe(3);
    expect(neutral.length).toBe(1);
    expect(neutral[0].final_rating).toBe("HOLD");
  });
});
