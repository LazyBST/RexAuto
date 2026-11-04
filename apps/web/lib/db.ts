import postgres from "postgres";

// One pool per server instance. `prepare: false` keeps it compatible with Supabase's pooled connection strings.
// Locally, DATABASE_URL may be unset and the standard PGHOST / PGDATABASE / PGUSER variables are used instead.
const g = globalThis as unknown as { __sql?: postgres.Sql };

export const sql: postgres.Sql =
  g.__sql ??
  (g.__sql = process.env.DATABASE_URL
    ? postgres(process.env.DATABASE_URL, { max: 5, prepare: false, idle_timeout: 20 })
    : postgres({ max: 5, prepare: false, idle_timeout: 20 }));
