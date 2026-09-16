/*
 * Copies the bundled fonts the standalone export needs into the backend.
 *
 * The export is built server-side and has to carry its fonts inside the file
 * it produces, base64 in a <style> block, because the whole point of that file
 * is that it works on a laptop with no connection to this platform. The backend
 * and the frontend are separate images, so the backend cannot reach into the
 * frontend's node_modules at run time and needs its own copy.
 *
 * Only latin and latin-ext are copied. Everything embedded is paid for in full
 * in every exported file - unlike the app, where the browser fetches one subset
 * on demand - and latin-ext is where the macrons Fijian needs live. A board in
 * a script outside those two exports with its text in the fallback face, which
 * is the right trade against putting a megabyte of Cyrillic in every file.
 *
 * Run `npm run fonts:sync` in frontend/ after changing the font list in
 * src/lib/fonts.ts. `test_export_fonts.py` fails if this was not run.
 */

import { createHash } from "node:crypto";
import { mkdirSync, copyFileSync, writeFileSync, readFileSync, rmSync, existsSync, unlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "../frontend/node_modules/esbuild/lib/main.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const MODULES = join(ROOT, "frontend", "node_modules");
const OUT = join(ROOT, "backend", "app", "services", "export_assets", "fonts");

/*
 * Each entry names the family exactly as its @font-face declares it, because
 * that string is what the export matches a dashboard's font stack against.
 *
 * `weight` is the range a variable file covers; a static face gets its single
 * weight. Both go straight into the generated @font-face.
 */
const FILES = [
  {
    family: "Inter Variable",
    pkg: "@fontsource-variable/inter",
    weight: "100 900",
    files: ["inter-latin-wght-normal.woff2", "inter-latin-ext-wght-normal.woff2"],
  },
  {
    family: "Source Sans 3 Variable",
    pkg: "@fontsource-variable/source-sans-3",
    weight: "200 900",
    files: [
      "source-sans-3-latin-wght-normal.woff2",
      "source-sans-3-latin-ext-wght-normal.woff2",
    ],
  },
  {
    family: "IBM Plex Sans Variable",
    pkg: "@fontsource-variable/ibm-plex-sans",
    weight: "100 700",
    files: [
      "ibm-plex-sans-latin-wght-normal.woff2",
      "ibm-plex-sans-latin-ext-wght-normal.woff2",
    ],
  },
  {
    family: "Space Grotesk Variable",
    pkg: "@fontsource-variable/space-grotesk",
    weight: "300 700",
    files: [
      "space-grotesk-latin-wght-normal.woff2",
      "space-grotesk-latin-ext-wght-normal.woff2",
    ],
  },
  {
    family: "Source Serif 4 Variable",
    pkg: "@fontsource-variable/source-serif-4",
    weight: "200 900",
    files: [
      "source-serif-4-latin-wght-normal.woff2",
      "source-serif-4-latin-ext-wght-normal.woff2",
    ],
  },
  {
    family: "IBM Plex Serif",
    pkg: "@fontsource/ibm-plex-serif",
    weight: "400",
    files: ["ibm-plex-serif-latin-400-normal.woff2"],
  },
  {
    family: "IBM Plex Serif",
    pkg: "@fontsource/ibm-plex-serif",
    weight: "600",
    files: ["ibm-plex-serif-latin-600-normal.woff2"],
  },
  {
    family: "JetBrains Mono Variable",
    pkg: "@fontsource-variable/jetbrains-mono",
    weight: "100 800",
    files: [
      "jetbrains-mono-latin-wght-normal.woff2",
      "jetbrains-mono-latin-ext-wght-normal.woff2",
    ],
  },
];

if (existsSync(OUT)) rmSync(OUT, { recursive: true });
mkdirSync(OUT, { recursive: true });

const manifest = [];
let bytes = 0;

for (const font of FILES) {
  for (const file of font.files) {
    const from = join(MODULES, font.pkg, "files", file);
    if (!existsSync(from)) {
      console.error(`missing: ${from}\nRun npm install in frontend/ first.`);
      process.exit(1);
    }
    copyFileSync(from, join(OUT, file));
    const data = readFileSync(from);
    bytes += data.length;
    manifest.push({
      family: font.family,
      weight: font.weight,
      file,
      sha256: createHash("sha256").update(data).digest("hex"),
      bytes: data.length,
    });
  }
}

writeFileSync(join(OUT, "fonts.json"), `${JSON.stringify(manifest, null, 2)}\n`);

/*
 * The catalogue itself, so the backend can turn a stored font id into a stack.
 *
 * A dashboard title stores an id ("source-serif"); a widget stores the stack.
 * The export has to resolve the first, and the mapping lives in TypeScript. It
 * is compiled and imported rather than read with a regular expression, because
 * a regular expression over source is a thing that works until someone adds a
 * line break.
 */
const compiled = join(OUT, ".catalogue.mjs");
await build({
  entryPoints: [join(ROOT, "frontend", "src", "lib", "fonts.ts")],
  outfile: compiled,
  bundle: true,
  format: "esm",
  platform: "neutral",
  logLevel: "error",
});
const { FONTS } = await import(pathToFileURL(compiled).href);
unlinkSync(compiled);

writeFileSync(
  join(OUT, "catalogue.json"),
  `${JSON.stringify(
    FONTS.map(({ id, label, stack, kind, family }) => ({ id, label, stack, kind, family })),
    null,
    2,
  )}\n`,
);
console.log(
  `export fonts: ${manifest.length} file(s), ${(bytes / 1024).toFixed(0)} KB, ` +
    `${new Set(FILES.map((f) => f.family)).size} bundled families, ` +
    `${FONTS.length} catalogue entries`,
);
