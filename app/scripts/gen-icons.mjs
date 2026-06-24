// Rasterize icon-src.svg into the PNG sizes the PWA manifest + iOS need.
import sharp from "sharp";
import { mkdir, copyFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const src = resolve(root, "icon-src.svg");
const out = resolve(root, "public/icons");

await mkdir(out, { recursive: true });

const targets = [
  ["pwa-192.png", 192],
  ["pwa-512.png", 512],
  ["maskable-512.png", 512], // graphic sits in the central safe zone already
  ["apple-touch-icon.png", 180],
];

for (const [name, size] of targets) {
  await sharp(src).resize(size, size).png().toFile(resolve(out, name));
  console.log("wrote", name);
}
await copyFile(src, resolve(out, "favicon.svg"));
console.log("wrote favicon.svg");
