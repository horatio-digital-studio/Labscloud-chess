// Game page controller: renders the latest server `state` and sends player actions.
// Everything shown comes from the most recent state (REQ-UI-14); the only local
// display is the faded "Sending…" preview of a move awaiting its reply (B4).

import { api, isSignedOut } from "./api.js";
import { BoardView } from "./board.js";
import { moveSquares } from "./board-model.js";
import { capitalise, other, pairMoves, spokenSan, statusLine, toastFor } from "./format.js";
import { GameSocket } from "./socket.js";
import { play, setSoundEnabled, soundEnabled, unlockAudio, vibrate } from "./sound.js";

const PENDING_TIMEOUT_MS = 8000;
const RESIGN_CONFIRM_MS = 4000;
const TOAST_MS = 3000;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const $ = (id) => document.getElementById(id);

const page = {
  gameId: null,
  state: null,
  connection: "connecting",
  attempts: 0,
  pending: null, // { uci, ply } of a move sent but not yet answered (B4)
  pendingTimer: null,
  resignArmed: false,
  resignTimer: null,
  socket: null,
  board: null,
  wakeLock: null,
  promotionOpen: false,
};

// ------------------------------------------------------------------- helpers

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(label, className, onClick, options = {}) {
  const node = el("button", className, label);
  node.type = "button";
  if (options.testId) node.dataset.testid = options.testId;
  if (options.disabled) node.disabled = true;
  node.addEventListener("click", onClick);
  return node;
}

function toast(text) {
  const node = el("div", "toast", text);
  $("toasts").append(node);
  setTimeout(() => node.remove(), TOAST_MS);
}

function announce(text) {
  const region = $("announcer");
  region.textContent = "";
  // A fresh text node after clearing makes screen readers repeat identical moves too.
  setTimeout(() => {
    region.textContent = text;
  }, 50);
}

function flipKey() {
  return `labscloud-chess:flip:${page.gameId}`;
}

function isFlipped() {
  try {
    return localStorage.getItem(flipKey()) === "1";
  } catch (error) {
    return false;
  }
}

function setFlipped(flipped) {
  try {
    if (flipped) localStorage.setItem(flipKey(), "1");
    else localStorage.removeItem(flipKey());
  } catch (error) {
    // the flip just won't be remembered
  }
}

function live() {
  return page.connection === "live";
}

function send(message) {
  if (!page.socket || !live() || !page.socket.send(message)) {
    toast("Not connected — try again in a moment.");
    return false;
  }
  return true;
}

// -------------------------------------------------------------------- render

function renderConnection() {
  const pill = $("conn");
  const text = $("conn-text");
  pill.className = "pill";
  pill.disabled = true;
  if (page.connection === "live") {
    pill.classList.add("pill--live");
    text.textContent = "Live";
  } else if (page.connection === "reconnecting") {
    pill.classList.add("pill--reconnecting");
    text.textContent = page.attempts > 3 ? `Reconnecting… (${page.attempts})` : "Reconnecting…";
  } else if (page.connection === "signedout") {
    pill.classList.add("pill--signedout");
    pill.disabled = false;
    text.textContent = "Signed out — tap to reload";
  } else {
    text.textContent = "Connecting…";
  }
}

function hasOwnMove(state) {
  // White has a move once ply ≥ 1, Black once ply ≥ 2.
  return state.you === "white" ? state.ply >= 1 : state.ply >= 2;
}

