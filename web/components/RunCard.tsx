import Link from "next/link";
import type { RunOut } from "@/lib/types";
import RatingBadge from "./RatingBadge";

export default function RunCard({ run }: { run: RunOut }) {
  return (
    <div style={{
      border: "1px solid #e5e7eb", borderRadius: 8, padding: 16,
      display: "flex", justifyContent: "space-between", alignItems: "center",
    }}>
      <Link href={`/history/${run.id}`}
            style={{ textDecoration: "none", color: "inherit", flex: 1 }}>
        <div style={{ fontWeight: 600 }}>{run.ticker}</div>
        <div style={{ fontSize: 12, color: "#6b7280" }}>{run.trade_date}</div>
      </Link>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <RatingBadge rating={run.final_rating} />
        <Link href={`/portfolio/${run.ticker}`}
              style={{ fontSize: 12, color: "#6b7280" }}>
          View ticker
        </Link>
      </div>
    </div>
  );
}
