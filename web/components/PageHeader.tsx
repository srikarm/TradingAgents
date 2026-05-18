import type { ReactNode } from "react";

export default function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-10 flex flex-wrap items-end justify-between gap-6">
      <div>
        {eyebrow && (
          <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.18em] text-brand">
            {eyebrow}
          </div>
        )}
        <h1 className="text-3xl font-semibold tracking-tight text-fg">
          {title}
        </h1>
        {description && (
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-fg-muted">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