function renderStrips(state) {
  const you = state.you;
  const opp = other(you);
  const me = state.players[you];
  const them = state.players[opp];
  $("me-name").textContent = me.name;
  $("me-colour").textContent = capitalise(you);
  $("me-avatar").textContent = Array.from(me.name)[0] || "?";
  $("opp-name").textContent = them.name;
  $("opp-colour").textContent = capitalise(opp);
  $("opp-avatar").textContent = Array.from(them.name)[0] || "?";
  const online = Boolean(state.online && state.online[opp]);
  $("opp-presence").classList.toggle("presence--online", online);
  $("opp-presence-text").textContent = online ? "online" : "offline";

  const badge = $("turn-badge");
  const status = $("status");
  const active = state.status === "active";
  badge.hidden = true;
  status.hidden = true;
  if (page.pending) {
    badge.hidden = false;
    badge.textContent = "Sending…";
  } else if (page.promotionOpen) {
    badge.hidden = false;
    badge.textContent = "Choose a piece";
  } else if (active && state.turn === you) {
    badge.hidden = false;
    badge.textContent = statusLine(state);
  } else {
    status.hidden = false;
    status.textContent = statusLine(state);
  }
}

function renderMoves(state) {
  const list = $("moves");
  list.replaceChildren();
  const pairs = pairMoves(state.moves);
  if (pairs.length === 0) {
    list.append(el("li", "moves__empty", "No moves yet"));
    return;
  }
  const lastIndex = state.moves.length - 1;
  pairs.forEach((pair, index) => {
    const item = el("li", "moves__pair");
    const isLastPair = index === pairs.length - 1;
    if (isLastPair) item.classList.add("moves__pair--current");
    item.append(document.createTextNode(`${pair.number}. `));
    const white = el("span", "moves__san", pair.white);
    if (lastIndex === index * 2) white.classList.add("moves__san--last");
    item.append(white);
    if (pair.black) {
      item.append(document.createTextNode(" "));
      const black = el("span", "moves__san", pair.black);
      if (lastIndex === index * 2 + 1) black.classList.add("moves__san--last");
      item.append(black);
    }
    list.append(item);
  });
  list.scrollLeft = list.scrollWidth;
}

function banner(text, actions = [], testId = undefined) {
  const node = el("div", "banner");
  if (testId) node.dataset.testid = testId;
  node.append(el("span", "banner__text", text));
  if (actions.length) {
    const box = el("div", "banner__actions");
    box.append(...actions);
    node.append(box);
  }
  return node;
}

function renderBanners(state) {
  const box = $("banners");
  box.replaceChildren();
  const you = state.you;
  const opp = other(you);
  const oppName = state.players[opp].name;
  const canAct = live() && !page.pending;
  const small = "btn btn--small";

  if (state.status === "active") {
    if (state.draw_offer_from === opp) {
      box.append(
        banner(
          `${oppName} offers a draw`,
          [
            button("Accept", `${small} btn--outline-accent`, () => send({ type: "draw_accept" }), {
              disabled: !canAct,
              testId: "draw-accept",
            }),
            button("Decline", small, () => send({ type: "draw_decline" }), {
              disabled: !canAct,
              testId: "draw-decline",
            }),
          ],
          "draw-offer",
        ),
      );
    } else if (state.draw_offer_from === you) {
      box.append(banner("Draw offered — waiting", [], "draw-offered"));
    }
    if (state.takeback_from === opp) {
      box.append(
        banner(
          `${oppName} wants to take back their last move`,
          [
            button("Allow", `${small} btn--outline-accent`, () => send({ type: "takeback_accept" }), {
              disabled: !canAct,
              testId: "takeback-accept",
            }),
            button("Decline", small, () => send({ type: "takeback_decline" }), {
              disabled: !canAct,
              testId: "takeback-decline",
            }),
          ],
          "takeback-offer",
        ),
      );
    } else if (state.takeback_from === you) {
      box.append(banner(`Takeback requested — waiting for ${oppName}`, [], "takeback-requested"));
    }
    if (state.can_claim_draw) {
      box.append(
        banner(
          "You can claim a draw (repetition / 50 moves)",
          [
            button("Claim draw", `${small} btn--outline-accent`, () => send({ type: "claim_draw" }), {
              disabled: !canAct,
              testId: "claim-draw",
            }),
          ],
          "claim",
        ),
      );
    }
    return;
  }

  const rematch = state.rematch;
  if (rematch.game_id) {
    const link = el("a", `${small} btn--outline-accent`, "Open rematch");
    link.href = `/game/${rematch.game_id}`;
    box.append(banner("Rematch ready", [link], "rematch-ready"));
  } else if (rematch[you] && !rematch[opp]) {
    box.append(banner(`Rematch requested — waiting for ${oppName}`, [], "rematch-requested"));
  } else if (rematch[opp] && !rematch[you]) {
    box.append(
      banner(
        `${oppName} wants a rematch`,
        [
          button("Rematch", `${small} btn--outline-accent`, () => send({ type: "rematch" }), {
            disabled: !canAct,
            testId: "rematch-accept",
          }),
        ],
        "rematch-offer",
      ),
    );
  }
}

