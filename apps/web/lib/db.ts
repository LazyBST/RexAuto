import postgres from "postgres";

// One pool per server instance. `prepare: false` keeps it compatible with Supabase's pooled connection strings.
// Locally, DATABASE_URL may be unset and the standard PGHOST / PGDATABASE / PGUSER variables are used instead.
// Timeouts make a bad host or an unreachable database fail with a message instead of hanging the request.
const g = globalThis as unknown as { __sql?: postgres.Sql };
const opts = {
  // Few connections per instance: Supabase's free pooler allows ~15 in total across ALL serverless instances, and idle ones
  // held by frozen instances are what exhaust it. Close idle connections fast and recycle them.
  max: Number(process.env.DB_POOL_MAX ?? 1), prepare: false, idle_timeout: 4, max_lifetime: 300, connect_timeout: 8,
  connection: { statement_timeout: 15000 },
};
const url = process.env.DATABASE_URL;
const remote = !!url && !/localhost|127\.0\.0\.1/.test(url);

export const sql: postgres.Sql =
  g.__sql ?? (g.__sql = url ? postgres(url, { ...opts, ssl: remote ? "require" : false }) : postgres(opts));

// Retry once when the pooler is momentarily out of connections (Postgres code XX000 / 53300 / connection errors).
const TRANSIENT = /^(XX000|53300|57P03|08\w+|EMAX\w*)$/;
export async function withRetry<T>(fn: () => Promise<T>): Promise<T> {
  try { return await fn(); }
  catch (e: any) {
    const code = String(e?.code ?? "");
    if (!TRANSIENT.test(code) && !/max clients|too many (clients|connections)|EMAX/i.test(String(e?.message ?? ""))) throw e;
    await new Promise((r) => setTimeout(r, 250 + Math.random() * 250));
    return await fn();
  }
}
