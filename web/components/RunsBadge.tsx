"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { countActiveRunsAction } from "@/app/actions";

const POLL_INTERVAL_MS = 10_000;

export default function RunsBadge() {
  const [count, setCount] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await countActiveRunsAction();
        if (r.ok && !cancelled) setCount(r.data);
        // !ok (network blip / signed-out tab): keep last value; next tick retries.
      } catch {
        // Defensive: the action shouldn't throw, but never let the poller die.
      }
    };
    void tick();
    const id = setInterval(() => void tick(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (count === 0) return null;

  return (
    <Link
      href="/history"
      className="inline-flex items-center gap-1.5 rounded-full border border-brand/40 bg-brand/10 px-2.5 py-0.5 text-xs font-medium text-brand transition-colors hover:bg-brand/15"
      aria-label={`${count} ${count === 1 ? "run" : "runs"} in progress`}
    >
      <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
      <span>
        {count} {count === 1 ? "run" : "runs"}
      </span>
    </Link>
  );
}
