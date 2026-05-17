"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";
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
  try {
    const { run_id } = await api.createRun({
      ticker,
      trade_date,
      analysts: analysts.length ? analysts : undefined,
    });
    redirect(`/live/${run_id}`);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.includes("409")) {
      const match = msg.match(/"existing_run_id":\s*"([0-9a-f-]+)"/);
      if (match) return { kind: "conflict", existingRunId: match[1] };
    }
    return { kind: "unknown", message: msg };
  }
}
