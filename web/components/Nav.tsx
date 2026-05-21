"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Bookmark, History, PlayCircle, PieChart } from "lucide-react";
import { useSession, signOut } from "next-auth/react";
import { cn } from "@/lib/cn";
import RunsBadge from "@/components/RunsBadge";

const NAV_ITEMS = [
  { href: "/history", label: "History", icon: History },
  { href: "/live", label: "Live", icon: Activity },
  { href: "/launch", label: "Launch", icon: PlayCircle },
  { href: "/portfolio", label: "Portfolio", icon: PieChart },
  { href: "/watchlist", label: "Watchlist", icon: Bookmark },
];

export default function Nav() {
  const pathname = usePathname();
  const { data: session } = useSession();
  const githubId = (session?.user as { githubId?: string } | undefined)?.githubId;

  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-bg/70 backdrop-blur-xl">
      <nav className="mx-auto flex h-14 max-w-7xl items-center gap-2 px-4 sm:px-6">
        <Link
          href="/history"
          className="group mr-2 flex items-center gap-2.5 text-fg transition-opacity hover:opacity-90"
        >
          {/* Axiara slash-mark — three angled bars, brand-red weighted */}
          <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" aria-hidden>
            <path d="M7 4 L4 20" stroke="rgb(var(--brand))" strokeWidth="2.5" strokeLinecap="round" />
            <path d="M14 4 L11 20" stroke="rgb(var(--brand))" strokeWidth="2.5" strokeLinecap="round" />
            <path d="M21 4 L18 20" stroke="rgb(var(--fg))" strokeWidth="2.5" strokeLinecap="round" opacity="0.3" />
          </svg>
          <span className="hidden text-[13px] font-semibold uppercase tracking-[0.14em] sm:inline">
            Trading<span className="text-fg-muted">Agents</span>
          </span>
        </Link>

        <div className="ml-2 flex flex-1 items-center gap-0.5">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium transition-colors",
                  active ? "text-fg" : "text-fg-muted hover:text-fg"
                )}
              >
                <Icon className="h-[14px] w-[14px]" aria-hidden />
                <span className="hidden md:inline">{label}</span>
                {active && (
                  <span
                    className="absolute inset-x-2 -bottom-[14px] h-px bg-brand"
                    aria-hidden
                  />
                )}
              </Link>
            );
          })}
        </div>

        {githubId && (
          <div className="flex items-center gap-3 text-[12px]">
            <RunsBadge />
            <span className="hidden text-fg-subtle sm:inline">
              <span className="text-fg-subtle">gh:</span>
              <span className="font-mono text-fg-muted">{githubId}</span>
            </span>
            <button
              type="button"
              onClick={() => signOut({ callbackUrl: "/" })}
              className="text-fg-subtle transition-colors hover:text-fg"
            >
              Sign out
            </button>
          </div>
        )}
      </nav>
    </header>
  );
}
