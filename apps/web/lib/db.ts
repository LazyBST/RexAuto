import postgres from "postgres";

// One pool per server instance. `prepare: false` keeps it compatible with Supabase's pooled connection strings.
// Locally, DATABASE_URL may be unset and the standard PGHOST / PGDATABASE / PGUSER variables are used instead.
// Timeouts make a bad host or an unreachable database fail with a message instead of hanging the request.
const g = globalThis as unknown as { __sql?: postgres.Sql };
const opts = {
  max: 5, prepare: false, idle_timeout: 20, connect_timeout: 8,
  connection: { statement_timeout: 15000 },
};
const url = process.env.DATABASE_URL;
const remote = !!url && !/localhost|127\.0\.0\.1/.test(url);

export const sql: postgres.Sql =
  g.__sql ?? (g.__sql = url ? postgres(url, { ...opts, ssl: remote ? "require" : false }) : postgres(opts));
