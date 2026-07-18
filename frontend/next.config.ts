import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Production Docker image (frontend/Dockerfile) copies only
  // .next/standalone + .next/static + public — standalone output means the
  // runner stage never needs to ship node_modules.
  output: "standalone",
};

export default nextConfig;
