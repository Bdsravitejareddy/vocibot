import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const compat = new FlatCompat({ baseDirectory: __dirname });

const config = [{ ignores: [".next/**", "tmp/vocibot-next-build/**", "dist/**", "build/**", "out/**", "node_modules/**", ".venv/**", ".venv-local/**", "next-env.d.ts", "test-results/**", "playwright-report/**", "desktop/**/*.cjs"] }, ...compat.extends("next/core-web-vitals", "next/typescript")];
export default config;