const ICON_TAKEBACK =
  '<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 14L4 9l5-5"></path><path d="M4 9h10a6 6 0 010 12h-2"></path></svg>';
const ICON_FLAG =
  '<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 21V4"></path><path d="M5 4h11l-2 4 2 4H5"></path></svg>';

function iconButton(icon, label, className, onClick, options) {
  const node = button("", className, onClick, options);
  const holder = document.createElement("span");
  holder.className = "actions__icon";
  holder.setAttribute("aria-hidden", "true");
  // Static, trusted SVG markup defined in this file.
  holder.innerHTML = icon;
  node.append(holder, document.createTextNode(label));
  return node;
}

function disarmResign() {
  page.resignArmed = false;
  if (page.resignTimer) clearTimeout(page.resignTimer);
  page.resignTimer = null;
}

function onResign() {
  if (!page.resignArmed) {
    page.resignArmed = true;
    page.resignTimer = setTimeout(() => {
      disarmResign();
      render();
    }, RESIGN_CONFIRM_MS);
    render();
    return;
  }
  disarmResign();
  send({ type: "resign" });
  render();
}

function renderActions(state) {
  const box = $("actions");
  box.replaceChildren();
  const you = state.you;
  const canAct = live() && !page.pending;

  if (state.status === "active") {
    box.append(
      iconButton(ICON_TAKEBACK, "Takeback", "btn", () => send({ type: "takeback_request" }), {
        testId: "takeback",
        disabled: !canAct || state.takeback_from !== null || !hasOwnMove(state),
      }),
    );
    const draw = button("", "btn", () => send({ type: "draw_offer" }), {
      testId: "draw",
      disabled: !canAct || state.draw_offer_from !== null,
    });
    const half = el("span", "actions__half", "½");
    half.setAttribute("aria-hidden", "true");
    draw.append(half, document.createTextNode(" Offer draw"));
    draw.setAttribute("aria-label", "Offer draw");
    box.append(draw);
    box.append(
      iconButton(
        ICON_FLAG,
        page.resignArmed ? "Tap again to resign" : "Resign",
        "btn btn--danger",
        onResign,
        { testId: "resign", disabled: !canAct },
      ),
    );
    return;
  }

  disarmResign();
  const voted = state.rematch[you];
  box.append(
    button(voted ? "Rematch asked" : "Rematch", "btn btn--outline-accent", () => send({ type: "rematch" }), {
      testId: "rematch",
      disabled: !canAct || voted || Boolean(state.rematch.game_id),
    }),
  );
  const lobby = el("a", "btn", "Games");
  lobby.href = "/";
  box.append(lobby);
  const pgn = el("a", "btn", "PGN");
  pgn.href = `/api/games/${page.gameId}/pgn`;
  pgn.setAttribute("download", "");
  pgn.dataset.testid = "pgn";
  box.append(pgn);
}

function renderBoard(state) {
  const you = state.you;
  const bottom = isFlipped() ? other(you) : you;
  let takebackOutline = [];
  if (state.status === "active" && state.takeback_from === other(you) && state.moves.length) {
    // The requester's last move: the last one, or the one before if you've replied (B13a).
    const index = state.turn === state.takeback_from ? state.moves.length - 2 : state.moves.length - 1;
    if (index >= 0) takebackOutline = moveSquares(state.moves[index].uci);
  }
  page.board.update({
    fen: state.fen,
    you,
    bottom,
    legal: state.legal,
    lastMove: state.last_move ? state.last_move.uci : null,
    check: state.check,
    turn: state.turn,
    status: state.status,
    interactive: state.status === "active" && state.turn === you && live() && !page.pending,
    pending: page.pending ? page.pending.uci : null,
    outline: takebackOutline,
  });
}

