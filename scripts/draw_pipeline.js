#!/usr/bin/env node
/**
 * Draws the SWE-Flux-Live pipeline as a compact SVG flow, then renders it to
 * PNG with headless Chrome.
 *
 *   node scripts/draw_pipeline.js [--out out/pipeline.png] [--scale 2]
 *
 * Pure JS layout, no npm dependencies. Colors: validated dataviz palette.
 */

const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

// ---------------------------------------------------------------- palette --
const C = {
  bg: "#fcfcfb",
  panel: "#ffffff",
  ink: "#0b0b0b",
  ink2: "#52514e",
  ink3: "#8a8880",
  rule: "#dcdad4",
  blue: "#2a78d6",     // agent-authored
  orange: "#eb6834",   // deterministic screen
  aqua: "#1baf7a",     // agent-validated
  violet: "#4a3aa7",   // measurement only
  good: "#0ca30c",
  warning: "#fab219",
  critical: "#d03b3b",
};

const SANS = "'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
const MONO = "'JetBrains Mono', 'DejaVu Sans Mono', Menlo, monospace";

const out = [];
const push = (s) => out.push(s);
const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function rect(x, y, w, h, o = {}) {
  const { fill = C.panel, stroke = C.rule, sw = 1.5, r = 12, dash = null, op = 1 } = o;
  push(
    `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" ry="${r}" fill="${fill}" ` +
      `fill-opacity="${op}" stroke="${stroke}" stroke-width="${sw}"` +
      (dash ? ` stroke-dasharray="${dash}"` : "") + `/>`
  );
}

function txt(x, y, s, o = {}) {
  const {
    size = 14, weight = 400, fill = C.ink, anchor = "start", family = SANS,
  } = o;
  push(
    `<text x="${x}" y="${y}" font-family="${esc(family)}" font-size="${size}" ` +
      `font-weight="${weight}" fill="${fill}" text-anchor="${anchor}">${esc(s)}</text>`
  );
}

function arrow(x1, y1, x2, y2, o = {}) {
  const { stroke = C.ink3, sw = 2.5, dash = null } = o;
  push(
    `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${sw}" ` +
      `stroke-linecap="round" marker-end="url(#a)"` +
      (dash ? ` stroke-dasharray="${dash}"` : "") + `/>`
  );
}

/** A stage node: number badge, name, one short descriptor. */
function node(x, y, w, h, n, name, desc, color) {
  rect(x, y, w, h, { stroke: color, sw: 2 });
  push(`<rect x="${x}" y="${y}" width="${w}" height="4" rx="2" fill="${color}"/>`);
  push(`<circle cx="${x + 26}" cy="${y + 34}" r="13" fill="${color}" fill-opacity="0.14"/>`);
  txt(x + 26, y + 39, String(n), { size: 14, weight: 700, fill: color, anchor: "middle" });
  txt(x + 48, y + 33, name, { size: 17, weight: 700 });
  if (desc) txt(x + 48, y + 53, desc, { size: 13, fill: C.ink3 });
}

/** Small file chip under a stage. */
function file(x, y, name, color = C.ink3) {
  const w = name.length * 7.3 + 22;
  rect(x, y, w, 26, { fill: "#f5f4f1", stroke: C.rule, sw: 1, r: 6 });
  push(`<circle cx="${x + 12}" cy="${y + 13}" r="3" fill="${color}"/>`);
  txt(x + 22, y + 18, name, { size: 12, family: MONO, fill: C.ink2 });
  return w;
}

// ------------------------------------------------------------------ layout --
const W = 1560;
const M = 56;

// ---- title
txt(M, 62, "SWE-Flux-Live — pipeline", { size: 30, weight: 700 });
txt(M, 90, "mine → author → screen → validate → label", { size: 15, fill: C.ink3 });

// legend
let lx = W - M;
for (const [label, c] of [
  ["measure only", C.violet], ["agent-validated", C.aqua],
  ["screen", C.orange], ["agent-authored", C.blue], ["deterministic", C.ink3],
].reverse()) {
  const w = label.length * 6.6 + 26;
  lx -= w + 8;
  push(`<circle cx="${lx + 12}" cy="${74}" r="5" fill="${c}"/>`);
  txt(lx + 24, 79, label, { size: 12, fill: C.ink2 });
}

