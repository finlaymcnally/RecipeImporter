import eslint from "@eslint/js";
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

export default defineConfig(
  {
    ignores: [
      "node_modules/**",
      "dist/**",
      "build/**",
      "out/**",
      "coverage/**",
      ".venv/**",
      "**/.venv/**",
    ],
  },
  eslint.configs.recommended,
  tseslint.configs.recommended,
);
