"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { launchRunAction, type LaunchFormError } from "@/app/launch/actions";

const ANALYSTS = [
  { key: "market", label: "Market" },
  { key: "social", label: "Social" },
  { key: "news", label: "News" },
  { key: "fundamentals", label: "Fundamentals" },
] as const;

export default function LaunchForm() {
  const [error, setError] = useState<LaunchFormError | null>(null);
  const [isPending, startTransition] = useTransition();
  const router = useRouter();

  const onSubmit = (fd: FormData) => {
    startTransition(async () => {
      const res = await launchRunAction(fd);
      if (res) setError(res);
    });
  };

  return (
    <form
      action={onSubmit}
      style={{ display: "grid", gap: 12, maxWidth: 400 }}
    >
      <label>
        Ticker
        <input
          name="ticker"
          required
          maxLength={12}
          placeholder="NVDA"
          style={{ padding: 8, width: "100%" }}
        />
      </label>
      <label>
        Trade date
        <input
          name="trade_date"
          type="date"
          required
          style={{ padding: 8, width: "100%" }}
        />
      </label>
      <fieldset style={{ border: "1px solid #e5e7eb", padding: 12, borderRadius: 6 }}>
        <legend>Analysts</legend>
        {ANALYSTS.map((a) => (
          <label key={a.key} style={{ display: "block", padding: "2px 0" }}>
            <input type="checkbox" name="analysts" value={a.key} defaultChecked />
            &nbsp;{a.label}
          </label>
        ))}
      </fieldset>
      <button
        type="submit"
        disabled={isPending}
        style={{
          padding: "10px 20px", background: "#2563eb", color: "#fff",
          border: "none", borderRadius: 6, cursor: isPending ? "wait" : "pointer",
        }}
      >
        {isPending ? "Launching..." : "Launch"}
      </button>
      {error && (
        <div style={{ color: "#dc2626", padding: 8, background: "#fef2f2", borderRadius: 6 }}>
          {error.kind === "conflict" ? (
            <>
              A run is already in progress for this ticker+date.{" "}
              <button
                type="button"
                onClick={() => router.push(`/live/${error.existingRunId}`)}
                style={{ textDecoration: "underline", background: "none", border: "none", color: "#dc2626", cursor: "pointer" }}
              >
                View running run
              </button>
            </>
          ) : (
            error.message
          )}
        </div>
      )}
    </form>
  );
}
