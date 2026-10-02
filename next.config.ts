import type { NextConfig } from "next";

// Enterprise builds export static files that the VociBot server itself
// serves (one process, one port, same origin for cookies and the audio
// websocket). The original desktop build keeps the standalone Node server.
const staticExport = process.env.VOCIBOT_STATIC_EXPORT === "1";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  ...(staticExport ? { output: "export", trailingSlash: true, images: { unoptimized: true } } : { output: "standalone" }),
};

export default nextConfig;
