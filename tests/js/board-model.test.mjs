import assert from "node:assert/strict";
import { test } from "node:test";

import {
  coordinates,
  displayOrder,
  glyph,
  isDark,
  kingSquare,
  movesBetween,
  needsPromotion,
  neighbour,
  parseFen,
  previewMove,
  squareLabel,
  targetsFrom,
} from "../../public/js/board-model.js";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

test("parseFen places every piece", () => {
  const pieces = parseFen(START);
  assert.equal(pieces.size, 32);
  assert.equal(pieces.get("e1"), "K");
  assert.equal(pieces.get("d8"), "q");
  assert.equal(pieces.get("a2"), "P");
  assert.equal(pieces.has("e4"), false);
  assert.throws(() => parseFen("8/8/8"));
  assert.throws(() => parseFen("9/8/8/8/8/8/8/8 w - - 0 1"));
  assert.throws(() => parseFen("x7/8/8/8/8/8/8/8 w - - 0 1"));
});

test("orientation puts your colour at the bottom (REQ-UI-01)", () => {
  const white = displayOrder("white");
  assert.equal(white[0], "a8");
  assert.equal(white[63], "h1");
  const black = displayOrder("black");
  assert.equal(black[0], "h1");
  assert.equal(black[63], "a8");
  assert.equal(new Set(black).size, 64);
  assert.deepEqual(coordinates("a1", "white"), { rank: "1", file: "a" });
  assert.deepEqual(coordinates("h8", "black"), { rank: "8", file: "h" });
  assert.deepEqual(coordinates("e4", "white"), { rank: "", file: "" });
});

test("square colours", () => {
  assert.equal(isDark("a1"), true);
  assert.equal(isDark("h1"), false);
  assert.equal(isDark("e4"), false);
  assert.equal(isDark("d4"), true);
});

test("targets come only from the server's legal list (REQ-UI-03)", () => {
  const legal = ["e2e3", "e2e4", "g1f3", "g1h3"];
  assert.deepEqual([...targetsFrom(legal, "e2").keys()], ["e3", "e4"]);
  assert.deepEqual([...targetsFrom(legal, "d2").keys()], []);
  assert.deepEqual([...targetsFrom(undefined, "e2").keys()], []);
});

test("promotion needs a choice (REQ-UI-04)", () => {
  const legal = ["a7a8q", "a7a8r", "a7a8b", "a7a8n", "h2h3"];
  const promo = movesBetween(legal, "a7", "a8");
  assert.equal(promo.length, 4);
  assert.equal(needsPromotion(promo), true);
  assert.equal(needsPromotion(movesBetween(legal, "h2", "h3")), false);
  assert.equal(needsPromotion([]), false);
});

test("king square and labels", () => {
  const pieces = parseFen(START);
  assert.equal(kingSquare(pieces, "white"), "e1");
  assert.equal(kingSquare(pieces, "black"), "e8");
  assert.equal(squareLabel("g1", "N"), "g1, white knight");
  assert.equal(squareLabel("e4", undefined), "e4, empty");
  assert.equal(glyph("N"), "♞︎");
  assert.equal(glyph("n"), "♞︎");
  assert.equal(glyph(undefined), "");
});

test("arrow keys move in screen space", () => {
  assert.equal(neighbour("e2", "ArrowUp", "white"), "e3");
  assert.equal(neighbour("e2", "ArrowUp", "black"), "e1");
  assert.equal(neighbour("a1", "ArrowLeft", "white"), "a1");
  assert.equal(neighbour("b1", "ArrowRight", "black"), "a1");
  assert.equal(neighbour("h8", "ArrowRight", "white"), "h8");
  assert.equal(neighbour("d4", "Home", "white"), "a4");
  assert.equal(neighbour("d4", "End", "black"), "a4");
});

test("pending preview moves the piece and promotes", () => {
  const pieces = previewMove(parseFen(START), "e2e4");
  assert.equal(pieces.get("e4"), "P");
  assert.equal(pieces.has("e2"), false);
  const promo = previewMove(parseFen("8/P7/8/8/8/8/8/k6K w - - 0 1"), "a7a8n");
  assert.equal(promo.get("a8"), "N");
  const blackPromo = previewMove(parseFen("8/8/8/8/8/8/p7/k6K b - - 0 1"), "a2a1q");
  assert.equal(blackPromo.get("a1"), "q");
});
