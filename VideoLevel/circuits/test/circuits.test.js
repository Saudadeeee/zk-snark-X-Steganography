const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const { existsSync, mkdtempSync, readFileSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const test = require("node:test");

const circuitsDir = join(__dirname, "..");
const circuits = [
  "camera_video.circom",
  "fingerprint_verify.circom",
  "detector_receipt.circom",
];

const outputDir = mkdtempSync(join(tmpdir(), "zkstego-circuits-"));
test.after(() => rmSync(outputDir, { recursive: true, force: true }));

function compile(circuit) {
  execFileSync("circom", [circuit, "--r1cs", "--wasm", "--sym", "-o", outputDir], {
    cwd: circuitsDir,
    stdio: "pipe",
  });
}

async function witnessCalculator(name) {
  const jsDir = join(outputDir, `${name}_js`);
  const builder = require(join(jsDir, "witness_calculator.js"));
  return builder(readFileSync(join(jsDir, `${name}.wasm`)));
}

// Fixed vector shared with src/runtest/test_zk_proof.py: camera secret 1 opened
// along 16 levels whose siblings are 0 and whose path indices are 0, i.e.
// ROOT = Poseidon(...Poseidon(Poseidon(1), 0)..., 0), computed by src/poseidon.py.
const DEPTH = 16;
const ROOT = "13540250208624962443651359021534662279818360331845733678151493660599986427279";

function cameraInput() {
  return {
    secret: "1",
    siblings: Array(DEPTH).fill("0"),
    pathIndices: Array(DEPTH).fill("0"),
    root: ROOT,
    bindingHi: "123",
    bindingLo: "456",
  };
}

function sourceLine(circuit, needle) {
  const lines = readFileSync(join(circuitsDir, circuit), "utf8").split(/\r?\n/);
  const index = lines.findIndex((line) => line.includes(needle));
  assert.ok(index >= 0, `missing "${needle}" in ${circuit}`);
  return index + 1;
}

test("all committed Circom circuits compile", () => {
  for (const circuit of circuits) {
    compile(circuit);
    assert.ok(existsSync(join(outputDir, circuit.replace(".circom", ".r1cs"))));
  }
});

test("camera_video accepts the camera that opens the registry path", async () => {
  const wc = await witnessCalculator("camera_video");
  const witness = await wc.calculateWitness(cameraInput(), true);
  assert.equal(witness[0], 1n);
});

test("camera_video rejects another camera secret", async () => {
  const wc = await witnessCalculator("camera_video");
  const input = { ...cameraInput(), secret: "2" };
  const line = sourceLine("camera_video.circom", "membership.root === root;");
  await assert.rejects(wc.calculateWitness(input, true), new RegExp(`Assert Failed[\\s\\S]*line: ${line}\\b`));
});

test("camera_video rejects a non-boolean path index", async () => {
  const wc = await witnessCalculator("camera_video");
  const input = { ...cameraInput(), pathIndices: ["2", ...Array(DEPTH - 1).fill("0")] };
  const line = sourceLine("camera_video.circom", "pathIndices[i] * (pathIndices[i] - 1) === 0;");
  await assert.rejects(wc.calculateWitness(input, true), new RegExp(`Assert Failed[\\s\\S]*line: ${line}\\b`));
});

test("detector_receipt compares scores above 2^32 correctly", async () => {
  const wc = await witnessCalculator("detector_receipt");
  const max = "65535";
  const score = 4n * 65535n * 65535n; // ~2^34, overflowed the old 32-bit comparator
  const base = { features: [max, max, max, max], weights: [max, max, max, max] };

  // score - threshold ~ 2^34 needs the 35-bit comparator to produce a witness.
  const lowThreshold = await wc.calculateWitness({ ...base, threshold: "1" }, true);
  assert.equal(lowThreshold[1], 1n);

  const accepted = await wc.calculateWitness({ ...base, threshold: String(score) }, true);
  assert.equal(accepted[1], 1n);

  const rejected = await wc.calculateWitness({ ...base, threshold: String(score + 1n) }, true);
  assert.equal(rejected[1], 0n);
});

test("detector_receipt range-checks the public threshold", async () => {
  const wc = await witnessCalculator("detector_receipt");
  const input = {
    features: ["1", "1", "1", "1"],
    weights: ["1", "1", "1", "1"],
    threshold: String(1n << 35n),
  };
  await assert.rejects(wc.calculateWitness(input, true), /Assert Failed/);
});
