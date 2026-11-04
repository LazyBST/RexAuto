import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Rex Auto", description: "Search commercial-vehicle and car spare parts by part number, vehicle or description." };
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
