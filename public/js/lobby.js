// Lobby page: name box, head-to-head, new game, game lists and email settings
// (docs/ui-spec.md §3). No WebSocket here; the lists refresh when the page is shown again.

import { api, isSignedOut } from "./api.js";
import {
  CAUSES,
  COOLDOWN_STEPS,
  capitalise,
  cooldownLabel,
  moveNumber,
  other,
  relativeTime,
  resultFor,
  shortDate,
  stepCooldown,
  validateName,
} from "./format.js";

const $ = (id) => document.getElementById(id);

const page = {
  me: null,
  stats: null,
  games: null,
  colour: "random",
  creating: false,
  savingPrefs: false,
  loading: false,
  signedOut: false,
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function opponentKey() {
  return page.me ? (page.me.player === "harry" ? "partner" : "harry") : null;
}

function opponentName() {
  const key = opponentKey();
  return (page.stats && key && page.stats.names[key]) || "your opponent";
}

// --------------------------------------------------------------------- name

function renderName() {
  const input = $("name-input");
  const save = $("name-save");
  if (!page.me) return;
  input.disabled = false;
  const changed = input.value.trim() !== page.me.name;
  save.disabled = !changed;
  $("me-chip").hidden = false;
  $("me-chip").textContent = page.me.name;
}

function setupName() {
  const input = $("name-input");
  input.addEventListener("input", () => {
    $("name-saved").hidden = true;
    $("name-error").hidden = true;
    input.removeAttribute("aria-invalid");
    renderName();
  });
  $("name-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = validateName(input.value);
    if (name === null) {
      $("name-error").textContent = "Names need 1–24 characters.";
      $("name-error").hidden = false;
      input.setAttribute("aria-invalid", "true");
      return;
    }
    $("name-save").disabled = true;
    try {
      page.me = await api.updateMe({ name });
      input.value = page.me.name;
      $("name-saved").hidden = false;
      setTimeout(() => {
        $("name-saved").hidden = true;
      }, 2500);
      renderName();
      await refresh(); // names appear in the head-to-head and game lists
    } catch (error) {
      if (handleSignedOut(error)) return;
      const invalid = error.status === 400;
      $("name-error").textContent = invalid ? "Names need 1–24 characters." : "Couldn't save your name. Try again.";
      $("name-error").hidden = false;
      if (invalid) input.setAttribute("aria-invalid", "true");
      renderName();
    }
  });
}

// ------------------------------------------------------------- head to head

function renderStats() {
  if (!page.stats || !page.me) return;
  const me = page.me.player;
  const opp = opponentKey();
  const mine = page.stats.players[me];
  const theirs = page.stats.players[opp];
  $("h2h-me").textContent = String(mine.wins);
  $("h2h-opp").textContent = String(theirs.wins);
  $("h2h-draws").textContent = String(mine.draws);
  $("h2h-me-name").textContent = page.stats.names[me];
  $("h2h-opp-name").textContent = page.stats.names[opp];
}

// ----------------------------------------------------------------- new game

function renderNewGame() {
  for (const node of $("colour-choice").querySelectorAll("button")) {
    node.setAttribute("aria-pressed", String(node.dataset.colour === page.colour));
    node.disabled = page.creating;
  }
  const start = $("start");
  start.disabled = page.creating || !page.me;
  start.replaceChildren();
  if (page.creating) {
    const spinner = el("span", "spinner");
    spinner.setAttribute("aria-hidden", "true");
    start.append(spinner, document.createTextNode(" Starting…"));
  } else {
    start.textContent = "Start a new game";
  }
}

function setupNewGame() {
  $("colour-choice").addEventListener("click", (event) => {
    const choice = event.target.closest("button[data-colour]");
    if (!choice || page.creating) return;
    page.colour = choice.dataset.colour;
    renderNewGame();
  });
  $("start").addEventListener("click", async () => {
    if (page.creating) return;
    page.creating = true;
    $("start-error").hidden = true;
    renderNewGame();
    try {
      const created = await api.createGame(page.colour);
      window.location.assign(created.url);
    } catch (error) {
      page.creating = false;
      if (handleSignedOut(error)) return;
      $("start-error").hidden = false;
      renderNewGame();
    }
  });
}

// --------------------------------------------------------------- game lists

function sectionWithHeading(title, testId) {
  const section = el("section", "section");
  section.dataset.testid = testId;
  const heading = el("h2", "eyebrow", title);
  heading.id = `${testId}-heading`;
  section.setAttribute("aria-labelledby", heading.id);
  section.append(heading);
  return section;
}

function gameCard(game, yours, now) {
  const card = el("a", yours ? "game-card game-card--yours" : "game-card");
  card.href = `/game/${game.id}`;
  card.dataset.testid = "game-card";
  card.dataset.gameId = game.id;
  if (yours) {
    const dot = el("span", "game-card__dot");
    dot.setAttribute("aria-hidden", "true");
    card.append(dot);
  }
  const body = el("span", "game-card__body");
  const opp = game[other(game.you)].name;
  body.append(
    el("span", "game-card__title", `vs ${opp} · you're ${capitalise(game.you)}`),
    el("span", "game-card__meta", `Move ${moveNumber(game.ply)} · ${relativeTime(game.updated_at, now)}`),
  );
  card.append(body);
  card.append(el("span", yours ? "game-card__cta" : "game-card__cta game-card__cta--theirs", yours ? "Play" : "Their move"));
  return card;
}

