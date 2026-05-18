import type { components } from "@/lib/openapi-types";

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

// --- Wave 3: portfolio — generated from FastAPI Pydantic schemas ---
//
// These 7 types are re-exported from web/lib/openapi-types.ts. Do NOT
// hand-edit them here. After changing a Pydantic schema in
// server/app/schemas/portfolio.py, run `npm run codegen` to regenerate
// the openapi-types.ts file; the re-exports below pick up changes
// automatically. `npm run codegen:check` fails if the committed
// openapi-types.ts is stale relative to the current Pydantic schemas.
//
// Other types in this file (RunStatus, RunOut, etc.) remain
// hand-defined until their Pydantic counterparts are migrated.
// The `components` import is at the top of the file (line 1).

export type MemoryEntryStatus = components["schemas"]["MemoryEntryStatus"];
export type PortfolioSummaryOut = components["schemas"]["PortfolioSummaryOut"];
export type PnLPoint = components["schemas"]["PnLPoint"];
export type PortfolioCurveOut = components["schemas"]["PortfolioCurveOut"];
export type PricePoint = components["schemas"]["PricePoint"];
export type DecisionPin = components["schemas"]["DecisionPin"];
export type TickerDetailOut = components["schemas"]["TickerDetailOut"];
