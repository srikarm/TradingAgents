"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Pencil, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { WatchlistItemOut } from "@/lib/types";
import { cn } from "@/lib/cn";

export default function WatchlistTable({
  initialItems,
}: {
  initialItems: WatchlistItemOut[];
}) {
  const router = useRouter();
  const [items, setItems] = useState(initialItems);
  const [editing, setEditing] = useState<string | null>(null); // ticker
  const [editNotes, setEditNotes] = useState("");
  const [removeTarget, setRemoveTarget] = useState<string | null>(null); // ticker
  const dialogRef = useRef<HTMLDialogElement>(null);

  // Sync local state when server-provided items change (router.refresh()).
  useEffect(() => {
    setItems(initialItems);
  }, [initialItems]);

  // Open the <dialog> when removeTarget is set.
  useEffect(() => {
    if (removeTarget !== null && dialogRef.current) {
      dialogRef.current.showModal();
    }
  }, [removeTarget]);

  async function saveNotes(ticker: string) {
    const next = editNotes.trim() || null;
    try {
      await api.updateWatchlistNotes(ticker, next);
      setItems((prev) =>
        prev.map((i) => (i.ticker === ticker ? { ...i, notes: next } : i)),
      );
    } catch (e) {
      console.error("update notes failed", e);
    } finally {
      setEditing(null);
      setEditNotes("");
    }
  }

  async function confirmRemove() {
    if (!removeTarget) return;
    const ticker = removeTarget;
    setRemoveTarget(null);
    dialogRef.current?.close();
    try {
      await api.removeFromWatchlist(ticker);
      setItems((prev) => prev.filter((i) => i.ticker !== ticker));
    } catch (e) {
      console.error("remove failed", e);
      router.refresh(); // Reconcile.
    }
  }

  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-border/60 bg-surface/40 px-4 py-10 text-center text-sm text-fg-muted backdrop-blur-sm">
        Add a ticker above to start watching.
      </div>
    );
  }

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-border/60 bg-surface/40 backdrop-blur-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/40 text-left">
              <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
                Ticker
              </th>
              <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
                Notes
              </th>
              <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
                Added
              </th>
              <th className="w-24 px-4 py-3" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.id}
                className="border-b border-border/30 transition-colors last:border-0 hover:bg-surface/60"
              >
                <td className="px-4 py-2.5 font-mono">
                  <Link
                    href={`/portfolio/${encodeURIComponent(item.ticker)}`}
                    className="text-fg hover:text-brand"
                  >
                    {item.ticker}
                  </Link>
                </td>
                <td className="px-4 py-2.5 text-fg-muted">
                  {editing === item.ticker ? (
                    <textarea
                      autoFocus
                      value={editNotes}
                      onChange={(e) => setEditNotes(e.target.value)}
                      onBlur={() => saveNotes(item.ticker)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          saveNotes(item.ticker);
                        } else if (e.key === "Escape") {
                          setEditing(null);
                          setEditNotes("");
                        }
                      }}
                      maxLength={500}
                      rows={2}
                      className="w-full rounded border border-border bg-surface/60 px-2 py-1 text-sm text-fg focus:border-brand/60 focus:outline-none"
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setEditing(item.ticker);
                        setEditNotes(item.notes ?? "");
                      }}
                      className="group flex w-full items-start gap-2 text-left hover:text-fg"
                    >
                      <span className={cn(item.notes ? "" : "italic text-fg-subtle")}>
                        {item.notes || "Click to add notes"}
                      </span>
                      <Pencil className="h-3 w-3 flex-shrink-0 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
                    </button>
                  )}
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-fg-subtle">
                  {new Date(item.added_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-2.5">
                  <button
                    type="button"
                    onClick={() => setRemoveTarget(item.ticker)}
                    aria-label={`Remove ${item.ticker} from watchlist`}
                    className="inline-flex h-7 w-7 items-center justify-center rounded text-fg-subtle transition-colors hover:bg-danger/10 hover:text-danger"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <dialog
        ref={dialogRef}
        onClose={() => setRemoveTarget(null)}
        className="rounded-xl border border-border/60 bg-surface p-6 backdrop:bg-black/60 backdrop-blur-sm text-fg"
      >
        <h3 className="mb-2 text-sm font-semibold">Remove from watchlist?</h3>
        <p className="mb-4 text-sm text-fg-muted">
          Remove <span className="font-mono">{removeTarget}</span> from your watchlist?
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => {
              dialogRef.current?.close();
              setRemoveTarget(null);
            }}
            className="rounded-lg border border-border/60 bg-surface/40 px-3 py-1.5 text-sm text-fg-muted hover:text-fg"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={confirmRemove}
            className="rounded-lg border border-danger/60 bg-danger/10 px-3 py-1.5 text-sm text-danger hover:bg-danger/15"
          >
            Remove
          </button>
        </div>
      </dialog>
    </>
  );
}
