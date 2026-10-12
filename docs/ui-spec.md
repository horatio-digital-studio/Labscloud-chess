# UI specification — labscloud-chess

**Status:** v1.1 — 12 October 2026. Visual direction: **option A "Clubroom"** (§7). This document is the source for states and behaviour.
**Principle:** every screen state below is reachable in an e2e test, and the page only ever renders what the latest server `state` says (REQ-UI-14). Most UI bugs are unhandled states, so this document lists them all.
**Primary device:** iPhone in portrait, in Safari, with FaceTime picture-in-picture floating over a corner. Desktop must also work.

---

## 1. Screens

| Route | Screen | Served by |
|---|---|---|
| (Access) | Cloudflare login: enter email → PIN | Cloudflare (not ours) |
| `/` | Lobby | `index.html` |
| `/game/{id}` | Board | `game.html` (Worker serves it after JWT check) |
| `/diag` | Diagnostics (staging only, S-04) | Worker |

No other pages. Errors are shown in-page, not on separate error pages.

## 2. Layout rules (all screens)

- Mobile-first, single column. Must work from **320 px to 430 px** wide in portrait without horizontal scroll, and scale up to desktop with the board capped at ~640 px (REQ-UI-10).
- Respect `env(safe-area-inset-*)` on all sides.
- **FaceTime PiP:** it can sit in any corner and usually covers ~110 × 160 px. Keep tap targets that matter out of the four 120 × 170 px corner zones; the top bar's corners hold only non-essential items (title, connection pill can be overlapped briefly).
- Tap targets ≥ 44 × 44 px. No hover-only behaviour.
- Self-hosted fonts only (no third-party requests; REQ-NFR-08). One accent colour (brass). Option A is a dark design, so there is one theme for both `prefers-color-scheme` values (decided 12 Oct 2026 with the choice of A).
- All copy in British English.

## 3. Lobby (`/`)

### 3.1 Wireframe (390 px)

```text
┌────────────────────────────────────┐
│ ♞ labscloud chess          Harry ▾│  top bar (name opens settings sheet)
├────────────────────────────────────┤
│  Your name [ Harry          ] Save │  name box (REQ-GAME-09)
│  Harry 4 · 1 · 3 Partner           │  head-to-head: wins · draws · wins
│                                    │
│  ┌──────────────────────────────┐  │
│  │       + New game             │  │  primary button
│  └──────────────────────────────┘  │
│                                    │
│  YOUR MOVE                         │
│  ┌──────────────────────────────┐  │
│  │ ● vs Partner · you're White  │  │  dot = your turn
│  │   Move 7 · 2 min ago         │  │
│  └──────────────────────────────┘  │
│  WAITING FOR PARTNER               │
│  ┌──────────────────────────────┐  │
│  │   vs Partner · you're Black  │  │
│  │   Move 12 · yesterday        │  │
│  └──────────────────────────────┘  │
│  FINISHED                          │
│  │ Won · checkmate · 12 Oct  PGN │  │
│  │ Draw · agreed · 11 Oct    PGN │  │
└────────────────────────────────────┘
```

### 3.2 New game

Inline on the lobby (option A puts it there instead of a bottom sheet): heading "New game — you play", a segmented control **White** / **Random** / **Black** (Random pre-selected), then the primary button **Start a new game**. On success, navigate to `/game/{id}`.

### 3.3 States

| ID | State | Shown |
|---|---|---|
| L1 | Loading | Skeleton rows; New game disabled |
| L2 | Empty (no games ever) | "No games yet. Start one and it'll appear here for both of you." + New game |
| L3 | Has active games | Sections *Your move* then *Waiting for {opponent}*, each newest first |
| L4 | Has finished games | *Finished* section: result from your point of view (Won / Lost / Draw), cause, date, PGN link |
| L5 | Load error | Inline banner "Couldn't load your games." + Retry; existing content kept if any |
| L6 | Create in progress | Start game button shows spinner, sheet locked |
| L7 | Create failed | Sheet stays open with "Couldn't start the game. Try again." |
| L8 | Emails card (Phase 6) | Switch "Email me when I'm invited"; switch "Email me when it's my move"; **gap timer** for move emails with − / + steps 5, 10, 15, 30, 45 min, 1, 2, 4, 8, 12, 24 h (default 30 min). The timer is greyed out and inert while the move-email switch is off. Changes save immediately (REQ-NOTIFY-06). |
| L9 | Name box | Text field prefilled with the current display name + Save. Save is disabled until the text changes. 1–24 characters after trimming; an invalid name shows "Names need 1–24 characters." under the field. Saved → brief "Saved" confirmation; the new name shows on boards after the other player refreshes (REQ-GAME-09). |

The lobby refreshes its list when the page becomes visible again (no WebSocket on the lobby).

## 4. Board (`/game/{id}`)

