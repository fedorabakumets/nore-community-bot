// Identical deterministic rules to the browser; no network or filesystem permissions needed.
import process from "node:process";
import "./web/dot-core.js";
let input="";
for await(const chunk of process.stdin){input+=chunk.toString();if(input.length>2000000)throw Error("payload too large");}
const {seed,ticks,flaps,reviveTick}=JSON.parse(input);
const result=globalThis.NoraDotCore.replay(seed,ticks,flaps,reviveTick);
process.stdout.write(JSON.stringify(result));
