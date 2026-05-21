"use server";

import { redirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { AnalystKey } from "@/lib/types";

export type LaunchFormError =
  | { kind: "validation"; message: string }
  | { kind: "conflict"; existingRunId: string }
  | { kind: "unknown"; message: string };

export async function launchRunAction(formData: FormData): Promise<LaunchFormError | void> {
  const ticker = String(formData.get("ticker") ?? "").trim();
  const trade_date = String(formData.get("trade_date") ?? "").trim();
  if (!ticker || !trade_date) {
    return { kind: "validation", message: "Ticker and trade date are required." };
  }
  const analysts = (formData.getAll("analysts") as string[]).filter(
    (a): a is AnalystKey =>
      a === "market" || a === "social" || a === "news" || a === "fundamentals"
  );

  let runId: string;
  try {
    const res = await api.createRun({
      ticker,
      trade_date,
      analysts: analysts.length ? analysts : undefined,
    });
    runId = res.run_id;
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      const body = e.body as Record<string, unknown> | null;
      const detail = body?.detail as Record<string, unknown> | undefined;
      const existingRunId = detail?.existing_run_id;
      if (typeof existingRunId === "string") {
        return { kind: "conflict", existingRunId };
      }
    }
    const msg = e instanceof Error ? e.message : String(e);
    return { kind: "unknown", message: msg };
  }

  // Outside try: redirect() throws NEXT_REDIRECT, must not be caught.
  const watchLive = formData.get("watch_live") === "on";
  redirect(watchLive ? `/live/${runId}` : "/history");
}
