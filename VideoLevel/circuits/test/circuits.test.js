const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const { createHash } = require("node:crypto");
const { existsSync, mkdtempSync, readFileSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const test = require("node:test");

const circuitsDir = join(__dirname, "..");
const circuits = [
  "payload_verify.circom",
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

function bytesToBits(bytes) {
  const bits = [];
  for (const byte of bytes) {
    for (let i = 7; i >= 0; i--) bits.push(String((byte >> i) & 1));
  }
  return bits;
}

function payloadInput(payload, secret) {
  const payloadHash = createHash("sha256").update(payload).digest();
  const commitment = createHash("sha256").update(Buffer.concat([payloadHash, secret])).digest();
  return {
    payload_hash: bytesToBits(payloadHash),
    commitment: bytesToBits(commitment),
    payload_length: String(payload.length),
    secret: bytesToBits(secret),
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

test("payload_verify accepts an honest witness", async () => {
  const wc = await witnessCalculator("payload_verify");
  const input = payloadInput(Buffer.from("hello zk stego"), Buffer.alloc(32, 7));
  const witness = await wc.calculateWitness(input, true);
  assert.equal(witness[0], 1n);
});

test("payload_verify rejects non-boolean secret bits", async () => {
  const wc = await witnessCalculator("payload_verify");
  const input = payloadInput(Buffer.from("hello zk stego"), Buffer.alloc(32, 7));
  input.secret[0] = "2";
  const line = sourceLine("payload_verify.circom", "secret[i] * (secret[i] - 1) === 0");
  await assert.rejects(wc.calculateWitness(input, true), new RegExp(`Assert Failed[\\s\\S]*line: ${line}\\b`));
});

test("payload_verify rejects non-boolean payload_hash bits", async () => {
  const wc = await witnessCalculator("payload_verify");
  const input = payloadInput(Buffer.from("hello zk stego"), Buffer.alloc(32, 7));
  input.payload_hash[5] = "3";
  const line = sourceLine("payload_verify.circom", "payload_hash[i] * (payload_hash[i] - 1) === 0");
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
