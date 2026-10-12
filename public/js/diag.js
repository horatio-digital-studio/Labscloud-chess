// Staging diagnostics (S-04): play a fixed 150-ply game through /api/diag/move and report
// whether any request hit the Workers CPU limit (error 1102). Not available in production.

import { api } from "./api.js";

// A legal 150-ply game that never ends early (generated with python-chess, seed 0).
const MOVES = [
  "f2f3 f7f6 a2a4 d7d5 g2g3 d8d6 e2e3 d6c5 f1a6 e7e6 e1f1 c5d6 d2d4 c7c5 b1d2 c5c4 a4a5 e8d8 d1e1",
  "d8d7 h2h3 h7h5 g1e2 d6a3 e1d1 a3d3 a1a4 h5h4 d2b3 d7e8 f3f4 b8d7 d1e1 g8e7 e1b4 e7g8 f1f2 d3d2",
  "f2g1 f6f5 e2c3 h8h6 c3e2 d7b6 a4a2 g7g6 a2a1 b6d7 b4d6 h6h5 g1h2 g6g5 a1a2 f8h6 d6e7 g8e7 a6b5",
  "e7c6 a2a4 c6d8 b5a6 d2d3 a6b5 g5g4 a4a3 b7b6 c1d2 h6g5 e2c1 c8a6 c2c3 g5f6 d2e1 f6h8 b3a1 e8f8",
  "c1b3 h5h7 h2g2 d7e5 h1g1 e5g6 g1h1 d3c2 g2g1 h7b7 b5a4 c2d3 e1d2 b7c7 a4c6 g6e7 c6a4 a6b7 b3c5",
  "d8c6 a3a2 a8c8 a4b5 c6b8 a1c2 b7a8 d2e1 e7c6 g1g2 c7g7 g2h2 e6e5 c2a1 d3f1 b5a4 g7g5 a4d1 h8g7",
  "e1f2 f8e8 c5e4 f1g1 h1g1 e8f8 e4f6 e5e4 a2a3 c8d8 g1e1 b8a6 e1h1 g5h5 h1g1 d8b8 b2b4 b8e8 a1b3",
  "c6e7 b3a1 e7c8 f2e1 b6b5 e1d2 f8f7 a1c2 a8b7 c2a1 h5g5 d1c2 a6c5 g1d1 f7e6 f6d7 g5g6",
]
  .join(" ")
  .split(" ");

const $ = (id) => document.getElementById(id);

async function diagMove(gameId, uci) {
  const started = performance.now();
  const response = await fetch("/api/diag/move", {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ game_id: gameId, uci }),
  });
  const text = await response.text();
  return { status: response.status, text, ms: performance.now() - started };
}

async function run() {
  const button = $("run");
  button.disabled = true;
  $("copy").disabled = true;
  const results = { sent: 0, errors: 0, cpuLimit: 0, totalMs: 0, slowestMs: 0, firstError: "" };
  try {
    const created = await api.createGame("white");
    const gameId = created.game.id;
    results.gameId = gameId;
    for (let index = 0; index < MOVES.length; index += 1) {
      $("progress").textContent = `Ply ${index + 1}/${MOVES.length}`;
      const reply = await diagMove(gameId, MOVES[index]);
      results.sent += 1;
      results.totalMs += reply.ms;
      results.slowestMs = Math.max(results.slowestMs, reply.ms);
      let ok = false;
      try {
        ok = reply.status === 200 && JSON.parse(reply.text).ok === true;
      } catch (error) {
        ok = false;
      }
      if (!ok) {
        results.errors += 1;
        if (reply.status === 503 || reply.text.includes("1102")) results.cpuLimit += 1;
        if (!results.firstError) results.firstError = `ply ${index + 1}: HTTP ${reply.status} ${reply.text.slice(0, 120)}`;
      }
    }
    $("progress").textContent = "Done";
  } catch (error) {
    $("progress").textContent = `Stopped: ${error.message}`;
  }
  render(results);
  button.disabled = false;
}

function render(results) {
  const rows = [
    ["Game", results.gameId || "–"],
    ["Moves sent", String(results.sent)],
    ["Errors", String(results.errors)],
    ["1102 (CPU limit) responses", String(results.cpuLimit)],
    ["Total time", `${Math.round(results.totalMs)} ms`],
    ["Average per move", results.sent ? `${Math.round(results.totalMs / results.sent)} ms` : "–"],
    ["Slowest move", `${Math.round(results.slowestMs)} ms`],
    ["First error", results.firstError || "none"],
  ];
  const body = $("results");
  body.replaceChildren();
  for (const [label, value] of rows) {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = label;
    const td = document.createElement("td");
    td.textContent = value;
    tr.append(th, td);
    body.append(tr);
  }
  $("copy").disabled = false;
  $("copy").onclick = async () => {
    const text = rows.map(([label, value]) => `| ${label} | ${value} |`).join("\n");
    try {
      await navigator.clipboard.writeText(`| Check | Result |\n|---|---|\n${text}`);
      $("progress").textContent = "Copied";
    } catch (error) {
      $("progress").textContent = "Couldn't copy; select the table instead.";
    }
  };
}

$("run").addEventListener("click", run);
