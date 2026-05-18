import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

export default function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-border/60 bg-surface/40 px-6 py-20 text-center animate-fade-in">
      {/* Subtle inner glow — gives the empty card depth without being loud */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-brand/[0.04] to-transparent"
        aria-hidden
      />
      <div className="relative flex flex-col items-center">
        <div className="mb-5 grid h-12 w-12 place-items-center rounded-xl border border-border bg-bg/80 text-fg-muted">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
        <h2 className="text-base font-semibold tracking-tight text-fg">{title}</h2>
        <p className="mt-1.5 max-w-md text-sm leading-relaxed text-fg-muted">
          {description}
        </p>
        {action && <div className="mt-6">{action}</div>}
      </div>
    </div>
  );
}
