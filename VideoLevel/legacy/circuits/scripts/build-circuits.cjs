"use strict";

// Builds local Groth16 artifacts.  A verified Powers of Tau file and fresh,
// secret entropy are deliberately required; this script never creates a
// predictable development ceremony for a production artifact.

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const circuitDir = path.resolve(__dirname, "..");
const buildDir = path.join(circuitDir, "build");
const snarkjsCli = path.join(circuitDir, "node_modules", "snarkjs", "build", "cli.cjs");
const ptauFile = process.env.PTAU_FILE;
const entropy = process.env.ZKEY_ENTROPY;

function run(command, args, input) {
  const executable = process.platform === "win32" && command === "npx" ? "npx.cmd" : command;
  const result = spawnSync(executable, args, {
    cwd: circuitDir,
    encoding: "utf8",
    stdio: input === undefined ? "inherit" : ["pipe", "inherit", "inherit"],
    shell: false,
    input,
  });
  if (result.status !== 0) {
    throw new Error(`${executable} ${args.join(" ")} failed with exit code ${result.status}`);
  }
}

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function runSnarkjs(args, input) {
  run(process.execPath, [snarkjsCli, ...args], input);
}

if (!ptauFile || !fs.existsSync(ptauFile)) {
  throw new Error("PTAU_FILE must point to a verified Powers of Tau .ptau file.");
}
if (!entropy || entropy.length < 32) {
  throw new Error("ZKEY_ENTROPY must contain at least 32 characters of freshly generated secret entropy.");
}

fs.mkdirSync(buildDir, { recursive: true });
run("circom", ["payload_verify.circom", "--r1cs", "--wasm", "--sym", "-o", "build"]);

const r1cs = path.join(buildDir, "payload_verify.r1cs");
const provisionalZkey = path.join(buildDir, "proving_key_initial.zkey");
const provingKey = path.join(buildDir, "proving_key.zkey");
const verificationKey = path.join(buildDir, "verification_key.json");

runSnarkjs(["groth16", "setup", r1cs, path.resolve(ptauFile), provisionalZkey]);
runSnarkjs(["zkey", "contribute", provisionalZkey, provingKey], `${entropy}\n`);
fs.rmSync(provisionalZkey, { force: true });
runSnarkjs(["zkey", "export", "verificationkey", provingKey, verificationKey]);

const artifactManifest = {
  schema: "zk-stego-circuit-artifacts-v1",
  circuit: "payload_verify",
  generated_at: new Date().toISOString(),
  ptau_sha256: sha256(path.resolve(ptauFile)),
  files: Object.fromEntries(
    [r1cs, provingKey, verificationKey, path.join(buildDir, "payload_verify_js", "payload_verify.wasm")]
      .map((filePath) => [path.relative(buildDir, filePath).replaceAll("\\", "/"), sha256(filePath)]),
  ),
};
fs.writeFileSync(
  path.join(buildDir, "artifacts.json"),
  `${JSON.stringify(artifactManifest, null, 2)}\n`,
  { encoding: "utf8", mode: 0o600 },
);
console.log("Circuit artifacts built and recorded in build/artifacts.json.");
