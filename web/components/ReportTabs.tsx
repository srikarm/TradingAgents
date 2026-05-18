"use client";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ReportSections } from "@/lib/types";
import { cn } from "@/lib/cn";

const ORDER: { key: keyof ReportSections; label: string }[] = [
  { key: "market", label: "Market" },
  { key: "sentiment", label: "Sentiment" },
  { key: "news", label: "News" },
  { key: "fundamentals", label: "Fundamentals" },
  { key: "investment_plan", label: "Research" },
  { key: "trader_plan", label: "Trader" },
  { key: "final", label: "Final" },
];

// remark-gfm is stateless; hoisting prevents a new array identity per render
// (the original Wave 1 review caught this).
const REMARK_PLUGINS = [remarkGfm];

export default function ReportTabs({ sections }: { sections: ReportSections }) {
  const available = ORDER.filter((t) => sections[t.key]);
  const [active, setActive] = useState<keyof ReportSections | null>(
    available[0]?.key ?? null
  );
  if (!active) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-surface/40 px-6 py-12 text-center text-sm text-fg-muted">
        No reports on disk for this run.
      </div>
    );
  }
  return (
    <div>
      <div
        role="tablist"
        className="mb-6 flex flex-wrap gap-1 border-b border-border"
      >
        {available.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={active === t.key}
            onClick={() => setActive(t.key)}
            className={cn(
              "relative h-10 px-4 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
              active === t.key
                ? "text-fg"
                : "text-fg-muted hover:text-fg"
            )}
          >
            {t.label}
            {active === t.key && (
              <span
                className="absolute inset-x-0 -bottom-px h-0.5 bg-brand"
                aria-hidden
              />
            )}
          </button>
        ))}
      </div>
      <article className="prose-report">
        <ReactMarkdown remarkPlugins={REMARK_PLUGINS}>
          {sections[active] ?? ""}
        </ReactMarkdown>
      </article>
    </div>
  );
}
