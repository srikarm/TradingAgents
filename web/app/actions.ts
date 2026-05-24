"use server";

// Server Actions that wrap the server-only @/lib/api so CLIENT components can
// trigger backend calls without importing api.ts directly. api.ts uses
// bearer() → auth() → next/headers, which only works in a server request
// scope; calling it from the browser throws "headers() was called outside a
// request scope". These actions run server-side (real request scope), do the
// auth there, and return serializable, discriminated results — so the client
// never touches server-only APIs.

import { api, ApiError } from "@/lib/api";
import type {
  MonitorOut,
  MonitorUpdate,
  NotifyOut,
  NotifyUpdate,
  WatchlistItemOut,
} from "@/lib/types";

export type ActionResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; message: string };

function toFailure(e: unknown): { ok: false; status: number; message: string } {
  // Preserve the upstream HTTP status so callers can branch (e.g. 409/422).
  // Thrown errors don't survive the server-action boundary intact (Next
  // sanitizes them), so we return status explicitly instead of re-throwing.
  if (e instanceof ApiError) {
    const message = typeof e.body === "string" && e.body ? e.body : e.message;
    return { ok: false, status: e.status, message };
  }
  return { ok: false, status: 0, message: e instanceof Error ? e.message : String(e) };
}

async function run<T>(fn: () => Promise<T>): Promise<ActionResult<T>> {
  try {
    return { ok: true, data: await fn() };
  } catch (e) {
    return toFailure(e);
  }
}

export async function updateMonitorAction(
  body: MonitorUpdate,
): Promise<ActionResult<MonitorOut>> {
  return run(() => api.updateMonitor(body));
}

export async function updateNotificationsAction(
  body: NotifyUpdate,
): Promise<ActionResult<NotifyOut>> {
  return run(() => api.updateNotifications(body));
}

export async function addToWatchlistAction(
  ticker: string,
  notes: string | null,
): Promise<ActionResult<WatchlistItemOut>> {
  return run(() => api.addToWatchlist(ticker, notes));
}

export async function updateWatchlistNotesAction(
  ticker: string,
  notes: string | null,
): Promise<ActionResult<WatchlistItemOut>> {
  return run(() => api.updateWatchlistNotes(ticker, notes));
}

export async function removeFromWatchlistAction(
  ticker: string,
): Promise<ActionResult<void>> {
  return run(() => api.removeFromWatchlist(ticker));
}

export async function countActiveRunsAction(): Promise<ActionResult<number>> {
  return run(() => api.countActiveRuns());
}
