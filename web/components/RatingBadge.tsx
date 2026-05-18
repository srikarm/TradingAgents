import { TrendingDown, TrendingUp, Minus, ArrowUp, ArrowDown } from "lucide-react";
import { cn } from "@/lib/cn";

// Rating taxonomy → outlined chip with icon. Outline rather than fill keeps
// the page reading "calm" — the data is the focus, not the badge.
const RATING_MAP: Record<
  string,
  { ring: string; text: string; Icon: typeof TrendingUp; label: string }
> = {
  Buy: {
    ring: "ring-success/30",
    text: "text-success",
    Icon: TrendingUp,
    label: "Buy",
  },
  Overweight: {
    ring: "ring-success/25",
    text: "text-success/90",
    Icon: ArrowUp,
    label: "Overweight",
  },
  Hold: {
    ring: "ring-border",
    text: "text-fg-muted",
    Icon: Minus,
    label: "Hold",
  },
  Underweight: {
    ring: "ring-warning/30",
    text: "text-warning",
    Icon: ArrowDown,
    label: "Underweight",
  },
  Sell: {
    ring: "ring-danger/30",
    text: "text-danger",
    Icon: TrendingDown,
    label: "Sell",
  },
};

export default function RatingBadge({ rating }: { rating: string | null }) {
  if (!rating) {
    return <span className="text-fg-subtle tabular-nums">—</span>;
  }
  const r = RATING_MAP[rating];
  if (!r) {
    return (
      <span className="inline-flex items-center rounded-full bg-surface px-2.5 py-1 text-[11px] font-medium text-fg-muted ring-1 ring-inset ring-border">
        {rating}
      </span>
    );
  }
  const Icon = r.Icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full bg-surface/60 px-2.5 py-1 text-[11px] font-medium ring-1 ring-inset backdrop-blur-sm",
        r.ring,
        r.text
      )}
    >
      <Icon className="h-3 w-3" strokeWidth={2.25} aria-hidden />
      {r.label}
    </span>
  );
}
