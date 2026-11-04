import { sql } from "@/lib/db";

export const dynamic = "force-dynamic";

// Visit /api/health after a deploy: shows whether the database is reachable and why not (no secrets in the output).
export async function GET() {
  const url = process.env.DATABASE_URL ?? "";
  let host = "", port = "", user = "";
  try { const u = new URL(url); host = u.hostname; port = u.port; user = u.username.replace(/\..*/, ".<ref>"); } catch {}
  const t = Date.now();
  try {
    const r = await sql.unsafe("select count(*)::int n from products where status = 'published'");
    return Response.json({ ok: true, products: r[0].n, ms: Date.now() - t, host, port, user });
  } catch (e: any) {
    return Response.json({ ok: false, error: String(e?.code ?? e?.message ?? e).slice(0, 160), ms: Date.now() - t, host, port, user }, { status: 503 });
  }
}