function render() {
  // Banners and action buttons are rebuilt on each render; keep keyboard focus on the
  // same control (e.g. Resign → Enter → Enter) instead of dropping it to <body>.
  const focused = document.activeElement;
  const focusKey = focused && focused.dataset ? focused.dataset.testid : undefined;
  renderInner();
  if (focusKey && document.activeElement !== focused) {
    const again = document.querySelector(`[data-testid="${focusKey}"]`);
    if (again && !again.disabled) again.focus();
  }
}

function renderInner() {
  renderConnection();
  const state = page.state;
  if (!state) return;
  for (const id of ["opp-strip", "board-frame", "me-strip", "moves", "actions"]) $(id).hidden = false;
  $("loading").hidden = true;
  renderStrips(state);
  renderBoard(state);
  renderMoves(state);
  renderBanners(state);
  renderActions(state);
  document.title = `${statusLine(state)} · labscloud chess`;
}

// -------------------------------------------------------------------- events

function clearPending() {
  page.pending = null;
  if (page.pendingTimer) clearTimeout(page.pendingTimer);
  page.pendingTimer = null;
}

function onMove(uci) {
  const state = page.state;
  if (!state || page.pending) return;
  if (!send({ type: "move", uci, ply: state.ply })) return;
  page.pending = { uci, ply: state.ply };
  page.pendingTimer = setTimeout(() => {
    // No reply: the connection is probably dead. Resync from the server.
    clearPending();
    render();
    if (page.socket) page.socket.reconnectNow();
  }, PENDING_TIMEOUT_MS);
  render();
}

function soundFor(san) {
  if (!san) return "move";
  if (san.endsWith("+") || san.endsWith("#")) return "check";
  return san.includes("x") ? "capture" : "move";
}

function onState(next) {
  const previous = page.state;
  page.state = next;
  // A state at a different ply answers the pending move; one at the same ply (say the
  // opponent offered a draw meanwhile) doesn't, so keep "Sending…" until it's answered.
  if (page.pending && next.ply !== page.pending.ply) clearPending();
  if (previous && previous.game_id === next.game_id) {
    if (next.ply < previous.ply) {
      toast("Move taken back");
      page.board.clearSelection();
    } else if (next.ply === previous.ply + 1 && next.last_move) {
      const byOpponent = next.turn === next.you;
      if (byOpponent) {
        announce(`${next.players[other(next.you)].name}: ${spokenSan(next.last_move.san)}`);
        vibrate(60);
      }
      if (next.status === "active") play(soundFor(next.last_move.san));
    }
    if (previous.status === "active" && next.status !== "active") {
      play("end");
      vibrate([80, 60, 80]);
      announce(statusLine(next));
    }
  }
  render();
}

function onMessage(message) {
  switch (message.type) {
    case "state":
      onState(message);
      break;
    case "presence":
      if (page.state) {
        page.state = { ...page.state, online: message.online };
        render();
      }
      break;
    case "error":
      if (message.in_reply_to === "move") clearPending();
      toast(toastFor(message.code));
      if (message.code === "STALE_PLY") page.socket.send({ type: "hello" });
      if (message.code === "BAD_MESSAGE" || message.code === "INTERNAL") page.socket.reconnectNow();
      render();
      break;
    case "rematch_ready":
      if (message.game_id && UUID_RE.test(message.game_id)) {
        window.location.assign(`/game/${message.game_id}`);
      }
      break;
    default:
      break; // pong, or a newer message type this page doesn't know
  }
}

function onStatus(status, attempts) {
  page.connection = status;
  page.attempts = attempts;
  if (status !== "live") clearPending();
  render();
}

