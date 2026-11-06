import { sql, dbInfo, withRetry } from "@/lib/db";

export const dynamic = "force-dynamic";

// Visit /api/health after a deploy: shows whether the database is reachable and how the pool is set up (no secrets in the output).
export async function GET() {
  let user = "";
  try { user = new URL(process.env.DATABASE_URL ?? "").username.replace(/\..*/, ".<ref>"); } catch {}
  const info = { ...dbInfo, user };
  const t = Date.now();
  try {
    const r = await withRetry(() => sql.unsafe("select count(*)::int n from products where status = 'published'"));
    return Response.json({ ok: true, products: r[0].n, ms: Date.now() - t, ...info });
  } catch (e: any) {
    return Response.json({ ok: false, error: String(e?.code ?? e?.message ?? e).slice(0, 160), ms: Date.now() - t, ...info }, { status: 503 });
  }
}
