"use client";

import { useEffect, useRef, useState } from "react";
import type { RunStatus, RunTailOut } from "@/lib/types";

interface Props {
  runId: string;
  initialStatus: RunStatus;
  pollIntervalMs?: number;
}

export default function LiveLogStream({ runId, initialStatus, pollIntervalMs = 2000 }: Props) {
  const [content, setContent] = useState("");
  const [status, setStatus] = useState<RunStatus>(initialStatus);
  const offsetRef = useRef(0);
  const scrollRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    if (status === "succeeded" || status === "failed") return;
    const ctl = new AbortController();
    let stopped = false;
    let backoffMs = pollIntervalMs;

    async function poll() {
      while (!stopped) {
        try {
          const res = await fetch(`/api/runs/${runId}/tail?since=${offsetRef.current}`, {
            signal: ctl.signal,
            cache: "no-store",
          });
          if (!res.ok) {
            backoffMs = Math.min(backoffMs * 2, 16000);
          } else {
            const data: RunTailOut = await res.json();
            offsetRef.current = data.next_offset;
            if (data.content) setContent((c) => c + data.content);
            setStatus(data.status);
            backoffMs = pollIntervalMs;
            if (data.status === "succeeded" || data.status === "failed") break;
          }
        } catch (e) {
          if (ctl.signal.aborted) return;
          backoffMs = Math.min(backoffMs * 2, 16000);
        }
        await new Promise((r) => setTimeout(r, backoffMs));
      }
    }

    poll();
    return () => {
      stopped = true;
      ctl.abort();
    };
  }, [runId, status, pollIntervalMs]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [content]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{
          display: "inline-block", width: 8, height: 8, borderRadius: "50%",
          background: status === "running" ? "#22c55e" :
                      status === "queued" ? "#f59e0b" :
                      status === "succeeded" ? "#2563eb" : "#dc2626",
          animation: status === "running" ? "pulse 1.5s infinite" : "none",
        }} />
        <strong style={{ textTransform: "uppercase", fontSize: 12 }}>{status}</strong>
      </div>
      <pre
        ref={scrollRef}
        style={{
          background: "#0f172a", color: "#e2e8f0",
          padding: 16, borderRadius: 8,
          maxHeight: 500, overflow: "auto",
          fontSize: 12, fontFamily: "ui-monospace, monospace",
          whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}
      >
        {content || "(waiting for output...)"}
      </pre>
      <style>{`@keyframes pulse { 0%, 100% { opacity: 1 } 50% { opacity: 0.4 } }`}</style>
    </div>
  );
}
