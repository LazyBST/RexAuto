import { createHash } from "node:crypto";
import { sql } from "@/lib/db";
import { limited } from "@/lib/limit";

export const dynamic = "force-dynamic";

const BOT = /bot|crawl|spider|slurp|headless|preview|monitor|uptime|curl|wget|python|node-fetch|axios|lighthouse/i;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SID = /^[A-Za-z0-9-]{8,64}$/;
const FILTER_KEYS = ["brand", "make", "segment", "category", "min_price", "max_price"];
const str = (v: unknown, max: number) => (typeof v === "string" ? v.slice(0, max) : "");

// Fire-and-forget usage events from the app: one "search" when a search settles, one "view" when a product is opened.
// Always answers 204 (even for ignored/invalid events) so tracking can never get in the way of the app.
export async function POST(req: Request) {
  const rl = limited(req);
  if (rl) return new Response(null, { status: 204 });
  const ua = req.headers.get("user-agent") ?? "";
  if (!ua || BOT.test(ua)) return new Response(null, { status: 204 });
  let b: any;
  try { b = await req.json(); } catch { return new Response(null, { status: 204 }); }
  const sid = SID.test(str(b?.sid, 80)) ? b.sid : null;
  const ip = (req.headers.get("x-forwarded-for")?.split(",")[0] ?? req.headers.get("x-real-ip") ?? "unknown").trim();
  const ipHash = createHash("sha256").update(ip + (process.env.VISITOR_SALT ?? "rex-auto")).digest("hex");
  try {
    if (b?.t === "search") {
      const query = str(b.q, 200).trim();
      const filters: Record<string, string> = {};
      for (const k of FILTER_KEYS) { const v = str(b.f?.[k], 80); if (v) filters[k] = v; }
      if (!query && !Object.keys(filters).length) return new Response(null, { status: 204 });
      const top = (Array.isArray(b.top) ? b.top : []).filter((x: unknown) => typeof x === "string" && UUID.test(x)).slice(0, 10);
      const num = (v: unknown) => (Number.isFinite(Number(v)) ? Math.max(0, Math.min(1e7, Math.round(Number(v)))) : null);
      await sql.unsafe(
        `insert into search_events (sid, ip_hash, query, query_norm, filters, total, ms, corrected, top_ids)
         values ($1::text, $2::text, $3::text, $4::text, $5::jsonb, $6::int, $7::int, $8::boolean, $9::uuid[])`,
        [sid, ipHash, query, query.toLowerCase().replace(/\s+/g, " "), filters, num(b.total), num(b.ms), !!b.corrected, `{${top.join(",")}}`],
      );
    } else if (b?.t === "view") {
      const id = str(b.id, 40);
      if (!UUID.test(id)) return new Response(null, { status: 204 });
      const source = ["list", "related", "link"].includes(b.src) ? b.src : "list";
      await sql.unsafe(
        `insert into product_views (sid, ip_hash, product_id, source, query) values ($1::text, $2::text, $3::uuid, $4::text, $5::text)`,
        [sid, ipHash, id, source, str(b.q, 200).trim() || null],
      );
    }
  } catch (e: any) {
    console.error("track failed", e?.code ?? e?.message);
  }
  return new Response(null, { status: 204 });
}