### 4.1 Wireframe (390 px, you are Black)

```text
┌────────────────────────────────────┐
│ ‹ Lobby        ● Live      ⋯ menu │  top bar: back, connection pill, menu
├────────────────────────────────────┤
│ ♔ Harry (White)        ● online   │  opponent strip
│ ┌────────────────────────────────┐ │
│ │                                │ │
│ │         8 × 8 board            │ │  full width, square
│ │   (Black at the bottom)        │ │
│ │                                │ │
│ └────────────────────────────────┘ │
│ ♚ You (Black)          Your move  │  your strip + turn indicator
├────────────────────────────────────┤
│ 1. e4 e5  2. Nf3 Nc6  3. Bb5 a6 ▸ │  move list, horizontal scroll, latest visible
├────────────────────────────────────┤
│ [ Takeback ] [ Offer draw ] [Resign]│  action bar (bottom, away from top corners)
└────────────────────────────────────┘
```
Menu (⋯): Flip board, Sound on/off, Download PGN.

### 4.2 Connection pill (REQ-UI-06)

| Client socket state | Pill | Input |
|---|---|---|
| `connecting` (first load) | grey "Connecting…" | disabled |
| `open` + synced (received `state`) | green "Live" | enabled per turn |
| `reconnecting` | amber "Reconnecting…" + attempt count after 3 | disabled |
| `closed` after 1008 | red "Signed out — tap to reload" | disabled |

### 4.3 Game states

| ID | Condition (from `state`) | Board | Status line | Actions |
|---|---|---|---|---|
| B1 | `active`, `turn == you`, not in check | interactive; legal targets shown on select | "Your move" | Takeback, Offer draw, Resign |
| B2 | `active`, `turn == you`, `check` | interactive; king square red | "Check — your move" | Takeback, Offer draw, Resign |
| B3 | `active`, `turn != you` | read-only; you may still select to look | "{Opponent}'s move" | Takeback, Offer draw, Resign |
| B4 | Move sent, awaiting reply | piece shown moved, faded; input locked | "Sending…" | none |
| B5 | `draw_offer_from == opponent` | as B1/B3 | banner "{Opponent} offers a draw" | **Accept**, **Decline** (in banner) |
| B6 | `draw_offer_from == you` | as B1/B3 | banner "Draw offered — waiting" | Offer draw disabled |
| B7 | `can_claim_draw` | as B1 | banner "You can claim a draw (repetition / 50 moves)" | **Claim draw** |
| B8 | Opponent offline (`online[opp] == false`) | as is | grey dot + "offline" on opponent strip | — |
| B9 | Promotion pending | board dims; picker over the promotion square | "Choose a piece" | Q, R, B, N, cancel (tap outside) |
| B10 | Terminal: `checkmate` | read-only; mated king red | "Checkmate — {Winner} wins" / "Checkmate — you win" | Rematch, Back to lobby, PGN |
| B11 | Terminal: `stalemate`, `insufficient_material`, `seventyfive_moves`, `fivefold_repetition`, `draw_claimed`, `draw_agreed` | read-only | "Draw — {plain-English reason}" | Rematch, Back to lobby, PGN |
| B12 | Terminal: `resigned` | read-only | "{Name} resigned — {Winner} wins" | Rematch, Back to lobby, PGN |
| B13 | `takeback_from == you` | as B1/B3 | banner "Takeback requested — waiting for {opponent}" | Takeback disabled |
| B13a | `takeback_from == opponent` | as B1/B3; their last move outlined | banner "{Opponent} wants to take back their last move" | **Allow**, **Decline** (in banner) |
| B13b | Takeback accepted | board returns to the earlier position; move list shortens | toast "Move taken back" | — |
| B14 | Rematch voted by you only | — | "Rematch requested — waiting for {opponent}" | — |
| B15 | Rematch voted by opponent only | — | banner "{Opponent} wants a rematch" | **Rematch** |
| B16 | `rematch_ready` received | navigate to new game | — | — |
| B17 | Server `error` | state unchanged; board resyncs | toast with friendly text (§6) for 3 s | — |
| B18 | Game not found (404) | none | "This game doesn't exist." | Back to lobby |

Plain-English draw reasons: stalemate → "stalemate"; insufficient_material → "not enough pieces to mate"; seventyfive_moves → "75 moves without a capture or pawn move"; fivefold_repetition → "same position five times"; draw_claimed → "claimed"; draw_agreed → "agreed".

### 4.4 Interaction rules

