import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const isStaticExport = process.env.NEXT_OUTPUT === "export";

// ESM next.config.ts has no CommonJS __dirname; derive it from import.meta.url.
const projectRoot = path.dirname(fileURLToPath(import.meta.url));
// The npm workspace root is two levels up from apps/web. Turbopack must be
// pointed at the monorepo root (not apps/web), otherwise Next.js may fail to
// infer the workspace root when hoisted deps live at the top-level
// `node_modules/` — causing `Error: Next.js inferred your workspace root...
// We couldn't find the Next.js package`. Keep this set to the monorepo root.
const monorepoRoot = path.resolve(projectRoot, "..", "..");

const nextConfig: NextConfig = {
  allowedDevOrigins: ["*.ngrok-free.dev", "*.ngrok.io"],
  turbopack: {
    root: monorepoRoot,
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
