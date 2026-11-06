import { product } from "@/lib/search";
import { withRetry } from "@/lib/db";
import { limited } from "@/lib/limit";

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const rl = limited(req);
  if (rl) return rl;
  const { id } = await params;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) return Response.json({ detail: "not found" }, { status: 404 });
  try {
    const p = await withRetry(() => product(id));
    return p ? Response.json(p) : Response.json({ detail: "not found" }, { status: 404 });
  } catch (e: any) {
    // a database problem is not "not found": tell the client to retry instead of caching a wrong answer
    console.error("product failed", e?.code, String(e?.message ?? "").slice(0, 200));
    return Response.json({ detail: "database unavailable", code: String(e?.code ?? "").slice(0, 40) }, { status: 503 });
  }
}
