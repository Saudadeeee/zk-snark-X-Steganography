const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const { existsSync, mkdtempSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const test = require("node:test");

const circuitsDir = join(__dirname, "..");
const circuits = [
  "payload_verify.circom",
  "fingerprint_verify.circom",
  "detector_receipt.circom",
];

test("all committed Circom circuits compile", () => {
  const outputDir = mkdtempSync(join(tmpdir(), "zkstego-circuits-"));
  try {
    for (const circuit of circuits) {
      execFileSync("circom", [circuit, "--r1cs", "--sym", "-o", outputDir], {
        cwd: circuitsDir,
        stdio: "pipe",
      });
      assert.ok(existsSync(join(outputDir, circuit.replace(".circom", ".r1cs"))));
    }
  } finally {
    rmSync(outputDir, { recursive: true, force: true });
  }
});
