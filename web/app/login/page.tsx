// web/app/login/page.tsx
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import SignInForm from "./SignInForm";

export const metadata = {
  title: "Sign in · TradingAgents",
};

// Accepts only relative paths (starts with a single slash).
// Rejects absolute URLs and protocol-relative URLs (//...) which browsers
// treat as cross-origin, preventing open-redirect attacks via callbackUrl.
function isSafeRedirect(url: string | undefined): url is string {
  return !!url && url.startsWith("/") && !url.startsWith("//");
}

interface PageProps {
  searchParams: Promise<{ error?: string; callbackUrl?: string }>;
}

export default async function LoginPage({ searchParams }: PageProps) {
  const session = await auth();
  const { error, callbackUrl } = await searchParams;

  if (session) {
    redirect(isSafeRedirect(callbackUrl) ? callbackUrl : "/history");
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-10">
      <div className="w-full max-w-sm rounded-2xl border border-white/[0.06] bg-surface/55 px-7 py-7 text-center backdrop-blur-sm">
        <div
          className="mx-auto mb-4 flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-brand to-red-dark font-bold text-white shadow-glow"
          aria-hidden="true"
        >
          /
        </div>
        <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-brand/85">
          tradingagents
        </p>
        <h1 className="text-lg font-semibold text-fg-primary">Sign in</h1>
        <p className="mb-5 mt-1.5 text-xs text-fg-muted">
          Continue with your preferred account
        </p>
        <SignInForm callbackUrl={isSafeRedirect(callbackUrl) ? callbackUrl : undefined} error={error} />
      </div>
    </main>
  );
}
