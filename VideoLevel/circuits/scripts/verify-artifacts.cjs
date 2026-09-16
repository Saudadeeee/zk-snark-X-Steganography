"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const circuitDir = path.resolve(__dirname, "..");
const buildDir = path.join(circuitDir, "build");
const manifestPath = path.join(buildDir, "artifacts.json");

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

if (!fs.existsSync(manifestPath)) {
  throw new Error("Missing build/artifacts.json. Run npm run build with PTAU_FILE and ZKEY_ENTROPY first.");
}
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
if (manifest.schema !== "zk-stego-circuit-artifacts-v1") {
  throw new Error("Unsupported artifact manifest schema.");
}
for (const [relativePath, expectedHash] of Object.entries(manifest.files)) {
  const filePath = path.join(buildDir, relativePath);
  if (!fs.existsSync(filePath) || sha256(filePath) !== expectedHash) {
    throw new Error(`Artifact integrity check failed: ${relativePath}`);
  }
}
console.log("Artifact checksums verified.");
