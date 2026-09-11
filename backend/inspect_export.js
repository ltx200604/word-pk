/**
 * Inspect bays4 export shape.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const libPath = path.join(__dirname, "..", "data", "bays4.js");
const src = fs.readFileSync(libPath, "utf8");

const sandbox = {
  module: { exports: {} },
  exports: {},
  console,
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.global = sandbox;
vm.createContext(sandbox);
try {
  vm.runInContext(src, sandbox);
} catch (e) {
  console.error("run error", e);
}

const exp = sandbox.module.exports;
console.log("typeof exports", typeof exp);
console.log("exports keys", exp && Object.keys(exp));
console.log("exports.default", typeof exp?.default);
if (typeof exp === "function") {
  console.log("function name", exp.name);
  console.log("static d", typeof exp.d);
  const inst = new exp();
  console.log("inst keys", Object.getOwnPropertyNames(Object.getPrototypeOf(inst)));
  console.log("inst.d", typeof inst.d);
  try {
    const s = "QMQBM3UN73TU6HI4BOKU63NKIZNTOO4B34M3UN7OO34K3CMOJM6AJWUN4TOO27HVTHVMUHVU63N7OKU6";
    console.log("try inst.d", inst.d(s).slice(0, 100));
  } catch (e) {
    console.error("inst.d fail", e.message);
  }
}
console.log("window.bays4", typeof sandbox.bays4);
