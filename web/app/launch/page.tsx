import { redirect } from "next/navigation";
import { Info } from "lucide-react";
import { auth } from "@/lib/auth";
import Nav from "@/components/Nav";
import PageHeader from "@/components/PageHeader";
import LaunchForm from "@/components/LaunchForm";

export default async function LaunchPage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  return (
    <>
      <Nav />
      <main className="mx-auto max-w-7xl px-4 py-12 sm:px-6">
        <PageHeader
          eyebrow="New analysis"
          title="Launch"
          description="Spin up the full multi-agent pipeline — analysts, research debate, trader, risk team, portfolio manager."
        />

        {/* Info banner spans the full container width — matches the
         * full-width content rhythm of /history rows and /portfolio cards. */}
        <div className="mb-4 flex items-start gap-3 rounded-xl border border-info/20 bg-info/[0.04] p-4 text-sm backdrop-blur-sm">
          <Info className="mt-0.5 h-4 w-4 flex-shrink-0 text-info" aria-hidden />
          <p className="leading-relaxed text-fg-muted">
            The worker uses LLM provider credentials configured on the server. Per-user keys
            land in a future release.
          </p>
        </div>

        <LaunchForm />
      </main>
    </>
  );
}
