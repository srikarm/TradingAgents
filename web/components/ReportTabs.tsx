"use client";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ReportSections } from "@/lib/types";

const ORDER: { key: keyof ReportSections; label: string }[] = [
  { key: "market", label: "Market" },
  { key: "sentiment", label: "Sentiment" },
  { key: "news", label: "News" },
  { key: "fundamentals", label: "Fundamentals" },
  { key: "investment_plan", label: "Research" },
  { key: "trader_plan", label: "Trader" },
  { key: "final", label: "Final" },
];

export default function ReportTabs({ sections }: { sections: ReportSections }) {
  const available = ORDER.filter((t) => sections[t.key]);
  const [active, setActive] = useState<keyof ReportSections | null>(
    available[0]?.key ?? null
  );
  if (!active) return <p style={{ color: "#6b7280" }}>No reports on disk for this run.</p>;
  return (
    <div>
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #e5e7eb",
                    marginBottom: 16, flexWrap: "wrap" }}>
        {available.map((t) => (
          <button
            key={t.key}
            onClick={() => setActive(t.key)}
            style={{
              padding: "8px 12px", border: "none", background: "transparent",
              borderBottom: active === t.key ? "2px solid #2563eb" : "2px solid transparent",
              cursor: "pointer", fontWeight: active === t.key ? 600 : 400,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <article className="prose">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {sections[active] ?? ""}
        </ReactMarkdown>
      </article>
    </div>
  );
}
