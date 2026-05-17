export type RunStatus = "queued" | "running" | "succeeded" | "failed";

export interface RunOut {
  id: string;
  ticker: string;
  trade_date: string;
  status: RunStatus;
  final_rating: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface RunListOut {
  items: RunOut[];
}

export interface ReportSections {
  market: string | null;
  sentiment: string | null;
  news: string | null;
  fundamentals: string | null;
  investment_plan: string | null;
  trader_plan: string | null;
  final: string | null;
}

export interface RunDetailOut extends RunOut {
  results_path: string;
  error_summary: string | null;
  report_sections: ReportSections;
}

export interface UserOut {
  id: string;
  github_id: string;
  email: string | null;
  created_at: string;
}

export type AnalystKey = "market" | "social" | "news" | "fundamentals";

export interface RunCreate {
  ticker: string;
  trade_date: string;
  analysts?: AnalystKey[];
  asset_type?: "stock" | "crypto";
}

export interface RunTailOut {
  content: string;
  next_offset: number;
  status: RunStatus;
}

// --- Wave 3: portfolio ---

export type MemoryEntryStatus = "pending" | "resolved";

export interface PortfolioSummaryOut {
  trade_count: number;
  win_rate: number;
  sharpe: number;
  max_drawdown: number;
  cumulative_return: number;
}

export interface PnLPoint {
  trade_date: string;
  cumulative_pnl: number;
}

export interface PortfolioCurveOut {
  points: PnLPoint[];
}

export interface PricePoint {
  trade_date: string;
  close: number;
}

export interface DecisionPin {
  trade_date: string;
  rating: string;
  status: MemoryEntryStatus;
  raw_return: number | null;
}

export interface TickerDetailOut {
  ticker: string;
  prices: PricePoint[];
  decisions: DecisionPin[];
}
