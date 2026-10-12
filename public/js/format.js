// Pure text helpers shared by the lobby and game pages. No DOM access, so node:test can
// import this file directly (tests/js/format.test.mjs).

export const COOLDOWN_STEPS = [5, 10, 15, 30, 45, 60, 120, 240, 480, 720, 1440];
export const NAME_MAX = 24;

/** Toast copy for server error codes (docs/ui-spec.md §6). */
export const ERROR_TOASTS = {
  NOT_YOUR_TURN: "It's not your move yet.",
  STALE_PLY: "The board was out of date — refreshed.",
  ILLEGAL_MOVE: "That move isn't allowed.",
  BAD_FORMAT: "That move isn't allowed.",
  GAME_OVER: "This game has finished.",
  CANNOT_CLAIM: "You can't claim a draw right now.",
  DRAW_ALREADY_OFFERED: "You've already offered a draw.",
  NO_DRAW_OFFER: "There's no draw offer to answer.",
  OWN_DRAW_OFFER: "There's no draw offer to answer.",
  REMATCH_NOT_AVAILABLE: "Rematch is available when the game ends.",
  TAKEBACK_NOT_AVAILABLE: "There's no move of yours to take back yet.",
  TAKEBACK_ALREADY_REQUESTED: "A takeback is already waiting for an answer.",
  NO_TAKEBACK_REQUEST: "There's no takeback to answer.",
  OWN_TAKEBACK_REQUEST: "There's no takeback to answer.",
  BAD_MESSAGE: "Something went wrong — reconnecting.",
  INTERNAL: "Something went wrong — reconnecting.",
};

export function toastFor(code) {
  return ERROR_TOASTS[code] || "Something went wrong.";
}

/** Plain-English draw reasons (docs/ui-spec.md §4.3). */
export const DRAW_REASONS = {
  stalemate: "stalemate",
  insufficient_material: "not enough pieces to mate",
  seventyfive_moves: "75 moves without a capture or pawn move",
  fivefold_repetition: "same position five times",
  draw_claimed: "claimed",
  draw_agreed: "agreed",
};

/** Short cause labels for the lobby's Finished list. */
export const CAUSES = {
  checkmate: "checkmate",
  resigned: "resigned",
  stalemate: "stalemate",
  insufficient_material: "not enough pieces",
  seventyfive_moves: "75-move rule",
  fivefold_repetition: "repetition",
  draw_claimed: "claimed",
  draw_agreed: "agreed",
};

export const TERMINAL = new Set([
  "checkmate",
  "stalemate",
  "insufficient_material",
  "seventyfive_moves",
  "fivefold_repetition",
  "resigned",
  "draw_agreed",
  "draw_claimed",
]);

export function other(colour) {
  return colour === "white" ? "black" : "white";
}

export function capitalise(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/** Trimmed name, or null when it breaks the 1–24 character / no control character rule. */
export function validateName(raw) {
  if (typeof raw !== "string") return null;
  const name = raw.trim();
  const length = Array.from(name).length;
  // Python's len() counts code points, and so does Array.from().
  if (length < 1 || length > NAME_MAX) return null;
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f-\u009f]/.test(name)) return null;
  return name;
}

export function cooldownLabel(minutes) {
  if (minutes < 60) return `${minutes} min`;
  const hours = minutes / 60;
  return `${hours} h`;
}

