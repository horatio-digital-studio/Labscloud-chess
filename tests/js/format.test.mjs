import assert from "node:assert/strict";
import { test } from "node:test";

import {
  COOLDOWN_STEPS,
  ERROR_TOASTS,
  backoffDelay,
  cooldownLabel,
  moveNumber,
  pairMoves,
  relativeTime,
  resultFor,
  shortDate,
  spokenSan,
  statusLine,
  stepCooldown,
  toastFor,
  validateName,
} from "../../public/js/format.js";

test("cooldown steps and labels match REQ-NOTIFY-06", () => {
  assert.deepEqual(COOLDOWN_STEPS, [5, 10, 15, 30, 45, 60, 120, 240, 480, 720, 1440]);
  assert.deepEqual(COOLDOWN_STEPS.map(cooldownLabel), [
    "5 min", "10 min", "15 min", "30 min", "45 min", "1 h", "2 h", "4 h", "8 h", "12 h", "24 h",
  ]);
  assert.equal(stepCooldown(30, 1), 45);
  assert.equal(stepCooldown(30, -1), 15);
  assert.equal(stepCooldown(5, -1), 5);
  assert.equal(stepCooldown(1440, 1), 1440);
  assert.equal(stepCooldown(31, 1), 45); // unknown value restarts from the default
});

test("validateName mirrors the server rule", () => {
  assert.equal(validateName("  Sam "), "Sam");
  assert.equal(validateName("x".repeat(24)), "x".repeat(24));
  assert.equal(validateName("🙂".repeat(24)), "🙂".repeat(24)); // code points, like Python len()
  assert.equal(validateName("x".repeat(25)), null);
  assert.equal(validateName("   "), null);
  assert.equal(validateName("a\tb"), null);
  assert.equal(validateName("a\u0085b"), null); // C1 control (NEL)
  assert.equal(validateName(null), null);
});

test("every server error code has friendly copy", () => {
  for (const code of ["NOT_YOUR_TURN", "STALE_PLY", "ILLEGAL_MOVE", "BAD_FORMAT", "GAME_OVER", "CANNOT_CLAIM",
    "DRAW_ALREADY_OFFERED", "NO_DRAW_OFFER", "OWN_DRAW_OFFER", "REMATCH_NOT_AVAILABLE", "TAKEBACK_NOT_AVAILABLE",
    "TAKEBACK_ALREADY_REQUESTED", "NO_TAKEBACK_REQUEST", "OWN_TAKEBACK_REQUEST", "BAD_MESSAGE", "INTERNAL"]) {
    assert.ok(ERROR_TOASTS[code], code);
  }
  assert.equal(toastFor("WHO_KNOWS"), "Something went wrong.");
});

test("relative times and dates", () => {
  const now = new Date(2026, 9, 12, 15, 0, 0).getTime();
  assert.equal(relativeTime(now - 10_000, now), "just now");
  assert.equal(relativeTime(now - 60_000, now), "1 minute ago");
  assert.equal(relativeTime(now - 120_000, now), "2 minutes ago");
  assert.equal(relativeTime(now - 3_600_000, now), "1 hour ago");
  assert.equal(relativeTime(new Date(2026, 9, 11, 23, 0).getTime(), now), "yesterday");
  assert.equal(relativeTime(new Date(2026, 9, 9, 12, 0).getTime(), now), "3 days ago");
  assert.equal(relativeTime(new Date(2026, 8, 1, 12, 0).getTime(), now), "1 Sep");
  assert.equal(relativeTime(now + 5000, now), "just now"); // clock skew
  assert.equal(shortDate(new Date(2026, 9, 12).getTime()), "12 Oct");
});

test("move numbers and pairs", () => {
  assert.equal(moveNumber(0), 1);
  assert.equal(moveNumber(1), 1);
  assert.equal(moveNumber(12), 7);
  const pairs = pairMoves([{ san: "e4" }, { san: "e5" }, { san: "Nf3" }]);
  assert.deepEqual(pairs, [
    { number: 1, white: "e4", black: "e5" },
    { number: 2, white: "Nf3", black: null },
  ]);
  assert.deepEqual(pairMoves([]), []);
});

test("spoken SAN", () => {
  assert.equal(spokenSan("e4"), "Pawn to e4");
  assert.equal(spokenSan("Nf3+"), "Knight to f3, check");
  assert.equal(spokenSan("exd5"), "Pawn from e takes on d5");
  assert.equal(spokenSan("Qxf7#"), "Queen takes on f7, checkmate");
  assert.equal(spokenSan("O-O"), "Castles kingside");
  assert.equal(spokenSan("O-O-O+"), "Castles queenside, check");
  assert.equal(spokenSan("e8=Q+"), "Pawn to e8, promotes to queen, check");
  assert.equal(spokenSan("Nbd2"), "Knight from b to d2");
  assert.equal(spokenSan("R1xa3"), "Rook from 1 takes on a3");
});

test("lobby result from the viewer's side", () => {
  assert.equal(resultFor({ you: "white", result: "1-0" }), "Won");
  assert.equal(resultFor({ you: "black", result: "1-0" }), "Lost");
  assert.equal(resultFor({ you: "black", result: "0-1" }), "Won");
  assert.equal(resultFor({ you: "white", result: "1/2-1/2" }), "Draw");
});

function state(overrides) {
  return {
    you: "white",
    turn: "white",
    check: false,
    status: "active",
    result: null,
    players: { white: { name: "Harry" }, black: { name: "Sam" } },
    ...overrides,
  };
}

test("status lines for every game state (ui-spec §4.3)", () => {
  assert.equal(statusLine(state({})), "Your move");
  assert.equal(statusLine(state({ check: true })), "Check — your move");
  assert.equal(statusLine(state({ turn: "black" })), "Sam's move");
  assert.equal(statusLine(state({ status: "checkmate", result: "1-0" })), "Checkmate — you win");
  assert.equal(statusLine(state({ you: "black", status: "checkmate", result: "1-0" })), "Checkmate — Harry wins");
  assert.equal(statusLine(state({ status: "resigned", result: "0-1" })), "You resigned — Sam wins");
  assert.equal(statusLine(state({ status: "resigned", result: "1-0" })), "Sam resigned — you win");
  assert.equal(statusLine(state({ status: "stalemate", result: "1/2-1/2" })), "Draw — stalemate");
  assert.equal(statusLine(state({ status: "insufficient_material", result: "1/2-1/2" })), "Draw — not enough pieces to mate");
  assert.equal(statusLine(state({ status: "seventyfive_moves", result: "1/2-1/2" })), "Draw — 75 moves without a capture or pawn move");
  assert.equal(statusLine(state({ status: "fivefold_repetition", result: "1/2-1/2" })), "Draw — same position five times");
  assert.equal(statusLine(state({ status: "draw_claimed", result: "1/2-1/2" })), "Draw — claimed");
  assert.equal(statusLine(state({ status: "draw_agreed", result: "1/2-1/2" })), "Draw — agreed");
});

test("back-off 0.5, 1, 2, 4, 8, 8 s with ±20 % jitter (REQ-UI-07)", () => {
  const mid = () => 0.5;
  assert.deepEqual([0, 1, 2, 3, 4, 5, 9].map((n) => backoffDelay(n, mid)), [500, 1000, 2000, 4000, 8000, 8000, 8000]);
  assert.equal(backoffDelay(0, () => 0), 400);
  assert.equal(backoffDelay(4, () => 0.999999), 9600);
});
