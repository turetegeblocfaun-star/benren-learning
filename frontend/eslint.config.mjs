import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // Client pages intentionally fetch server data once mounted. Their async
      // loaders own the loading/error transitions and cannot form render loops.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  globalIgnores([".next/**", "coverage/**", "next-env.d.ts", "public/mockServiceWorker.js"]),
]);
