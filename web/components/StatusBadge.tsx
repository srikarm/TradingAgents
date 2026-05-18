import { Loader2 } from "lucide-react";
import type { RunStatus } from "@/lib/types";
import { cn } from "@/lib/cn";

const VARIANTS: Record<
  RunStatus,
  { label: string; dot: string; text: string; animate?: boolean }
> = {
  queued: {
    label: "Queued",
    dot: "bg-info",
    text: "text-info",
  },
  running: {
    label: "Running",
    dot: "bg-warning",
    text: "text-warning",
    animate: true,
  },
  succeeded: {
    label: "Succeeded",
    dot: "bg-success",
    text: "text-success",
  },
  failed: {
    label: "Failed",
    dot: "bg-danger",
    text: "text-danger",
  },
};

export default function StatusBadge({ status }: { status: RunStatus }) {
  const v = VARIANTS[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border/80 bg-surface/60 px-2.5 py-1 text-[11px] font-medium backdrop-blur-sm",
        v.text
      )}
    >
      {v.animate ? (
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
      ) : (
        <span
          className={cn("h-1.5 w-1.5 rounded-full", v.dot, v.animate && "animate-pulse-soft")}
          aria-hidden
        />
      )}
      {v.label}
    </span>
  );
}
