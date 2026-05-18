"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, WifiOff } from "lucide-react";
import type { RunStatus, RunTailOut } from "@/lib/types";
import StatusBadge from "./StatusBadge";
import { cn } from "@/lib/cn";

interface Props {
  runId: string;
  initialStatus: RunStatus;
  pollIntervalMs?: number;
  maxConsecutiveFailures?: number;
}

/** Token a log line into (timestamp, kind, rest). The worker writes lines like:
 *
 *   2026-05-18T11:18:29+00:00 [start] launching propagate for NVDA on 2024-05-10
 *   2026-05-18T11:18:31+00:00 [heartbeat] still running
 *   2026-05-18T11:18:35+00:00 [node] Market Analyst
 *   2026-05-18T11:18:42+00:00 [completed] final_rating=Buy
 *   2026-05-18T11:18:42+00:00 [failed] OpenAI 429
 *
 * If a line doesn't match the convention, kind=null and rest=line. The whole
 * tokeniser is forgiving — never throws, always returns something.
 */
type LineKind =
  | "start"
  | "heartbeat"
  | "node"
  | "completed"
  | "failed"
  | "info";

function tokenize(raw: string): { ts: string | null; kind: LineKind | null; rest: string } {
  const m = raw.match(/^(\S+)\s+\[(\w+)\]\s*(.*)$/);
  if (!m) return { ts: null, kind: null, rest: raw };
  const kind = m[2].toLowerCase();
  const known: LineKind[] = ["start", "heartbeat", "node", "completed", "failed", "info"];
  return {
    ts: m[1],
    kind: (known as string[]).includes(kind) ? (kind as LineKind) : null,
    rest: m[3],
  };
}

const KIND_STYLES: Record<LineKind, string> = {
  start:     "text-info",
  heartbeat: "text-fg-subtle",
  node:      "text-brand",
  completed: "text-success",
  failed:    "text-danger",
  info:      "text-fg-muted",
};

export default function LiveLogStream({
  runId,
  initialStatus,
  pollIntervalMs = 2000,
  maxConsecutiveFailures = 5,
}: Props) {
  const [content, setContent] = useState("");
  const [status, setStatus] = useState<RunStatus>(initialStatus);
  const [streamHealth, setStreamHealth] = useState<"ok" | "degraded" | "broken">("ok");
  const offsetRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (status === "succeeded" || status === "failed") return;
    const ctl = new AbortController();
    let stopped = false;
    let backoffMs = pollIntervalMs;
    let consecutiveFailures = 0;

    async function poll() {
      while (!stopped) {
        try {
          const res = await fetch(`/api/runs/${runId}/tail?since=${offsetRef.current}`, {
            signal: ctl.signal,
            cache: "no-store",
          });
          if (!res.ok) {
            consecutiveFailures += 1;
            backoffMs = Math.min(backoffMs * 2, 16000);
            if (consecutiveFailures >= maxConsecutiveFailures) {
              setStreamHealth("broken");
              console.error(`stream gave up after ${consecutiveFailures} failures (last status ${res.status})`);
              break;
            } else if (consecutiveFailures >= 2) {
              setStreamHealth("degraded");
            }
          } else {
            consecutiveFailures = 0;
            setStreamHealth("ok");
            const data: RunTailOut = await res.json();
            offsetRef.current = data.next_offset;
            if (data.content) setContent((c) => c + data.content);
            setStatus(data.status);
            backoffMs = pollIntervalMs;
            if (data.status === "succeeded" || data.status === "failed") break;
          }
        } catch (e) {
          if (ctl.signal.aborted) return;
          consecutiveFailures += 1;
          backoffMs = Math.min(backoffMs * 2, 16000);
          console.error("tail poll failed:", e);
          if (consecutiveFailures >= maxConsecutiveFailures) {
            setStreamHealth("broken");
            break;
          } else if (consecutiveFailures >= 2) {
            setStreamHealth("degraded");
          }
        }
        await new Promise((r) => setTimeout(r, backoffMs));
      }
    }

    poll();
    return () => {
      stopped = true;
      ctl.abort();
    };
  }, [runId, status, pollIntervalMs, maxConsecutiveFailures]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [content]);

  // Split into lines once per content update — feeds the colorized render below.
  const lines = useMemo(() => {
    if (!content) return [];
    // Trim trailing newline so we don't render a phantom blank row.
    return content.replace(/\n$/, "").split("\n").map(tokenize);
  }, [content]);

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      {/* Terminal-style header bar: traffic-light dots + status + stream health */}
      <div className="flex items-center gap-3 border-b border-border bg-elevated/50 px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-danger/70" aria-hidden />
          <span className="h-2.5 w-2.5 rounded-full bg-warning/70" aria-hidden />
          <span className="h-2.5 w-2.5 rounded-full bg-success/70" aria-hidden />
        </div>
        <span className="ml-2 font-mono text-xs text-fg-subtle">message_tool.log</span>
        <div className="ml-auto flex items-center gap-3">
          {streamHealth === "degraded" && (
            <span className="inline-flex items-center gap-1.5 text-xs text-warning">
              <WifiOff className="h-3 w-3" aria-hidden />
              Reconnecting…
            </span>
          )}
          {streamHealth === "broken" && (
            <span className="inline-flex items-center gap-1.5 text-xs text-danger">
              <AlertTriangle className="h-3 w-3" aria-hidden />
              Stream unavailable — reload to retry
            </span>
          )}
          <StatusBadge status={status} />
        </div>
      </div>

      {/* Log body — colorized + monospace */}
      <div
        ref={scrollRef}
        className="max-h-[600px] overflow-y-auto bg-bg px-4 py-3 font-mono text-xs leading-relaxed"
        role="log"
        aria-live="polite"
        aria-label="Worker log stream"
      >
        {lines.length === 0 ? (
          <div className="flex items-center gap-2 text-fg-subtle">
            <span className="inline-block h-2 w-2 animate-pulse-soft rounded-full bg-warning" aria-hidden />
            Waiting for output…
          </div>
        ) : (
          <div className="space-y-0.5">
            {lines.map((ln, i) => (
              <div key={i} className="flex gap-3 whitespace-pre-wrap break-words">
                {ln.ts && (
                  <span className="flex-shrink-0 select-none text-fg-subtle">
                    {ln.ts.slice(11, 19)}
                  </span>
                )}
                {ln.kind ? (
                  <>
                    <span className={cn("flex-shrink-0 font-semibold", KIND_STYLES[ln.kind])}>
                      [{ln.kind}]
                    </span>
                    <span className="min-w-0 flex-1 text-fg">{ln.rest}</span>
                  </>
                ) : (
                  <span className="min-w-0 flex-1 text-fg-muted">{ln.rest}</span>
                )}
              </div>
            ))}
            {/* Blinking cursor when active */}
            {(status === "running" || status === "queued") && (
              <span className="inline-block h-3.5 w-1.5 animate-pulse-soft bg-brand align-text-bottom" aria-hidden />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
