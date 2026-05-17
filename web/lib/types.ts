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
