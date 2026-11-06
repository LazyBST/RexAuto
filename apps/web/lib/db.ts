import postgres from "postgres";

// ONE shared pool per server instance, built to survive serverless (Vercel) and a small Supabase pooler.
//
// Why it is set up this way
//  * Supabase's pooler (Supavisor) has two modes. SESSION mode (port 5432) pins one real database connection to every client
//    connection for as long as the client stays connected. Serverless instances freeze without closing their sockets, so those
//    pinned connections pile up and the pool (~15 on the free plan) runs dry -> every request fails with XX000.
//    TRANSACTION mode (port 6543) hands a real connection out per query and takes it back, so idle/frozen clients cost nothing.
//    => for *.pooler.supabase.com we always use transaction mode, even if DATABASE_URL says 5432 (set DB_POOL_MODE=session to opt out).
//  * Transaction mode breaks if postgres.js pipelines several queries on one connection (they hang), so pipelining is off
//    (`max_pipeline: 1`) and parallel queries simply use separate pooled connections or queue.
//  * `prepare: false` because transaction mode has no session-level prepared statements.
//  * Timeouts make a bad host or unreachable database fail with a message instead of hanging the request.
// Locally, DATABASE_URL may be unset and the standard PGHOST / PGDATABASE / PGUSER variables are used instead.

type Mode = "transaction" | "session" | "direct" | "env";
const g = globalThis as unknown as { __sql?: postgres.Sql; __dbinfo?: DbInfo };
export type DbInfo = { mode: Mode; host: string; port: string; max: number };

function resolve(raw: string | undefined): { url: string | undefined; mode: Mode; host: string; port: string } {
  if (!raw) return { url: undefined, mode: "env", host: process.env.PGHOST ?? "", port: process.env.PGPORT ?? "" };
  let u: URL;
  try { u = new URL(raw); } catch { return { url: raw, mode: "direct", host: "", port: "" }; }
  const pooler = /\.pooler\.supabase\.com$/i.test(u.hostname);
  if (pooler && process.env.DB_POOL_MODE !== "session") {
    if (u.port !== "6543") u.port = "6543";
    return { url: u.toString(), mode: "transaction", host: u.hostname, port: u.port };
  }
  return { url: raw, mode: pooler ? "session" : "direct", host: u.hostname, port: u.port || "5432" };
}

const r = resolve(process.env.DATABASE_URL);
const local = !r.url || /localhost|127\.0\.0\.1/.test(r.url);
// transaction mode: many cheap client connections are fine; session/direct: keep it tiny so sleeping instances hold almost nothing
const defaultMax = r.mode === "transaction" ? 4 : local ? 5 : r.mode === "session" ? 1 : 3;
const max = Math.max(1, Number(process.env.DB_POOL_MAX ?? defaultMax) || defaultMax);

const opts = {
  max, prepare: false, max_pipeline: 1,
  idle_timeout: r.mode === "transaction" ? 20 : 4, max_lifetime: 300, connect_timeout: 8,
  connection: { statement_timeout: 15000 },
} as postgres.Options<Record<string, postgres.PostgresType>>;

export const dbInfo: DbInfo = g.__dbinfo ?? (g.__dbinfo = { mode: r.mode, host: r.host, port: r.port, max });
export const sql: postgres.Sql =
  g.__sql ?? (g.__sql = r.url ? postgres(r.url, { ...opts, ssl: local ? false : "require" }) : postgres(opts));

// Every database call that serves a user goes through this: it never hangs (hard time limit) and retries ONCE when the pooler
// was momentarily out of connections or dropped one (Postgres XX000 / 53300 / 57P01 / 57P03 / 08xxx, "max clients", resets).
const TRANSIENT = /^(XX000|53300|57P01|57P03|08\w+|EMAX\w*|CONNECTION_\w+|ECONNRESET|EPIPE|ETIMEDOUT|CONNECT_TIMEOUT)$/;
const TRANSIENT_MSG = /max clients|too many (clients|connections)|EMAX|terminating connection|connection (closed|terminated|ended)|ECONNRESET/i;
class DbTimeout extends Error { code = "DB_TIMEOUT"; }

export async function withRetry<T>(fn: () => Promise<T>, limitMs = 9000): Promise<T> {
  const once = () => {
    let t: ReturnType<typeof setTimeout>;
    return Promise.race([fn(), new Promise<never>((_, rej) => { t = setTimeout(() => rej(new DbTimeout("database timed out")), limitMs); })])
      .finally(() => clearTimeout(t));
  };
  try { return await once(); }
  catch (e: any) {
    const code = String(e?.code ?? "");
    if (code === "DB_TIMEOUT" || (!TRANSIENT.test(code) && !TRANSIENT_MSG.test(String(e?.message ?? "")))) throw e;
    await new Promise((res) => setTimeout(res, 200 + Math.random() * 300));
    return await once();
  }
}
