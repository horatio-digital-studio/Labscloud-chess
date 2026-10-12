# Email copy — labscloud-chess (Phase 6)

**Status:** v1 draft — 12 October 2026. Templates in `src/notify.py` must match this file; snapshot tests compare rendered output with these texts.

**Common rules**
- From: `labscloud chess <chess@labscloud.uk>`. Reply-To: none.
- Plain text is the source of truth; the HTML part is the same words with one button-style link and no images, tracking pixels or external CSS.
- One link per email, always to `{PUBLIC_URL}/…`.
- Placeholders: `{to_name}`, `{from_name}`, `{your_colour}` ("White"/"Black"), `{game_url}`, `{last_move_san}` (e.g. "12… Nxe4"), `{result_line}`, `{pgn}`, `{cooldown_minutes}`, `{public_url}`.
- British English. No exclamation-mark spam.

---

## 1. Invite (REQ-NOTIFY-01)

**Subject:** `{from_name} started a game — you're {your_colour}`

```text
Hi {to_name},

{from_name} has started a new game and you're playing {your_colour}.

Play: {game_url}

— labscloud chess
You're getting this because invite emails are on. Turn them off in the lobby settings.
```

## 2. Your move (REQ-NOTIFY-02)

**Subject:** `Your move against {from_name}`

```text
Hi {to_name},

{from_name} played {last_move_san}. It's your move.

Play: {game_url}

— labscloud chess
At most one of these every {cooldown_minutes} minutes. Change this in the lobby settings.
```

## 3. Game over (REQ-NOTIFY-03)

**Subject:** `Game over: {result_line}`

`{result_line}` examples: "Harry won by checkmate", "Draw by agreement", "{Name} resigned — Harry won", "Draw by stalemate".

```text
Hi {to_name},

{result_line}.

Rematch or review: {game_url}

Moves (PGN):
{pgn}

— labscloud chess
```

## 4. Snapshot fixtures

`tests/fixtures/emails/` holds one rendered `.txt` and `.html` per template using these fixed values: `to_name=Partner`, `from_name=Harry`, `your_colour=Black`, `game_url=https://chess-staging.labscloud.uk/game/7d3c9a2e-5b1f-4c8e-9a0d-2f6b8e1c4a77`, `last_move_san=1. e4`, `cooldown_minutes=30`, result "Harry won by checkmate" with the Scholar's-mate PGN from `docs/protocol.md` §2.7.
