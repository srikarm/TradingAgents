"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { addToWatchlistAction } from "@/app/actions";

const TICKER_PATTERN = /^[A-Z][A-Z0-9.\-]{0,11}$/;

export default function QuickAddForm() {
  const router = useRouter();
  const [ticker, setTicker] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!TICKER_PATTERN.test(ticker)) {
      setError("Ticker must be uppercase letters, digits, '.' or '-' (1-12 chars).");
      return;
    }

    setSubmitting(true);
    try {
      const r = await addToWatchlistAction(ticker, notes.trim() || null);
      if (!r.ok) {
        if (r.status === 409) {
          setError(`${ticker} is already on your watchlist.`);
        } else if (r.status === 422) {
          setError("Server rejected this ticker. Use only uppercase letters, digits, '.' or '-'.");
        } else {
          setError(r.message);
        }
        return;
      }
      setTicker("");
      setNotes("");
      router.refresh(); // Re-fetch the server component's data.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-xl border border-border/60 bg-surface/40 p-4 backdrop-blur-sm"
    >
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          name="ticker"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="e.g. BBCA.JK"
          aria-label="Ticker"
          className="h-10 w-full max-w-xs rounded-lg border border-border/60 bg-surface/40 px-3 font-mono text-sm text-fg placeholder:text-fg-subtle/70 focus:border-brand/60 focus:outline-none focus:ring-1 focus:ring-brand/40"
          required
        />
        <input
          name="notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Optional notes (e.g. watching for breakout)"
          aria-label="Notes"
          maxLength={500}
          className="h-10 flex-1 rounded-lg border border-border/60 bg-surface/40 px-3 text-sm text-fg placeholder:text-fg-subtle/70 focus:border-brand/60 focus:outline-none focus:ring-1 focus:ring-brand/40"
        />
        <button
          type="submit"
          disabled={submitting || !ticker}
          className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-brand/60 bg-brand/10 px-4 text-sm font-medium text-brand transition-colors hover:bg-brand/15 disabled:opacity-50"
        >
          <Plus className="h-4 w-4" aria-hidden />
          Add
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {error}
        </p>
      )}
    </form>
  );
}