- **Tap-tap:** tap your piece → it highlights and its legal targets show as dots (captures as rings) → tap a target to move. Tapping another of your pieces switches selection; tapping elsewhere clears it (REQ-UI-02/03).
- **Drag:** drag your piece; on drop, if `from+to` is in `legal` (any promotion suffix counts), move; otherwise snap back silently and send nothing.
- **Promotion:** if any legal move matches `from+to` with a suffix, show the picker (B9) and send the chosen `e7e8q` style move (REQ-UI-04).
- **Last move:** both squares tinted. **Check:** king square red (REQ-UI-05).
- **Resign:** first tap turns the button into "Tap again to resign" for 4 seconds (REQ-UI-11).
- **Flip:** local only, remembered per game on the device.
- **Optimistic display:** none beyond B4. The board changes only when a new `state` arrives; an `error` reverts B4.
- **Sounds (off by default, REQ-UI-09):** move, capture, check, game end. **Vibration** (Android/desktop where supported): opponent move and game end.
- **Wake lock (REQ-UI-08):** requested on load and on `visibilitychange` → visible; released on leaving.
- **Reconnect (REQ-UI-07):** back-off 0.5 s, 1 s, 2 s, 4 s, 8 s, 8 s… ±20% jitter; immediate attempt on `visibilitychange` → visible and on `online`; send `hello` on every connect.

### 4.5 Accessibility (REQ-UI-12)

- Board is a grid of buttons with labels like "e4, white knight". Arrow keys move focus; Enter/Space selects and moves.
- An ARIA live region announces opponent moves in SAN with a spoken expansion ("Knight to f3, check").
- Colour is never the only signal: check, last move and legal targets also differ in shape or outline.
- Contrast ≥ 4.5:1 for text.

## 5. Diagnostics page (`/diag`, staging only)

Button **Run CPU replay**. Shows progress (ply n/150), then a table: moves sent, errors, any `1102` responses, total time. A **Copy results** button for pasting into a GitHub issue.

## 6. Error copy

| Code | Toast text |
|---|---|
| `NOT_YOUR_TURN` | "It's not your move yet." |
| `STALE_PLY` | "The board was out of date — refreshed." (client then sends `hello`) |
| `ILLEGAL_MOVE`, `BAD_FORMAT` | "That move isn't allowed." |
| `GAME_OVER` | "This game has finished." |
| `CANNOT_CLAIM` | "You can't claim a draw right now." |
| `DRAW_ALREADY_OFFERED` | "You've already offered a draw." |
| `NO_DRAW_OFFER`, `OWN_DRAW_OFFER` | "There's no draw offer to answer." |
| `REMATCH_NOT_AVAILABLE` | "Rematch is available when the game ends." |
| `TAKEBACK_NOT_AVAILABLE` | "There's no move of yours to take back yet." |
| `TAKEBACK_ALREADY_REQUESTED` | "A takeback is already waiting for an answer." |
| `NO_TAKEBACK_REQUEST`, `OWN_TAKEBACK_REQUEST` | "There's no takeback to answer." |
| `BAD_MESSAGE`, `INTERNAL` | "Something went wrong — reconnecting." (client reconnects) |

## 7. Visual direction — Option A "Clubroom" (chosen 12 Oct 2026)

Harry chose option A from the four mock-ups (A Clubroom, B Midnight, C Broadsheet, D Sunday). The tokens below are the CSS custom properties at the top of `public/css/app.css`; change them there.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#22170f` | Page (walnut) |
| `--surface`, `--surface-2` | `#2f2117`, `#3b2a1d` | Cards, menus, banners |
| `--line`, `--line-strong` | `#4d3726`, `#6b4e35` | Borders |
| `--text`, `--muted` | `#f4ead8`, `#c9b79c` | Text |
| `--accent` / `--accent-ink` | `#d4a843` / `#22170f` | Brass: primary button, your-move badge, switches (dark text on brass) |
| `--link` | `#e2bd62` | Links |
| `--danger` / `--danger-line` | `#f0b3a0` / `#7a3a2a` | Resign |
| `--sq-light`, `--sq-dark` | `#f0d9b5`, `#b58863` | Board (a1 dark) |
| `--sq-last-light`, `--sq-last-dark` | `#f3e27a`, `#d5bd4f` | Last move (plus an inset outline) |
| `--sq-selected` | `#e3c45c` | Selected square (plus an inset outline) |
| `--sq-check` | `#e0654a` | King in check (radial glow plus a dashed ring) |
| `--board-frame` | `#5a3b22` | Frame around the board |

- **Fonts:** Cormorant Garamond 600/700 (headings, numbers), Source Sans 3 400/600/700 (body), and a 2.8 KB subset of Noto Sans Symbols 2 for the pieces. All self-hosted under `public/fonts/` (OFL; `LICENCES.txt`).
- **Pieces:** Unicode solid glyphs with U+FE0E. White pieces `#fdf8ee` with a 1.3 px `#3a2a1c` text stroke; black pieces `#21160e`.
- **Targets:** a 28 % dot for a quiet move; a 4 px ring for a capture.
- **Connection pill:** green "Live", amber "Reconnecting…", grey "Connecting…", red "Signed out — tap to reload".
