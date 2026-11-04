import { search } from "@/lib/search";
import { limited } from "@/lib/limit";

const MAX_DEPTH = Number(process.env.MAX_RESULT_DEPTH ?? 300);

export async function GET(req: Request) {
  const rl = limited(req);
  if (rl) return rl;
  const u = new URL(req.url).searchParams;
  const q = (u.get("q") ?? "").slice(0, 120);
  const limit = Math.min(Math.max(Number(u.get("limit") ?? 30) || 30, 1), 50);
  const offset = Math.max(Number(u.get("offset") ?? 0) || 0, 0);
  if (offset + limit > MAX_DEPTH) return Response.json({ detail: `results are limited to the first ${MAX_DEPTH}; narrow the search` }, { status: 400 });
  const f = Object.fromEntries(["brand", "make", "segment", "category", "min_price", "max_price"].map((k) => [k, u.get(k) ?? ""]));
  if ((f.min_price && isNaN(Number(f.min_price))) || (f.max_price && isNaN(Number(f.max_price)))) return Response.json({ detail: "bad filter value" }, { status: 400 });
  try {
    return Response.json(await search(q, f, limit, offset));
  } catch (e: any) {
    console.error("search failed", e?.code ?? e?.message);
    return Response.json({ detail: "database unavailable", code: String(e?.code ?? "").slice(0, 40) }, { status: 503 });
  }
}
