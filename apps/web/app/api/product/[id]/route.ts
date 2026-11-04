import { product } from "@/lib/search";
import { limited } from "@/lib/limit";

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const rl = limited(req);
  if (rl) return rl;
  const { id } = await params;
  const p = await product(id).catch(() => null);
  return p ? Response.json(p) : Response.json({ detail: "not found" }, { status: 404 });
}
