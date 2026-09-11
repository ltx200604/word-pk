/**
 * Decode Shanbay bays4 payload from file or argv.
 * Usage:
 *   node decode_bays4.js --file <in.txt> <outfile>
 *   node decode_bays4.js <payload> [outfile]
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const libPath = path.join(__dirname, "..", "data", "bays4.js");
const src = fs.readFileSync(libPath, "utf8");

function loadBays4() {
  const sandbox = {
    module: { exports: {} },
    exports: {},
    console,
  };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  sandbox.global = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox);
  const exp = sandbox.module.exports;
  if (typeof exp === "function" && typeof exp.d === "function") {
    return exp;
  }
  if (exp && typeof exp.default === "function" && typeof exp.default.d === "function") {
    return exp.default;
  }
  throw new Error("cannot load bays4.d");
}

function main() {
  const args = process.argv.slice(2);
  let payload = null;
  let outfile = null;
  if (args[0] === "--file") {
    payload = fs.readFileSync(args[1], "utf8").trim();
    outfile = args[2] || null;
  } else {
    payload = args[0];
    outfile = args[1] || null;
  }
  if (!payload) {
    console.error("usage: node decode_bays4.js --file <in> <out>");
    process.exit(1);
  }
  const lib = loadBays4();
  const out = lib.d(payload);
  if (!out) {
    console.error("empty decode");
    process.exit(2);
  }
  if (outfile) {
    fs.writeFileSync(outfile, out, "utf8");
    console.log("ok", out.length);
  } else {
    process.stdout.write(out);
  }
}

if (require.main === module) main();
module.exports = { loadBays4 };
