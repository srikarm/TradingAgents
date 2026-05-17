import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import Nav from "@/components/Nav";
import LaunchForm from "@/components/LaunchForm";

export default async function LaunchPage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  return (
    <>
      <Nav />
      <main style={{ padding: 24, maxWidth: 800, margin: "0 auto" }}>
        <h1>Launch a new analysis</h1>
        <p style={{ color: "#6b7280", marginBottom: 24 }}>
          The worker uses LLM provider credentials configured on the server.
          Per-user keys land in a future release.
        </p>
        <LaunchForm />
      </main>
    </>
  );
}
