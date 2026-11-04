import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Local development only: photos that the Python app stored on disk are served under /img there.
  async rewrites() {
    return process.env.IMG_PROXY ? [{ source: "/img/:path*", destination: `${process.env.IMG_PROXY}/img/:path*` }] : [];
  },
  images: { unoptimized: true },
};
export default nextConfig;
