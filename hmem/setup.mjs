// Vendors the Meterless H-MEM reference implementation and its conformance suite (Apache 2.0).
// Uses a local checkout of github.com/meterless/meterless when METERLESS_REPO points at one,
// otherwise fetches with degit. vendor/ and conformance/ are gitignored.
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const here = path.dirname(new URL(import.meta.url).pathname);
const local = process.env.METERLESS_REPO;
const copy = (from, to) => fs.cpSync(from, to, { recursive: true, filter: (p) => !p.includes("node_modules") });
fs.rmSync(path.join(here, "vendor"), { recursive: true, force: true });
fs.rmSync(path.join(here, "conformance"), { recursive: true, force: true });
if (local && fs.existsSync(path.join(local, "engines/hmem/reference"))) {
  copy(path.join(local, "engines/hmem/reference"), path.join(here, "vendor/hmem"));
  copy(path.join(local, "engines/hmem/conformance"), path.join(here, "conformance"));
  fs.copyFileSync(path.join(local, "engines/hmem/LICENSE"), path.join(here, "vendor/hmem/LICENSE"));
  console.log("H-MEM vendored from", local);
} else {
  execSync("npx --yes degit meterless/meterless/engines/hmem/reference vendor/hmem", { cwd: here, stdio: "inherit" });
  execSync("npx --yes degit meterless/meterless/engines/hmem/conformance conformance", { cwd: here, stdio: "inherit" });
  execSync("curl -sfL https://raw.githubusercontent.com/meterless/meterless/main/engines/hmem/LICENSE -o vendor/hmem/LICENSE", { cwd: here, stdio: "inherit" });
}
execSync("npm install --no-audit --no-fund", { cwd: path.join(here, "vendor/hmem"), stdio: "inherit" });