function finishedRow(game) {
  const row = el("li", "finished-row");
  row.dataset.testid = "finished-row";
  const link = el("a", "finished-row__text");
  link.href = `/game/${game.id}`;
  const result = el("strong", "", resultFor(game));
  link.append(result, document.createTextNode(` · ${CAUSES[game.status] || game.status} · ${shortDate(game.updated_at)}`));
  link.setAttribute("aria-label", `${resultFor(game)} against ${game[other(game.you)].name}, ${CAUSES[game.status] || game.status}, ${shortDate(game.updated_at)}`);
  const pgn = el("a", "finished-row__pgn", "PGN");
  pgn.href = `/api/games/${game.id}/pgn`;
  pgn.setAttribute("download", "");
  pgn.setAttribute("aria-label", `Download PGN, ${shortDate(game.updated_at)}`);
  row.append(link, pgn);
  return row;
}

function renderGames() {
  const box = $("games");
  if (page.games === null) return;
  box.setAttribute("aria-busy", "false");
  box.replaceChildren();
  const now = Date.now();
  const active = page.games.filter((g) => g.status === "active");
  const finished = page.games.filter((g) => g.status !== "active");
  const yours = active.filter((g) => g.your_turn);
  const theirs = active.filter((g) => !g.your_turn);

  if (page.games.length === 0) {
    const empty = el("p", "empty", "No games yet. Start one and it'll appear here for both of you.");
    empty.dataset.testid = "empty";
    box.append(empty);
    return;
  }
  const wrapper = el("div", "section");
  if (yours.length) {
    const section = sectionWithHeading("Your move", "your-move");
    for (const game of yours) section.append(gameCard(game, true, now));
    wrapper.append(section);
  }
  if (theirs.length) {
    const section = sectionWithHeading(`Waiting for ${opponentName()}`, "waiting");
    for (const game of theirs) section.append(gameCard(game, false, now));
    wrapper.append(section);
  }
  if (finished.length) {
    const section = sectionWithHeading("Finished", "finished");
    const list = el("ul", "finished-list");
    for (const game of finished) list.append(finishedRow(game));
    section.append(list);
    wrapper.append(section);
  }
  box.append(wrapper);
}

// ------------------------------------------------------------------ emails

function renderPrefs() {
  if (!page.me) return;
  const notify = page.me.notify;
  const busy = page.savingPrefs;
  const invites = $("invites");
  const yourMove = $("your-move");
  invites.setAttribute("aria-checked", String(notify.invites));
  yourMove.setAttribute("aria-checked", String(notify.your_move));
  invites.disabled = busy;
  yourMove.disabled = busy;
  const gapOn = notify.your_move;
  $("gap-row").classList.toggle("stepper-row--disabled", !gapOn);
  $("gap-value").textContent = cooldownLabel(notify.cooldown_minutes);
  const index = COOLDOWN_STEPS.indexOf(notify.cooldown_minutes);
  $("gap-down").disabled = busy || !gapOn || index <= 0;
  $("gap-up").disabled = busy || !gapOn || index >= COOLDOWN_STEPS.length - 1;
}

async function savePrefs(notify) {
  if (page.savingPrefs || !page.me) return;
  const before = page.me;
  page.me = { ...page.me, notify: { ...page.me.notify, ...notify } }; // show the change at once
  page.savingPrefs = true;
  $("mail-error").hidden = true;
  renderPrefs();
  try {
    page.me = await api.updateMe({ notify });
  } catch (error) {
    page.me = before;
    if (!handleSignedOut(error)) $("mail-error").hidden = false;
  } finally {
    page.savingPrefs = false;
    renderPrefs();
  }
}

function setupPrefs() {
  $("invites").addEventListener("click", () => savePrefs({ invites: !page.me.notify.invites }));
  $("your-move").addEventListener("click", () => savePrefs({ your_move: !page.me.notify.your_move }));
  $("gap-down").addEventListener("click", () =>
    savePrefs({ cooldown_minutes: stepCooldown(page.me.notify.cooldown_minutes, -1) }),
  );
  $("gap-up").addEventListener("click", () =>
    savePrefs({ cooldown_minutes: stepCooldown(page.me.notify.cooldown_minutes, 1) }),
  );
}

// ------------------------------------------------------------------ loading

function handleSignedOut(error) {
  if (!isSignedOut(error)) return false;
  $("load-error").hidden = false;
  $("load-error-text").textContent = "You've been signed out.";
  $("retry").textContent = "Sign in";
  page.signedOut = true;
  return true;
}

async function refresh() {
  if (page.loading) return;
  page.loading = true;
  try {
    const [me, stats, games] = await Promise.all([api.me(), api.stats(), api.games()]);
    const previousName = page.me ? page.me.name : null;
    page.me = me;
    page.stats = stats;
    page.games = games.games;
    $("load-error").hidden = true;
    const input = $("name-input");
    // Keep anything the player has typed but not saved yet.
    if (previousName === null || input.value.trim() === previousName) input.value = me.name;
    renderName();
    renderStats();
    renderNewGame();
    renderGames();
    renderPrefs();
  } catch (error) {
    if (!handleSignedOut(error)) {
      $("load-error").hidden = false;
      $("load-error-text").textContent = "Couldn't load your games.";
    }
  } finally {
    page.loading = false;
  }
}

function main() {
  setupName();
  setupNewGame();
  setupPrefs();
  $("retry").addEventListener("click", () => {
    if (page.signedOut) window.location.reload();
    else refresh();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refresh();
  });
  // Coming back with the Back button can restore this page from the bfcache.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) refresh();
  });
  refresh();
}

main();
