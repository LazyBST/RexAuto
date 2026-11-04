export async function GET() {
  return Response.json({ name: process.env.SITE_NAME ?? "Parts Catalogue", whatsapp: process.env.WHATSAPP_NUMBER ?? "919999999999" });
}
