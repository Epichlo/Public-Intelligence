import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    // An underscore prefix marks a parameter that is deliberately unread.
    //
    // A test double must mirror the signature of the thing it stands in for: a
    // fake `fetch` takes `(url, init)` it never reads, because the real one does
    // and because typing it is what lets `spy.mock.calls[0][0]` type-check at all.
    // Dropping the parameters would hide the real API and defeat the purpose.
    //
    // This is the same exemption, for the same reason, that
    // `packages/*/pyproject.toml` grants ARG001/ARG002/ARG005 to `tests/**` on the
    // Python side. `--max-warnings=0` is only sustainable if the intentional cases
    // have a way to say so.
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" },
      ],
    },
  },
]);

export default eslintConfig;
