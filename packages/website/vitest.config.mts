import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

/**
 * Vitest rather than Jest: Next 16 with React 19, so there is no Babel step to
 * configure and TypeScript runs directly. See specs/the-gate-sees-the-website.md.
 *
 * `environment: "node"` is the default and is correct here -- the tests that exist
 * cover API route handlers, which run on the server. A component test would need
 * jsdom, and that is ROADMAP 4.1's problem when it arrives, not a dependency to
 * install now against tests nobody has written.
 */
export default defineConfig({
  resolve: {
    // Mirrors the `@/*` path alias in tsconfig.json. Without it a route importing
    // `@/lib/node-api` resolves under `next build` and not under vitest, so a test
    // would fail for a reason that has nothing to do with the code.
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    // A suite that silently matches zero files is the failure this whole change
    // exists to prevent: the gate would report a green website step having run
    // nothing. Vitest exits non-zero on an empty run with this set.
    passWithNoTests: false,
  },
});
