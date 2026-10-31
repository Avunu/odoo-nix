// The addon's build: a dependency from node_modules, written where Odoo
// serves it (static/dist/, outside static/src so Odoo does not take it for
// an @odoo-module).
import { mkdirSync, writeFileSync } from "node:fs";
import isNumber from "is-number";

mkdirSync("static/dist", { recursive: true });
writeFileSync("static/dist/pos_ui.js", `window.pos_ui = ${isNumber(1)};\n`);
