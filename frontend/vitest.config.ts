import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// `e2e/` is Playwright's, run by `npm run test:e2e` against a live stack.
// Without this, vitest collects those specs and fails on Playwright's imports.
export default defineConfig({
  test: {
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