// ---- prompt kit: what every generation session is given
const PK = 128, PKH = 74;
rect(M, PK, W - M * 2, PKH, { fill: C.blue, stroke: C.blue, sw: 1.5, r: 12, op: 0.05 });
txt(M + 20, PK + 28, "EVERY GENERATION SESSION RECEIVES", {
  size: 11, weight: 700, fill: C.blue,
});
const kit = [
  "base contract",
  "category card",
  "answer template for the category",
  "the 5 screening rules",
  "qa_pipeline.sh + tracer (harvest harness)",
  "target dossier",
];
let kx = M + 20;
for (const k of kit) {
  const w = k.length * 6.9 + 26;
  rect(kx, PK + 38, w, 24, { fill: C.panel, stroke: C.blue, sw: 1, r: 12, op: 1 });
  push(`<circle cx="${kx + 12}" cy="${PK + 50}" r="3" fill="${C.blue}"/>`);
  txt(kx + 22, PK + 55, k, { size: 12, fill: C.ink2 });
  kx += w + 10;
}

// ---- row 1: the linear stages
const R1 = 244;
const NW = 268, NH = 78, GAP = 54;
const stages = [
  ["Scout", "find target functions", C.ink3, "targets.json"],
  ["Plan", "allocate 13 categories", C.ink3, "plan.json"],
  ["Generate", "1 agent session each", C.blue, "oracle.json"],
  ["Screen", "5 deterministic rules", C.orange, "screening_report.json"],
];
stages.forEach(([name, desc, color, artifact], i) => {
  const x = M + i * (NW + GAP);
  node(x, R1, NW, NH, i + 1, name, desc, color);
  file(x, R1 + NH + 14, artifact, color);
  if (i < stages.length - 1) arrow(x + NW + 8, R1 + NH / 2, x + NW + GAP - 8, R1 + NH / 2);
});

// prompt kit feeds the Generate stage; the agent runs the harness itself
const gx = M + 2 * (NW + GAP) + NW / 2;
arrow(gx, PK + PKH + 4, gx, R1 - 10, { stroke: C.blue, sw: 2 });
txt(gx + 14, R1 - 22, "agent runs the harness, harvests its own oracle", {
  size: 12, fill: C.blue,
});

// screen drops failures sideways, keeps the rest flowing down
const sx = M + 3 * (NW + GAP);
arrow(sx + NW + 8, R1 + NH / 2, sx + NW + 62, R1 + NH / 2, { stroke: C.orange, sw: 2, dash: "5 4" });
txt(sx + NW + 74, R1 + NH / 2 + 5, "excluded_instances/", {
  size: 12, family: MONO, fill: C.orange,
});

// ---- row 2: validation cascade
const R2 = R1 + NH + 150;
const BH = 300;
rect(M - 16, R2, W - (M - 16) * 2, BH, { fill: C.aqua, stroke: C.aqua, sw: 2, r: 16, op: 0.05 });
push(`<circle cx="${M + 10}" cy="${R2 + 34}" r="13" fill="${C.aqua}" fill-opacity="0.16"/>`);
txt(M + 10, R2 + 39, "5", { size: 14, weight: 700, fill: C.aqua, anchor: "middle" });
txt(M + 32, R2 + 33, "Validation cascade", { size: 19, weight: 700 });
txt(M + 32, R2 + 54, "weakest model first · all rollouts must pass", { size: 13, fill: C.ink3 });

// tiers
const TW = 300, TH = 116, TY = R2 + 84;
const tiers = [
  { t: "TIER 1", m: "Haiku 4.5", label: "validated", c: C.good, dash: false },
  { t: "TIER 2", m: "Fable 5", label: "validated", c: C.warning, dash: false },
  { t: "TIER n", m: "any model", label: "…", c: C.ink3, dash: true },
];
tiers.forEach((t, i) => {
  const x = M + 32 + i * (TW + 76);
  rect(x, TY, TW, TH, {
    stroke: t.dash ? C.rule : t.c, sw: 2, dash: t.dash ? "6 6" : null,
  });
  txt(x + 20, TY + 28, t.t, { size: 11, weight: 700, fill: t.dash ? C.ink3 : t.c });
  txt(x + 20, TY + 54, t.m, { size: 18, weight: 700 });
  // label chip
  rect(x + 20, TY + 70, 92, 26, { fill: t.c, stroke: "none", sw: 0, r: 13, op: 0.16 });
  txt(x + 66, TY + 88, t.label, {
    size: 12, weight: 700, fill: t.dash ? C.ink3 : t.c, anchor: "middle",
  });
  txt(x + 124, TY + 88, "solved → accept", { size: 12, fill: C.ink3 });
  if (i < 2) {
    arrow(x + TW + 8, TY + TH / 2, x + TW + 68, TY + TH / 2, { stroke: C.critical, sw: 2 });
    txt(x + TW + 38, TY + TH / 2 - 12, "fail", {
      size: 11, weight: 700, fill: C.critical, anchor: "middle",
    });
  }
});

