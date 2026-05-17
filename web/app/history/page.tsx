import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import RunCard from "@/components/RunCard";

export default async function HistoryPage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string }>;
}) {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  const { ticker } = await searchParams;
  const { items } = await api.listRuns(ticker);

  return (
    <>
      <Nav />
      <main style={{ padding: 24, maxWidth: 800, margin: "0 auto" }}>
        <h1>History</h1>
        <form>
          <input
            name="ticker"
            defaultValue={ticker ?? ""}
            placeholder="Filter by ticker (e.g. NVDA)"
            style={{ padding: 8, width: 240, marginBottom: 16 }}
          />
          <button type="submit" style={{ marginLeft: 8 }}>Filter</button>
        </form>
        {items.length === 0 ? (
          <p style={{ color: "#6b7280" }}>No runs yet. Run the importer or launch a new run (Wave 2).</p>
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            {items.map((r) => <RunCard key={r.id} run={r} />)}
          </div>
        )}
      </main>
    </>
  );
}
