import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  output: "standalone",
  // Pin the project root: a stray package-lock.json in a parent folder (one
  // appeared in the home folder) made Next nest the standalone server one
  // level deeper, and the packaged app failed to start.
  outputFileTracingRoot: path.join(__dirname),
};

export default nextConfig;
