import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import RunCard from "@/components/RunCard";

export default async function LivePage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  const { items } = await api.listRuns();
  const active = items.filter((r) => r.status === "queued" || r.status === "running");
  const recent = items.filter((r) => r.status === "succeeded" || r.status === "failed").slice(0, 10);

  return (
    <>
      <Nav />
      <main style={{ padding: 24, maxWidth: 800, margin: "0 auto" }}>
        <h1>Live runs</h1>
        <section style={{ marginBottom: 32 }}>
          <h2 style={{ fontSize: 18, color: "#374151" }}>Active</h2>
          {active.length === 0 ? (
            <p style={{ color: "#6b7280" }}>
              No active runs. <a href="/launch" style={{ color: "#2563eb" }}>Launch one →</a>
            </p>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {active.map((r) => (
                <a key={r.id} href={`/live/${r.id}`} style={{ textDecoration: "none", color: "inherit" }}>
                  <RunCard run={r} />
                </a>
              ))}
            </div>
          )}
        </section>
        <section>
          <h2 style={{ fontSize: 18, color: "#374151" }}>Recent</h2>
          <div style={{ display: "grid", gap: 12 }}>
            {recent.map((r) => <RunCard key={r.id} run={r} />)}
          </div>
        </section>
      </main>
    </>
  );
}
