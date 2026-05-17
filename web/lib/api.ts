import { SignJWT } from "jose";
import { auth } from "@/lib/auth";
import type {
  RunCreate,
  RunDetailOut,
  RunListOut,
  RunTailOut,
  UserOut,
} from "@/lib/types";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

async function bearer(): Promise<string> {
  const session = await auth();
  if (!session?.user) throw new Error("unauthenticated");
  const sub = (session.user as { githubId?: string }).githubId;
  if (!sub) throw new Error("session missing githubId");
  const secret = new TextEncoder().encode(process.env.NEXTAUTH_SECRET!);
  const token = await new SignJWT({ email: session.user.email ?? null })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(sub)
    .setIssuedAt()
    .setExpirationTime("7d")
    .sign(secret);
  return `Bearer ${token}`;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: await bearer() },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`api ${path} failed: ${res.status}`);
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
    const detail = await res.text();
    throw new Error(`api ${path} failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => get<UserOut>("/me"),
  listRuns: (ticker?: string) =>
    get<RunListOut>(ticker ? `/runs?ticker=${encodeURIComponent(ticker)}` : "/runs"),
  getRun: (id: string) => get<RunDetailOut>(`/runs/${id}`),
  createRun: (body: RunCreate) => post<{ run_id: string }>("/runs", body),
  tailRun: (id: string, since: number) =>
    get<RunTailOut>(`/runs/${id}/tail?since=${since}`),
};
