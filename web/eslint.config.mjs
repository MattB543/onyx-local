import { defineConfig, globalIgnores } from "eslint/config";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import tseslint from "typescript-eslint";
import prettierConfig from "eslint-config-prettier";
import importX from "eslint-plugin-import-x";
import unusedImports from "eslint-plugin-unused-imports";

export default defineConfig([
  // Global ignores
  globalIgnores([".next/", "node_modules/", "out/", "lib/opal/"]),

  // Next.js core-web-vitals (includes react, react-hooks, jsx-a11y,
  // @next/next, @typescript-eslint base, and import plugins)
  ...nextCoreWebVitals,

  // TypeScript strict & stylistic rule sets (rules only — the base plugin
  // and parser are already registered by eslint-config-next above)
  tseslint.configs.strict[2], // typescript-eslint/strict rules
  tseslint.configs.stylistic[2], // typescript-eslint/stylistic rules

  // eslint-plugin-import-x (flat config)
  importX.flatConfigs.recommended,
  importX.flatConfigs.typescript,

  // Custom rules & plugin overrides
  {
    plugins: {
      "unused-imports": unusedImports,
    },
    rules: {
      // ── Unused imports (auto-fixable) ────────────────────────────
      "no-unused-vars": "off",
      "@typescript-eslint/no-unused-vars": "off",
      "unused-imports/no-unused-imports": "error",
      "unused-imports/no-unused-vars": [
        "error",
        {
          vars: "all",
          varsIgnorePattern: "^_",
          args: "after-used",
          argsIgnorePattern: "^_",
          caughtErrors: "all",
          caughtErrorsIgnorePattern: "^_",
          ignoreRestSiblings: true,
        },
      ],

      // ── Import ordering ──────────────────────────────────────────
      "import-x/order": [
        "error",
        {
          groups: [
            "builtin",
            "external",
            "internal",
            "parent",
            "sibling",
            "index",
          ],
          pathGroups: [
            { pattern: "@/**", group: "internal", position: "before" },
          ],
          "newlines-between": "always",
          alphabetize: { order: "asc", caseInsensitive: true },
        },
      ],
      "import-x/no-duplicates": "error",

      // ── React hooks ──────────────────────────────────────────────
      "react-hooks/exhaustive-deps": "warn",

      // ── TypeScript overrides ─────────────────────────────────────
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-non-null-assertion": "warn",
      "@typescript-eslint/no-empty-function": [
        "error",
        { allow: ["arrowFunctions"] },
      ],
      "@typescript-eslint/consistent-type-definitions": "off",

      // ── Next.js ──────────────────────────────────────────────────
      "@next/next/no-img-element": "off",
    },
  },

  // Prettier — must be last to disable conflicting formatting rules
  prettierConfig,
]);
