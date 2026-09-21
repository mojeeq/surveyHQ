/*
 * Copies what the standalone export needs out of the frontend: the drawing
 * libraries, and the chart palette they draw with.
 *
 * The exported file used to fetch ECharts and Leaflet from a CDN. That is a
 * quiet failure rather than a loud one: the page still opens, the tables still
 * add up, and every chart on it has silently become a table of numbers -
 * because the drawing code falls back to a table when `window.echarts` is not
 * there. A survey office on a metered line, a ministry network that blocks
 * jsdelivr, or the laptop taken to the meeting the file was made for, all get
 * that page. So the libraries travel inside the file.
 *
 * The backend and the frontend are separate images, so the backend cannot
 * reach into the frontend's node_modules at run time and needs its own copy -
 * the same reason the bundled fonts are vendored beside these.
 *
 * The palette is here for a different reason. A board carries the name of a
 * chart theme, and the colours that name stands for live in TypeScript beside
 * the validator that scored them. The export was carrying that name and
 * ignoring it, drawing instead from a private list of ten colours that matched
 * no theme the platform has - so a board exported in hues it was never drawn
 * in. Compiling the real table out is what keeps one source of truth, the same
 * way the font catalogue is compiled rather than copied.
 *
 * Run `npm run lib:sync` in frontend/ after changing either dependency or the
 * theme table. `test_export_lib.py` fails if this was not run.
 */

import { createHash } from "node:crypto";
import { mkdirSync, copyFileSync, writeFileSync, readFileSync, rmSync, existsSync, unlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "../frontend/node_modules/esbuild/lib/main.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const MODULES = join(ROOT, "frontend", "node_modules");
const OUT = join(ROOT, "backend", "app", "services", "export_assets", "lib");

/*
 * `as` is the name the backend asks for the file by, so renaming a package
 * upstream does not ripple into Python. `when` says what has to be on the
 * board before the file is worth its kilobytes: `always` for the chart
 * library, which nearly every board needs, and `map` for Leaflet, which only
 * a board carrying a map does.
 */
const FILES = [
  { as: "echarts.js", pkg: "echarts", from: "dist/echarts.min.js", when: "always" },
  { as: "leaflet.js", pkg: "leaflet", from: "dist/leaflet.js", when: "map" },
  { as: "leaflet.css", pkg: "leaflet", from: "dist/leaflet.css", when: "map" },
];

if (existsSync(OUT)) rmSync(OUT, { recursive: true });
mkdirSync(OUT, { recursive: true });

const manifest = [];
let bytes = 0;

for (const entry of FILES) {
  const from = join(MODULES, entry.pkg, entry.from);
  if (!existsSync(from)) {
    console.error(`missing: ${from}\nRun npm install in frontend/ first.`);
    process.exit(1);
  }
  const data = readFileSync(from);
  /*
   * Both of these go into the page as they are, not base64, so a file that
   * happened to contain the end of a script tag would end it early and put the
   * rest of a megabyte of minified JavaScript on the screen as text. Neither
   * does today; this is here so that the day one does is a failed build rather
   * than a broken export.
   */
  const text = data.toString("utf8");
  if (/<\/script/i.test(text) || text.includes("<!--")) {
    console.error(`${entry.as} contains a sequence that cannot be inlined in HTML`);
    process.exit(1);
  }
  copyFileSync(from, join(OUT, entry.as));
  bytes += data.length;
  manifest.push({
    file: entry.as,
    when: entry.when,
    package: entry.pkg,
    version: JSON.parse(readFileSync(join(MODULES, entry.pkg, "package.json"), "utf8")).version,
    sha256: createHash("sha256").update(data).digest("hex"),
    bytes: data.length,
  });
}

writeFileSync(join(OUT, "lib.json"), `${JSON.stringify(manifest, null, 2)}\n`);

/*
 * The chart themes, compiled out rather than read with a regular expression,
 * for the same reason the font catalogue is: an expression over source works
 * until somebody adds a line break.
 */
const compiled = join(OUT, ".themes.mjs");
await build({
  entryPoints: [join(ROOT, "frontend", "src", "lib", "charts.ts")],
  outfile: compiled,
  bundle: true,
  format: "esm",
  platform: "neutral",
  logLevel: "error",
});
const { CHART_THEMES } = await import(pathToFileURL(compiled).href);
unlinkSync(compiled);

const themes = Object.fromEntries(
  Object.entries(CHART_THEMES).map(([id, theme]) => [id, theme.colors]),
);
writeFileSync(join(OUT, "themes.json"), `${JSON.stringify(themes, null, 2)}\n`);

console.log(
  `export libraries: ${manifest.length} file(s), ${(bytes / 1024).toFixed(0)} KB\n` +
    manifest.map((m) => `  ${m.file} ${m.package}@${m.version}`).join("\n") +
    `\nchart themes: ${Object.keys(themes).join(", ")}`,
);