// rejected chip at the end of the ladder
const rx = M + 32 + 3 * (TW + 76) - 12;
push(`<circle cx="${rx + 16}" cy="${TY + TH / 2}" r="7" fill="${C.critical}"/>`);
txt(rx + 32, TY + TH / 2 - 2, "rejected", { size: 15, weight: 700 });
txt(rx + 32, TY + TH / 2 + 16, "discarded", { size: 12, fill: C.ink3 });

// runner knobs
txt(M + 32, R2 + BH - 34, "P parallel containers   ·   R rollouts per instance   ·   solver never sees the oracle",
  { size: 13, fill: C.ink2 });

// ---- row 3: outputs
const R3 = R2 + BH + 56;
node(M, R3, NW, NH, 6, "Intrinsic difficulty", "easy · medium · hard · very hard", C.aqua);
file(M, R3 + NH + 14, "difficulty.json", C.aqua);

node(M + NW + GAP, R3, NW, NH, 7, "Evaluate", "raw LLMs — measure only", C.violet);
file(M + NW + GAP, R3 + NH + 14, "evaluation_report.json", C.violet);

arrow(M + NW + 8, R3 + NH / 2, M + NW + GAP - 8, R3 + NH / 2);

// results tile
const QX = M + 2 * (NW + GAP);
rect(QX, R3, W - M - QX, NH + 40, { stroke: C.rule, sw: 1.5 });
txt(QX + 24, R3 + 28, "2 repos · 80 planned", { size: 12, weight: 700, fill: C.ink3 });
[["62", "easy", C.good], ["10", "hard", C.warning], ["4", "rejected", C.critical]]
  .forEach(([n, l, c], i) => {
    const x = QX + 24 + i * 116;
    txt(x, R3 + 72, n, { size: 30, weight: 700, fill: c });
    txt(x, R3 + 94, l, { size: 13, fill: C.ink2 });
  });

// screened instances enter validation; validated instances receive intrinsic labels
arrow(sx + NW / 2, R1 + NH + 52, sx + NW / 2, R2 - 10);
arrow(M + NW / 2, R2 + BH + 6, M + NW / 2, R3 - 10);

const H = R3 + NH + 92;

// ------------------------------------------------------------------ emit --
out.unshift(`<rect x="0" y="0" width="${W}" height="${H}" fill="${C.bg}"/>`);
const svg =
  `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">` +
  `<defs><marker id="a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" ` +
  `orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="${C.ink3}"/></marker></defs>` +
  out.join("") + `</svg>`;

const argv = process.argv.slice(2);
const argOf = (k, d) => {
  const i = argv.indexOf(k);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : d;
};
const outPng = path.resolve(argOf("--out", "out/pipeline.png"));
const scale = Number(argOf("--scale", "2"));

fs.mkdirSync(path.dirname(outPng), { recursive: true });
const svgPath = outPng.replace(/\.png$/, ".svg");
fs.writeFileSync(svgPath, svg);

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "pipeline-"));
const html = path.join(tmp, "page.html");
fs.writeFileSync(
  html,
  `<!doctype html><meta charset="utf-8">` +
    `<style>html,body{margin:0;padding:0;background:${C.bg}}svg{display:block}</style>` +
    svg.replace("<svg ", `<svg style="width:${W * scale}px;height:${H * scale}px" `)
);

execFileSync("google-chrome", [
  "--headless", "--disable-gpu", "--hide-scrollbars",
  `--screenshot=${outPng}`, `--window-size=${W * scale},${H * scale}`,
  "--virtual-time-budget=3000", `file://${html}`,
], { stdio: "ignore" });

console.log(`PNG  ${outPng}  (${W * scale}×${H * scale}, ${(fs.statSync(outPng).size / 1024).toFixed(0)} KB)`);
console.log(`SVG  ${svgPath}`);
