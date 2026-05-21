import { describe, expect, it } from "vitest";
import type { OHLCVBar } from "@/lib/types";
import { ema, rsi, sma } from "./TickerChartWorkspace.indicators";

function makeBars(closes: number[]): OHLCVBar[] {
  return closes.map((close, i) => ({
    trade_date: `2026-01-${String(i + 1).padStart(2, "0")}`,
    open: close, high: close, low: close, close, volume: 1000,
  }));
}

describe("sma", () => {
  it("returns trailing average of the period", () => {
    const bars = makeBars([1, 2, 3, 4, 5]);
    const out = sma(bars, 3);
    // First 2 bars skipped; from bar index 2 onward: avg(1,2,3)=2, avg(2,3,4)=3, avg(3,4,5)=4
    expect(out).toEqual([
      { time: "2026-01-03", value: 2 },
      { time: "2026-01-04", value: 3 },
      { time: "2026-01-05", value: 4 },
    ]);
  });

  it("flat input gives flat output", () => {
    const bars = makeBars([10, 10, 10, 10, 10]);
    const out = sma(bars, 3);
    expect(out.every((p) => p.value === 10)).toBe(true);
  });

  it("period larger than length yields empty", () => {
    const bars = makeBars([1, 2]);
    expect(sma(bars, 5)).toEqual([]);
  });

  it("period of 1 yields the raw closes", () => {
    const bars = makeBars([1, 2, 3]);
    const out = sma(bars, 1);
    expect(out.map((p) => p.value)).toEqual([1, 2, 3]);
  });
});

describe("ema", () => {
  it("emits one point per bar; first equals first close", () => {
    const bars = makeBars([10, 11, 12]);
    const out = ema(bars, 3);
    expect(out.length).toBe(3);
    expect(out[0].value).toBe(10);
  });

  it("approaches input as period -> infinity (slow smoothing)", () => {
    const bars = makeBars([100, 200, 200, 200, 200, 200, 200, 200]);
    const out = ema(bars, 100);
    // With period=100, k = 2/101 ~= 0.0198. After 7 jumps from 100 to 200,
    // EMA should still be quite close to 100 (i.e., heavily smoothed).
    expect(out[out.length - 1].value).toBeLessThan(120);
  });

  it("period of 1 yields the raw closes (k=1)", () => {
    const bars = makeBars([1, 2, 3]);
    const out = ema(bars, 1);
    expect(out.map((p) => p.value)).toEqual([1, 2, 3]);
  });

  it("empty input yields empty output", () => {
    expect(ema([], 14)).toEqual([]);
  });
});

describe("rsi", () => {
  it("all-gain input yields 100", () => {
    const bars = makeBars([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]);
    const out = rsi(bars, 14);
    expect(out[out.length - 1].value).toBeCloseTo(100, 1);
  });

  it("all-loss input yields 0", () => {
    const bars = makeBars([16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]);
    const out = rsi(bars, 14);
    expect(out[out.length - 1].value).toBeCloseTo(0, 1);
  });

  it("alternating equal gain/loss stays near 50", () => {
    // 30 bars alternating +1/-1 around 100. After Wilder's initial window of 14
    // diffs (7 gains, 7 losses), the RSI starts at 50 and oscillates with each
    // subsequent bar. Check that it stays in the [40, 60] band — equal-magnitude
    // alternating input must not drift toward the extremes.
    const closes: number[] = [];
    let v = 100;
    for (let i = 0; i < 30; i++) { v += i % 2 === 0 ? 1 : -1; closes.push(v); }
    const bars = makeBars(closes);
    const out = rsi(bars, 14);
    const last = out[out.length - 1].value;
    expect(last).toBeGreaterThan(40);
    expect(last).toBeLessThan(60);
  });

  it("returns empty if bars.length <= period", () => {
    expect(rsi(makeBars([1, 2, 3]), 14)).toEqual([]);
  });
});
