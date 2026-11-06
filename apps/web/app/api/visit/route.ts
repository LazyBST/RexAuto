import { createHash } from "node:crypto";
import { sql, withRetry } from "@/lib/db";
import { limited } from "@/lib/limit";

export const dynamic = "force-dynamic";

const BOT = /bot|crawl|spider|slurp|headless|preview|monitor|uptime|curl|wget|python|node-fetch|axios|lighthouse/i;

const total = async () => Number((await withRetry(() => sql.unsafe("select total from visit_counter where id = 1")))[0]?.total ?? 0);

// Public counter: the number of times the site has been opened.
export async function GET() {
  try { return Response.json({ total: await total() }); }
  catch { return Response.json({ total: null }, { status: 503 }); }
}

// Called once when the site is opened in a browser tab. Counts one visit and records a salted hash of the IP for unique counting.
export async function POST(req: Request) {
  const rl = limited(req);
  if (rl) return rl;
  const ua = req.headers.get("user-agent") ?? "";
  try {
    if (!ua || BOT.test(ua)) return Response.json({ total: await total(), counted: false });
    const ip = (req.headers.get("x-forwarded-for")?.split(",")[0] ?? req.headers.get("x-real-ip") ?? "unknown").trim();
    const hash = createHash("sha256").update(ip + (process.env.VISITOR_SALT ?? "rex-auto")).digest("hex");
    const r = await withRetry(() => sql.unsafe(
      `with v as (
         insert into visits (ip_hash, is_new_ip, country, user_agent, referrer)
         select $1::text, not exists (select 1 from visits where ip_hash = $1::text), $2::text, $3::text, $4::text
         returning 1)
       update visit_counter set total = total + 1 from v where id = 1 returning total`,
      [hash, req.headers.get("x-vercel-ip-country"), ua.slice(0, 300), (req.headers.get("referer") ?? "").slice(0, 300) || null],
    ));
    return Response.json({ total: Number(r[0].total), counted: true });
  } catch (e: any) {
    console.error("visit failed", e?.code ?? e?.message);
    return Response.json({ total: null }, { status: 503 });
  }
}
