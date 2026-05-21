import { SignJWT } from "jose";
import { auth } from "@/lib/auth";
import type {
  PortfolioCurveOut,
  PortfolioSummaryOut,
  RunCreate,
  RunDetailOut,
  RunListOut,
  RunTailOut,
  TickerDetailOut,
  UserOut,
  WatchlistItemOut,
} from "@/lib/types";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function bearer(): Promise<string> {
  const session = await auth();
  if (!session?.user) throw new ApiError(401, null, "unauthenticated");
  const sub = (session.user as { githubId?: string }).githubId;
  if (!sub) throw new ApiError(401, null, "session missing githubId");
  const secret = new TextEncoder().encode(process.env.NEXTAUTH_SECRET!);
  const token = await new SignJWT({ email: session.user.email ?? null })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(sub)
    .setIssuedAt()
    .setExpirationTime("7d")
    .sign(secret);
  return `Bearer ${token}`;
}

async function parseBody(res: Response): Promise<unknown> {
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) {
    try { return await res.json(); } catch { return null; }
  }
  try { return await res.text(); } catch { return null; }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: await bearer() },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await parseBody(res);
    throw new ApiError(res.status, body, `api ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      Authorization: await bearer(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const respBody = await parseBody(res);
    throw new ApiError(res.status, respBody, `api ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: {
      Authorization: await bearer(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const respBody = await parseBody(res);
    throw new ApiError(res.status, respBody, `api ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function del(path: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: { Authorization: await bearer() },
    cache: "no-store",
  });
  if (!res.ok) {
    const respBody = await parseBody(res);
    throw new ApiError(res.status, respBody, `api ${path} failed: ${res.status}`);
  }
}

export const api = {
  me: () => get<UserOut>("/me"),
  listRuns: (ticker?: string) =>
    get<RunListOut>(ticker ? `/runs?ticker=${encodeURIComponent(ticker)}` : "/runs"),
  getRun: (id: string) => get<RunDetailOut>(`/runs/${id}`),
  createRun: (body: RunCreate) => post<{ run_id: string }>("/runs", body),
  tailRun: (id: string, since: number) =>
    get<RunTailOut>(`/runs/${id}/tail?since=${since}`),
  countActiveRuns: () =>
    get<{ count: number }>("/runs/active/count").then((d) => d.count),
  listWatchlist: () => get<WatchlistItemOut[]>("/watchlist"),
  addToWatchlist: (ticker: string, notes?: string | null) =>
    post<WatchlistItemOut>("/watchlist", { ticker, notes: notes ?? null }),
  updateWatchlistNotes: (ticker: string, notes: string | null) =>
    patch<WatchlistItemOut>(`/watchlist/${encodeURIComponent(ticker)}`, { notes }),
  removeFromWatchlist: (ticker: string) =>
    del(`/watchlist/${encodeURIComponent(ticker)}`),
  portfolioSummary: () => get<PortfolioSummaryOut>("/portfolio/summary"),
  portfolioCurve: () => get<PortfolioCurveOut>("/portfolio/curve"),
  portfolioTicker: (ticker: string, interval?: "1d" | "1h") => {
    const path = `/portfolio/ticker/${encodeURIComponent(ticker)}`;
    return get<TickerDetailOut>(
      interval && interval !== "1d" ? `${path}?interval=${interval}` : path,
    );
  },
};
