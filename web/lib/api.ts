import { auth } from "@/lib/auth";
import { encode } from "next-auth/jwt";
import type { RunDetailOut, RunListOut, UserOut } from "@/lib/types";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

async function bearer(): Promise<string> {
  const session = await auth();
  if (!session?.user) throw new Error("unauthenticated");
  // Re-encode the JWT so FastAPI receives the same HS256-signed token.
  const token = await encode({
    token: {
      sub: (session.user as { githubId?: string }).githubId,
      email: session.user.email ?? null,
    },
    secret: process.env.NEXTAUTH_SECRET!,
    salt: "",
  });
  return `Bearer ${token}`;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: await bearer() },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`api ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => get<UserOut>("/me"),
  listRuns: (ticker?: string) =>
    get<RunListOut>(ticker ? `/runs?ticker=${encodeURIComponent(ticker)}` : "/runs"),
  getRun: (id: string) => get<RunDetailOut>(`/runs/${id}`),
};
