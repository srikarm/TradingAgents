import type { OHLCVBar } from "@/lib/types";

export interface IndicatorPoint {
  time: string;
  value: number;
}

export function sma(bars: OHLCVBar[], period: number): IndicatorPoint[] {
  if (period < 1) throw new Error("SMA period must be >= 1");
  const out: IndicatorPoint[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= period) sum -= bars[i - period].close;
    if (i >= period - 1) {
      out.push({ time: bars[i].trade_date, value: sum / period });
    }
  }
  return out;
}

export function ema(bars: OHLCVBar[], period: number): IndicatorPoint[] {
  if (period < 1) throw new Error("EMA period must be >= 1");
  if (bars.length === 0) return [];
  const k = 2 / (period + 1);
  const out: IndicatorPoint[] = [];
  let prev = bars[0].close;
  out.push({ time: bars[0].trade_date, value: prev });
  for (let i = 1; i < bars.length; i++) {
    prev = bars[i].close * k + prev * (1 - k);
    out.push({ time: bars[i].trade_date, value: prev });
  }
  return out;
}

export function rsi(bars: OHLCVBar[], period: number): IndicatorPoint[] {
  if (period < 1) throw new Error("RSI period must be >= 1");
  if (bars.length <= period) return [];

  // Wilder's smoothing: initial avg from the first `period` deltas,
  // then EMA-like recursion with alpha = 1/period.
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = bars[i].close - bars[i - 1].close;
    if (d > 0) avgGain += d;
    else avgLoss -= d;
  }
  avgGain /= period;
  avgLoss /= period;

  const out: IndicatorPoint[] = [];
  const epsilon = 1e-10;
  out.push({
    time: bars[period].trade_date,
    value: 100 - 100 / (1 + avgGain / (avgLoss || epsilon)),
  });

  for (let i = period + 1; i < bars.length; i++) {
    const d = bars[i].close - bars[i - 1].close;
    const gain = d > 0 ? d : 0;
    const loss = d < 0 ? -d : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    const rs = avgGain / (avgLoss || epsilon);
    out.push({
      time: bars[i].trade_date,
      value: 100 - 100 / (1 + rs),
    });
  }

  return out;
}
