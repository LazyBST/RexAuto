import { sql } from "@/lib/db";

// Name -> image URL maps for vehicle makes, product brands and categories. Tiny and slow-changing, so it is cached hard.
export async function GET() {
  try {
    const [makes, brands, cats] = await Promise.all([
      sql`select name, logo_url from makes where logo_url is not null`,
      sql`select name, logo_url from brands where logo_url is not null`,
      sql`select name, icon_url from categories where icon_url is not null`,
    ]);
    const body = {
      makes: Object.fromEntries(makes.map((r) => [r.name, r.logo_url])),
      brands: Object.fromEntries(brands.map((r) => [r.name, r.logo_url])),
      categories: Object.fromEntries(cats.map((r) => [r.name, r.icon_url])),
    };
    return Response.json(body, { headers: { "Cache-Control": "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400" } });
  } catch {
    return Response.json({ makes: {}, brands: {}, categories: {} }, { status: 200, headers: { "Cache-Control": "no-store" } });
  }
}
