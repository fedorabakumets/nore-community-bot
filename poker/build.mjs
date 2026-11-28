import { copyFile } from "node:fs/promises";
import { build } from "esbuild";

await Promise.all([
  build({
    entryPoints: ["src/client.tsx"],
    outfile: "dist/public/table.js",
    bundle: true,
    format: "esm",
    jsx: "automatic",
    loader: { ".webp": "file" },
    assetNames: "art/[name]-[hash]",
    minify: true,
    legalComments: "linked",
  }),
  build({
    entryPoints: ["src/server.ts"],
    outfile: "dist/engine.mjs",
    platform: "node",
    format: "esm",
    bundle: true,
  }),
]);

await copyFile("LICENSE", "dist/public/LICENSE.txt");
