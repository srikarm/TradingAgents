"use client";

import { useRef, useState } from "react";
import { Bell } from "lucide-react";
import { updateNotificationsAction } from "@/app/actions";
import { enableDisabledReason, thresholdLabel } from "./notification-copy";

type NotifyState = {
  enabled: boolean;
  channel: string;
  threshold: string;
  deliverable: boolean;
};

export default function NotificationSection({
  initial,
  hasEmail,
}: {
  initial: NotifyState;
  hasEmail: boolean;
}) {
  const [state, setState] = useState<NotifyState>(initial);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function onEnable() {
    setError(null);
    try {
      const r = await updateNotificationsAction({ enabled: true, channel: "email" });
      if (!r.ok) throw new Error(r.message);
      setState(r.data);
    } catch (e) {
      setError("Couldn't enable alerts.");
      console.error("notifications enable failed", e);
    }
  }

  async function onDisable() {
    setError(null);
    try {
      const r = await updateNotificationsAction({ enabled: false });
      if (!r.ok) throw new Error(r.message);
      setState(r.data);
    } catch (e) {
      console.error("notifications disable failed", e);
    }
  }

  function onThreshold(next: string) {
    setState((s) => ({ ...s, threshold: next }));
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const r = await updateNotificationsAction({ enabled: true, threshold: next });
        if (!r.ok) throw new Error(r.message);
        setState(r.data);
      } catch (e) {
        console.error("notifications threshold save failed", e);
      }
    }, 800);
  }

  // STATE A — alerts off
  if (!state.enabled) {
    const blocked = enableDisabledReason(hasEmail);
    return (
      <div className="rounded-xl border border-border/60 bg-surface/40 p-4 backdrop-blur-sm">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Bell className="h-4 w-4 text-fg-subtle" aria-hidden />
            <span className="text-sm font-medium text-fg">Signal alerts</span>
          </div>
          <button
            type="button"
            onClick={onEnable}
            disabled={blocked !== null}
            title={blocked ?? undefined}
            className="inline-flex h-8 items-center rounded-lg border border-brand/60 bg-brand/10 px-3 text-xs font-medium text-brand transition-colors hover:bg-brand/15 disabled:opacity-50"
          >
            Enable alerts
          </button>
        </div>
        <p className="mt-1.5 text-xs text-fg-muted">
          {blocked ?? "Get an email when an actionable signal lands — silent on all-HOLD days."}
        </p>
      </div>
    );
  }

  // STATE B — alerts on
  return (
    <div className="rounded-xl border border-brand/40 bg-surface/40 p-4 backdrop-blur-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Bell className="h-4 w-4 text-brand" aria-hidden />
          <span className="text-sm font-medium text-fg">Signal alerts on</span>
        </div>
        <button
          type="button"
          onClick={onDisable}
          className="h-8 rounded-lg border border-border/60 bg-surface/40 px-3 text-xs text-fg-muted hover:text-fg"
        >
          Disable alerts
        </button>
      </div>
      <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex flex-col gap-1 text-xs text-fg-subtle">
          Alert on ratings
          <input
            type="text"
            value={state.threshold}
            onChange={(e) => onThreshold(e.target.value)}
            aria-label="Alert ratings"
            className="h-9 w-40 rounded-lg border border-border/60 bg-surface/40 px-2 font-mono text-sm text-fg focus:border-brand/60 focus:outline-none"
          />
        </label>
      </div>
      <p className="mt-2 text-xs text-fg-muted">
        We&apos;ll email you when a {thresholdLabel(state.threshold)} signal lands. Quiet on days with nothing actionable.
      </p>
      {!state.deliverable && (
        <p className="mt-1 text-xs text-danger" role="alert">
          No email on your account — alerts can&apos;t be delivered until you add one.
        </p>
      )}
      {error && <p className="mt-1 text-xs text-danger" role="alert">{error}</p>}
    </div>
  );
}
