import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ runId: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const { runId } = await params;
  const since = Number(req.nextUrl.searchParams.get("since") ?? 0);
  try {
    const data = await api.tailRun(runId, since);
    return NextResponse.json(data);
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401) {
        return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
      }
      if (e.status === 404) {
        return NextResponse.json({ error: "not_found" }, { status: 404 });
      }
      return NextResponse.json({ error: e.message, body: e.body }, { status: e.status });
    }
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}
