import { describe, expect, it } from "vitest";
import { enableDisabledReason, thresholdLabel } from "./notification-copy";

describe("thresholdLabel", () => {
  it("joins two ratings with 'or'", () => {
    expect(thresholdLabel("BUY,SELL")).toBe("BUY or SELL");
  });
  it("returns a single rating as-is", () => {
    expect(thresholdLabel("BUY")).toBe("BUY");
  });
  it("oxford-joins three ratings", () => {
    expect(thresholdLabel("BUY, SELL, HOLD")).toBe("BUY, SELL or HOLD");
  });
  it("falls back to 'actionable' when empty", () => {
    expect(thresholdLabel("")).toBe("actionable");
  });
});

describe("enableDisabledReason", () => {
  it("blocks enable when no email is on record", () => {
    expect(enableDisabledReason(false)).not.toBeNull();
  });
  it("allows enable when an email is present", () => {
    expect(enableDisabledReason(true)).toBeNull();
  });
});
