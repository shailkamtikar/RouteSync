// Copies the MapLibre worker into /public so the browser can load it from our own origin.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const target = resolve(root, "public/maplibre");
mkdirSync(target, { recursive: true });
copyFileSync(
  resolve(root, "node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs"),
  resolve(target, "maplibre-gl-worker.mjs"),
);