async function onRepeatedFailure() {
  try {
    await api.me();
  } catch (error) {
    if (isSignedOut(error)) page.socket.signedOut();
  }
}

async function requestWakeLock() {
  try {
    if (!("wakeLock" in navigator) || document.visibilityState !== "visible") return;
    if (page.wakeLock && !page.wakeLock.released) return;
    page.wakeLock = await navigator.wakeLock.request("screen");
  } catch (error) {
    page.wakeLock = null; // not allowed right now (e.g. battery saver)
  }
}

function setupMenu() {
  const menuButton = $("menu-button");
  const menu = $("menu");
  const close = () => {
    menu.hidden = true;
    menuButton.setAttribute("aria-expanded", "false");
  };
  menuButton.addEventListener("click", (event) => {
    event.stopPropagation();
    const open = menu.hidden;
    menu.hidden = !open;
    menuButton.setAttribute("aria-expanded", String(open));
    if (open) menu.querySelector(".menu__item").focus();
  });
  document.addEventListener("click", (event) => {
    if (!menu.hidden && !menu.contains(event.target)) close();
  });
  menu.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      close();
      menuButton.focus();
    }
  });
  const soundItem = $("menu-sound");
  const paintSound = () => {
    soundItem.textContent = soundEnabled() ? "Sound: on" : "Sound: off";
  };
  paintSound();
  soundItem.addEventListener("click", () => {
    setSoundEnabled(!soundEnabled());
    unlockAudio();
    paintSound();
    close();
  });
  $("menu-flip").addEventListener("click", () => {
    setFlipped(!isFlipped());
    close();
    render();
  });
  $("menu-pgn").href = `/api/games/${page.gameId}/pgn`;
  $("menu-pgn").addEventListener("click", close);
}

function showNotFound(detail) {
  $("loading").hidden = true;
  $("notfound").hidden = false;
  if (detail) $("notfound-detail").textContent = detail;
  document.title = "Game not found · labscloud chess";
}

async function main() {
  const match = window.location.pathname.match(/^\/game\/([^/]+)\/?$/);
  page.gameId = match ? decodeURIComponent(match[1]) : "";
  if (!UUID_RE.test(page.gameId)) {
    showNotFound();
    return;
  }
  page.board = new BoardView($("board"), $("board-frame"), {
    onMove,
    onPromotionOpen: (open) => {
      page.promotionOpen = open;
      if (page.state) renderStrips(page.state);
    },
  });
  setupMenu();
  // iOS only lets audio start inside a user gesture; unlock on the first touch or key
  // so a remembered "Sound: on" works after a reload (REQ-UI-09).
  const unlockOnGesture = () => {
    if (soundEnabled()) unlockAudio();
  };
  document.addEventListener("pointerdown", unlockOnGesture, { passive: true });
  document.addEventListener("keydown", unlockOnGesture);
  $("conn").addEventListener("click", () => {
    if (page.connection === "signedout") window.location.reload();
  });
  renderConnection();

  try {
    page.state = await api.game(page.gameId);
    render();
  } catch (error) {
    if (isSignedOut(error)) {
      page.connection = "signedout";
      renderConnection();
      $("loading").textContent = "You've been signed out. Tap the red button to sign in again.";
      return;
    }
    if (error.status === 404 || error.status === 403) {
      showNotFound(error.status === 403 ? "This isn't one of your games." : undefined);
      return;
    }
    // Otherwise carry on: the socket's hello will deliver the state.
  }

  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  page.socket = new GameSocket({
    url: `${scheme}://${window.location.host}/ws/games/${page.gameId}`,
    onMessage,
    onStatus,
    onRepeatedFailure,
  });
  page.socket.start();

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      page.socket.wake();
      requestWakeLock();
    }
  });
  window.addEventListener("online", () => page.socket.wake());
  window.addEventListener("pagehide", () => {
    if (page.wakeLock) page.wakeLock.release().catch(() => {});
  });
  requestWakeLock();
}

main();