/** Next step up or down the gap timer; stays put at either end. */
export function stepCooldown(current, direction) {
  let index = COOLDOWN_STEPS.indexOf(current);
  if (index === -1) index = COOLDOWN_STEPS.indexOf(30);
  const next = Math.min(COOLDOWN_STEPS.length - 1, Math.max(0, index + direction));
  return COOLDOWN_STEPS[next];
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function shortDate(epochMs) {
  const when = new Date(epochMs);
  return `${when.getDate()} ${MONTHS[when.getMonth()]}`;
}

function startOfDay(epochMs) {
  const when = new Date(epochMs);
  return new Date(when.getFullYear(), when.getMonth(), when.getDate()).getTime();
}

export function relativeTime(epochMs, nowMs) {
  const seconds = Math.max(0, Math.round((nowMs - epochMs) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes === 1 ? "1 minute ago" : `${minutes} minutes ago`;
  const hours = Math.floor(minutes / 60);
  const days = Math.round((startOfDay(nowMs) - startOfDay(epochMs)) / 86_400_000);
  if (days === 0) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return shortDate(epochMs);
}

/** "Move 7": the number of the move about to be played. */
export function moveNumber(ply) {
  return Math.floor(ply / 2) + 1;
}

/** Group SAN moves into numbered pairs for the move strip. */
export function pairMoves(moves) {
  const pairs = [];
  for (let index = 0; index < moves.length; index += 2) {
    pairs.push({
      number: index / 2 + 1,
      white: moves[index].san,
      black: index + 1 < moves.length ? moves[index + 1].san : null,
    });
  }
  return pairs;
}

const PIECE_WORDS = { K: "King", Q: "Queen", R: "Rook", B: "Bishop", N: "Knight" };
const PROMO_WORDS = { Q: "queen", R: "rook", B: "bishop", N: "knight" };

/** Screen-reader expansion of a SAN move: "Nf3+" → "Knight to f3, check". */
export function spokenSan(san) {
  if (!san) return "";
  let text = san;
  let suffix = "";
  if (text.endsWith("#")) {
    suffix = ", checkmate";
    text = text.slice(0, -1);
  } else if (text.endsWith("+")) {
    suffix = ", check";
    text = text.slice(0, -1);
  }
  if (text === "O-O") return `Castles kingside${suffix}`;
  if (text === "O-O-O") return `Castles queenside${suffix}`;
  let promotion = "";
  const promo = text.match(/=([QRBN])$/);
  if (promo) {
    promotion = `, promotes to ${PROMO_WORDS[promo[1]]}`;
    text = text.slice(0, -2);
  }
  const capture = text.includes("x");
  const target = text.slice(-2);
  const head = text.slice(0, -2).replace("x", "");
  let piece = "Pawn";
  let from = head;
  if (head && PIECE_WORDS[head[0]]) {
    piece = PIECE_WORDS[head[0]];
    from = head.slice(1);
  }
  const fromText = from ? ` from ${from}` : "";
  return `${piece}${fromText} ${capture ? "takes on" : "to"} ${target}${promotion}${suffix}`;
}

/** Lobby result from the viewer's side: "Won", "Lost" or "Draw". */
export function resultFor(game) {
  if (game.result === "1/2-1/2") return "Draw";
  if (!game.result) return "";
  const whiteWon = game.result === "1-0";
  return whiteWon === (game.you === "white") ? "Won" : "Lost";
}

function winnerColour(result) {
  if (result === "1-0") return "white";
  if (result === "0-1") return "black";
  return null;
}

/**
 * The status line under the board (docs/ui-spec.md §4.3), from the latest state only.
 * `names` maps colour → display name.
 */
export function statusLine(state) {
  const you = state.you;
  const opp = other(you);
  const oppName = state.players[opp].name;
  const status = state.status;
  if (status === "active") {
    if (state.turn === you) return state.check ? "Check — your move" : "Your move";
    return `${oppName}'s move`;
  }
  const winner = winnerColour(state.result);
  const winnerName = winner ? state.players[winner].name : "";
  if (status === "checkmate") {
    return winner === you ? "Checkmate — you win" : `Checkmate — ${winnerName} wins`;
  }
  if (status === "resigned") {
    const loser = other(winner);
    if (loser === you) return `You resigned — ${winnerName} wins`;
    return `${state.players[loser].name} resigned — ${winner === you ? "you win" : `${winnerName} wins`}`;
  }
  return `Draw — ${DRAW_REASONS[status] || status}`;
}

/** Reconnect delay for attempt n (0-based): 0.5, 1, 2, 4, 8, 8… seconds ±20 % (REQ-UI-07). */
export function backoffDelay(attempt, random = Math.random) {
  const base = Math.min(8000, 500 * 2 ** Math.max(0, attempt));
  const jitter = 1 + (random() * 0.4 - 0.2);
  return Math.round(base * jitter);
}
