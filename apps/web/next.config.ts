import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const isStaticExport = process.env.NEXT_OUTPUT === "export";

// ESM next.config.ts has no CommonJS __dirname; derive it from import.meta.url.
// We set this as `turbopack.root` so the bundler doesn't misinfer
// `apps/web/src/app` as the project root. Note: even with this set, Turbopack
// 16 currently can't resolve `next/package.json` across pnpm's `.pnpm` store
// symlinks, so `pnpm dev` defaults to the webpack path via --webpack in
// package.json. Use `pnpm dev:turbopack` to opt in (and watch it fail).
const projectRoot = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  allowedDevOrigins: ["*.ngrok-free.dev", "*.ngrok.io"],
  turbopack: {
    root: projectRoot,
  },
  // Static export for Firebase Hosting (set NEXT_OUTPUT=export in CI)
  ...(isStaticExport
    ? { output: "export" }
    : {
        // Dev-only: proxy /api to backend. In production, firebase.json handles routing.
        async rewrites() {
          return [
            {
              source: "/api/:path*",
              // Backend default is 8080 (see apps/api/src/insightxpert_api/config.py::port).
              // NEXT_PUBLIC_API_URL overrides for prod/ops.
              destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080"}/api/:path*`,
            },
          ];
        },
      }),
};

export default nextConfig;
