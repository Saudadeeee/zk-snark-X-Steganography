"use strict";

const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");

const circuitDir = path.resolve(__dirname, "..");

test("package scripts resolve to committed files", () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(circuitDir, "package.json"), "utf8"));
  assert.match(pkg.scripts.build, /scripts\/build-circuits\.cjs/);
  assert.equal(fs.existsSync(path.join(circuitDir, "scripts", "build-circuits.cjs")), true);
  assert.equal(fs.existsSync(path.join(circuitDir, "scripts", "verify-artifacts.cjs")), true);
});
