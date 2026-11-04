// Per-visitor request limit. In-memory, so it is per server instance: a cheap first line of defence, not a firewall.
// Add Vercel's WAF / rate-limit rule for real protection.
const hits = new Map<string, number[]>();
const PER_MINUTE = Number(process.env.RATE_LIMIT_PER_MINUTE ?? 90);

export function limited(req: Request): Response | null {
  const ip = (req.headers.get("x-forwarded-for") ?? "local").split(",")[0].trim();
  const now = Date.now();
  const q = (hits.get(ip) ?? []).filter((t) => now - t < 60_000);
  if (q.length >= PER_MINUTE) return Response.json({ detail: "too many requests" }, { status: 429, headers: { "Retry-After": "30" } });
  q.push(now);
  hits.set(ip, q);
  if (hits.size > 5000) for (const [k, v] of hits) if (!v.length || now - v[v.length - 1] > 60_000) hits.delete(k);
  return null;
}
