// Pure board helpers: FEN placement, orientation, legal-move lookups and labels.
// The client never decides legality; these functions only *read* the server's `legal` list
// (REQ-UI-03, REQ-UI-14). No DOM access, so node:test imports this file directly.

export const FILES = "abcdefgh";

const GLYPHS = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };
const NAMES = { k: "king", q: "queen", r: "rook", b: "bishop", n: "knight", p: "pawn" };

/** Map of square → piece letter (upper case = white) from a FEN's placement field. */
export function parseFen(fen) {
  const pieces = new Map();
  const placement = String(fen).split(" ")[0];
  const ranks = placement.split("/");
  if (ranks.length !== 8) throw new Error("bad FEN");
  ranks.forEach((row, rowIndex) => {
    let file = 0;
    for (const ch of row) {
      if (ch >= "1" && ch <= "8") {
        file += Number(ch);
      } else {
        if (file > 7 || !"kqrbnpKQRBNP".includes(ch)) throw new Error("bad FEN");
        pieces.set(`${FILES[file]}${8 - rowIndex}`, ch);
        file += 1;
      }
    }
    if (file !== 8) throw new Error("bad FEN");
  });
  return pieces;
}

export function pieceColour(piece) {
  if (!piece) return null;
  return piece === piece.toUpperCase() ? "white" : "black";
}

/** Text-presentation glyph: solid pieces for both sides, coloured by CSS. */
export function glyph(piece) {
  return piece ? `${GLYPHS[piece.toLowerCase()]}︎` : "";
}

export function pieceName(piece) {
  return piece ? `${pieceColour(piece)} ${NAMES[piece.toLowerCase()]}` : "";
}

/** "e4, white knight" or "e4, empty" for screen readers (REQ-UI-12). */
export function squareLabel(square, piece) {
  return `${square}, ${piece ? pieceName(piece) : "empty"}`;
}

export function isDark(square) {
  const file = FILES.indexOf(square[0]);
  const rank = Number(square[1]);
  return (file + rank) % 2 === 1; // a1 is a dark square
}

/** Squares in display order, top-left first, for the given colour at the bottom. */
export function displayOrder(bottom) {
  const order = [];
  for (let row = 0; row < 8; row += 1) {
    for (let col = 0; col < 8; col += 1) {
      const file = bottom === "white" ? col : 7 - col;
      const rank = bottom === "white" ? 8 - row : row + 1;
      order.push(`${FILES[file]}${rank}`);
    }
  }
  return order;
}

/** Which coordinate labels a square shows: rank on the left edge, file on the bottom edge. */
export function coordinates(square, bottom) {
  const order = displayOrder(bottom);
  const index = order.indexOf(square);
  const row = Math.floor(index / 8);
  const col = index % 8;
  return { rank: col === 0 ? square[1] : "", file: row === 7 ? square[0] : "" };
}

/** Moves in `legal` that start on `from`, grouped by destination. */
export function targetsFrom(legal, from) {
  const targets = new Map();
  for (const uci of legal || []) {
    if (uci.slice(0, 2) !== from) continue;
    const to = uci.slice(2, 4);
    if (!targets.has(to)) targets.set(to, []);
    targets.get(to).push(uci);
  }
  return targets;
}

/** The legal UCI strings for from→to: one plain move, four promotions, or none. */
export function movesBetween(legal, from, to) {
  return (legal || []).filter((uci) => uci.slice(0, 4) === `${from}${to}`);
}

export function needsPromotion(candidates) {
  return candidates.length > 0 && candidates.every((uci) => uci.length === 5);
}

export function kingSquare(pieces, colour) {
  const wanted = colour === "white" ? "K" : "k";
  for (const [square, piece] of pieces) {
    if (piece === wanted) return square;
  }
  return null;
}

/** Arrow-key navigation in display space (so "up" is always up on screen). */
export function neighbour(square, key, bottom) {
  const order = displayOrder(bottom);
  const index = order.indexOf(square);
  if (index === -1) return square;
  let row = Math.floor(index / 8);
  let col = index % 8;
  if (key === "ArrowUp") row = Math.max(0, row - 1);
  else if (key === "ArrowDown") row = Math.min(7, row + 1);
  else if (key === "ArrowLeft") col = Math.max(0, col - 1);
  else if (key === "ArrowRight") col = Math.min(7, col + 1);
  else if (key === "Home") col = 0;
  else if (key === "End") col = 7;
  return order[row * 8 + col];
}

/** Square names involved in a UCI move, for last-move tinting. */
export function moveSquares(uci) {
  return uci ? [uci.slice(0, 2), uci.slice(2, 4)] : [];
}

/** Placement after a move, for the faded "Sending…" preview only (B4). Not a rules engine. */
export function previewMove(pieces, uci) {
  const next = new Map(pieces);
  const from = uci.slice(0, 2);
  const to = uci.slice(2, 4);
  const piece = next.get(from);
  if (!piece) return next;
  next.delete(from);
  const promo = uci[4];
  next.set(to, promo ? (pieceColour(piece) === "white" ? promo.toUpperCase() : promo) : piece);
  return next;
}
