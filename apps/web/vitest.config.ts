import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: "@", replacement: path.resolve(__dirname, "./src") },
      // The CJS build of react-syntax-highlighter requires the ESM-only
      // `refractor/lib/core.js`, which Node refuses to require() in
      // JSDOM/Vitest. Tests don't exercise SQL highlighting, so swap every
      // path under the package for a thin stub that exports the surface our
      // components touch (Light, a sqlLang shape, hljs styles).
      {
        find: /^react-syntax-highlighter(\/.*)?$/,
        replacement: path.resolve(__dirname, "./test/stubs/react-syntax-highlighter.tsx"),
      },
    ],
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    setupFiles: ["./vitest.setup.ts"],
    server: {
      deps: {
        // react-syntax-highlighter ships CJS that requires ESM-only refractor.
        // Forcing Vite to transform it inline turns the require() into an
        // ESM-friendly import so the chunk-renderer test (which transitively
        // imports SqlChunk) can load.
        inline: [/react-syntax-highlighter/, /refractor/],
      },
    },
  },
});
