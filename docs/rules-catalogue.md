# Rules catalogue — chess edge cases

**Purpose:** the authoritative list of rule situations the chess core must handle. Every row was **machine-verified against python-chess 1.11.2 on 12 October 2026** (55 positions, 9 wrapper cases, zero mismatches). The same data lives in `tests/fixtures/positions.py`, which the T-010/T-011 tests consume directly — this page is the human-readable view.

**How to read a row:** start from the FEN, apply any listed moves, then check the expectations. "after `x`" means: play move `x` from that position, then check the expectations that follow.

**Rules for changing this file:** add rows freely; never delete or weaken a row to make code pass (raise it with Harry instead). Regenerate both this page and `positions.py` from the same source so they cannot drift.

**Status vocabulary** matches `docs/protocol.md`: `active`, `checkmate`, `stalemate`, `insufficient_material`, `seventyfive_moves`, `fivefold_repetition`. Draw *claims* (threefold, fifty-move) never end the game by themselves; they make `can_claim_draw` true.


## Basics

| ID | Situation | Start FEN | Moves first | Expectations |
|---|---|---|---|---|
| A01 | Standard starting position | `rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1` | — | status=active; check=False; legal_count=20 |
| A02 | After 1.e4, Black to move | `rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1` | e2e4 | status=active; legal_count=20 |
| A03 | King in check from a rook on the back rank: only escapes allowed | `4k3/8/8/8/8/8/8/r3K3 w - - 0 1` | — | check=True; legal: `e1e2`, `e1d2`, `e1f2`; illegal: `e1d1`, `e1f1` |
| A04 | Absolutely pinned bishop cannot leave the pin line | `4k3/4r3/8/8/8/8/4B3/4K3 w - - 0 1` | — | check=False; illegal: `e2d3`, `e2f3` |
| A05 | Double check (rook + knight): only king moves are legal | `4k3/8/8/8/8/5n2/8/r3K3 w - - 0 1` | — | check=True; legal_count=2; legal: `e1e2`, `e1f2` |

## Castling

| ID | Situation | Start FEN | Moves first | Expectations |
|---|---|---|---|---|
| B01 | White can castle both sides | `r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1` | — | legal: `e1g1`, `e1c1` |
| B02 | Black can castle both sides | `r3k2r/8/8/8/8/8/8/4K3 b kq - 0 1` | — | legal: `e8g8`, `e8c8` |
| B03 | Cannot castle kingside through an attacked square (f1) | `5r1k/8/8/8/8/8/8/4K2R w K - 0 1` | — | illegal: `e1g1` |
| B04 | Cannot castle out of check | `4r2k/8/8/8/8/8/8/4K2R w K - 0 1` | — | check=True; illegal: `e1g1` |
| B05 | Cannot castle into check (g1 attacked) | `6rk/8/8/8/8/8/8/4K2R w K - 0 1` | — | illegal: `e1g1` |
| B06 | Queenside castling is legal even though b1 is attacked (king never crosses b1) | `1r5k/8/8/8/8/8/8/R3K3 w Q - 0 1` | — | legal: `e1c1` |
| B07 | Pieces between king and rook block castling | `r3k2r/8/8/8/8/8/8/RN2K1NR w KQkq - 0 1` | — | illegal: `e1g1`, `e1c1` |
| B08 | No castling rights in FEN means no castling even with pieces on home squares | `r3k2r/8/8/8/8/8/8/R3K2R w kq - 0 1` | — | illegal: `e1g1`, `e1c1` |
| B09 | Kingside right lost after the h1 rook moves away and back; queenside still allowed | `r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1` | h1h2 h8h7 h2h1 h7h8 | legal: `e1c1`; illegal: `e1g1` |
| B10 | All white rights lost after the king moves away and back | `r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1` | e1f1 e8f8 f1e1 f8e8 | illegal: `e1g1`, `e1c1`, `e8g8` |

## En passant

| ID | Situation | Start FEN | Moves first | Expectations |
|---|---|---|---|---|
| C01 | En passant available immediately after the double push (FEN ep square) | `4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1` | — | legal: `e5d6` |
| C02 | No ep square in FEN means the capture is not available | `4k3/8/8/3pP3/8/8/8/4K3 w - - 0 1` | — | illegal: `e5d6` |
| C03 | En passant created by an actual double push in the move list | `4k3/3p4/8/4P3/8/8/8/4K3 b - - 0 1` | d7d5 | legal: `e5d6` |
| C04 | En passant expires if not taken on the very next move | `4k3/3p4/8/4P3/8/8/8/4K3 b - - 0 1` | d7d5 e1e2 e8e7 | illegal: `e5d6` |
| C05 | Horizontal-pin trap: ep would remove both rank-5 pawns and expose the king | `8/8/8/K2pP2q/8/8/8/7k w - d6 0 1` | — | illegal: `e5d6` |
| C06 | Black captures en passant | `4k3/8/8/8/3pP3/8/8/4K3 b - e3 0 1` | — | legal: `d4e3` |

## Promotion

| ID | Situation | Start FEN | Moves first | Expectations |
|---|---|---|---|---|
| D01 | All four promotion pieces are legal; a bare a7a8 is not | `8/P7/8/8/8/8/8/k6K w - - 0 1` | — | legal: `a7a8q`, `a7a8r`, `a7a8b`, `a7a8n`; illegal: `a7a8` |
| D02 | Capture-promotion and push-promotion both available | `1r6/P7/8/8/8/8/8/k6K w - - 0 1` | — | legal: `a7b8q`, `a7a8q`, `a7b8n` |
| D03 | Underpromotion to a knight gives check | `8/1p3P1k/8/8/8/8/8/K7 w - - 0 1` | — | after `f7f8n` → check=True, status=active |
| D04 | Black promotes on rank 1 | `k6K/8/8/8/8/8/p7/8 b - - 0 1` | — | legal: `a2a1q`, `a2a1n`; illegal: `a2a1` |
| D05 | Promoting to a queen stalemates; promoting to a rook does not | `8/6P1/8/8/8/8/2K5/k7 w - - 0 1` | — | legal: `g7g8q`, `g7g8r` |

## Checkmate

| ID | Situation | Start FEN | Moves first | Expectations |
|---|---|---|---|---|
| E01 | Fool's mate (Black wins in 2) | `rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1` | f2f3 e7e5 g2g4 d8h4 | status=checkmate; result=0-1; check=True; legal_count=0 |
| E02 | Scholar's mate (White wins in 4) | `rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1` | e2e4 e7e5 d1h5 b8c6 f1c4 g8f6 h5f7 | status=checkmate; result=1-0; legal_count=0 |
| E03 | Back-rank mate delivered by Rd8 | `6k1/5ppp/8/8/8/8/8/3R2K1 w - - 0 1` | — | after `d1d8` → status=checkmate, result=1-0 |
| E04 | Smothered mate with Nf7 | `6rk/6pp/8/6N1/8/8/8/6K1 w - - 0 1` | — | after `g5f7` → status=checkmate, result=1-0 |
| E05 | Two-rook ladder mate | `k7/7R/8/8/8/8/8/6RK w - - 0 1` | — | after `g1g8` → status=checkmate, result=1-0 |
| E06 | Position loaded already in checkmate: no legal moves | `R5k1/5ppp/8/8/8/8/8/6K1 b - - 0 1` | — | status=checkmate; result=1-0; check=True; legal_count=0 |
| E07 | Checkmate on the move that also reaches halfmove clock 100 is still checkmate | `6k1/5ppp/8/8/8/8/8/3R2K1 w - - 99 80` | — | after `d1d8` → status=checkmate, result=1-0 |

## Stalemate

| ID | Situation | Start FEN | Moves first | Expectations |
|---|---|---|---|---|
| F01 | Queen stalemate: Black king h8, no legal moves, not in check | `7k/5Q2/6K1/8/8/8/8/8 b - - 0 1` | — | status=stalemate; result=1/2-1/2; check=False; legal_count=0 |
| F02 | King and pawn stalemate in the corner | `k7/P7/K7/8/8/8/8/8 b - - 0 1` | — | status=stalemate; result=1/2-1/2; legal_count=0 |
| F03 | Careless Qf7 stalemates instead of mating | `7k/8/5QK1/8/8/8/8/8 w - - 0 1` | — | after `f6f7` → status=stalemate, result=1/2-1/2 |
| F04 | Promoting to a queen stalemates (see D05) | `8/6P1/8/8/8/8/2K5/k7 w - - 0 1` | — | after `g7g8q` → status=stalemate, result=1/2-1/2 |
| F05 | Promoting to a rook instead keeps the game going (see D05) | `8/6P1/8/8/8/8/2K5/k7 w - - 0 1` | — | after `g7g8r` → status=active, result=— |

## Insufficient material

| ID | Situation | Start FEN | Moves first | Expectations |
|---|---|---|---|---|
| G01 | King v king | `8/8/8/4k3/8/8/8/4K3 w - - 0 1` | — | status=insufficient_material; result=1/2-1/2 |
| G02 | King and bishop v king | `8/8/8/4k3/8/8/2B5/4K3 w - - 0 1` | — | status=insufficient_material; result=1/2-1/2 |
| G03 | King and knight v king | `8/8/8/4k3/8/8/2N5/4K3 w - - 0 1` | — | status=insufficient_material; result=1/2-1/2 |
| G04 | Same-coloured bishops (both dark squares) is a draw | `5b2/8/8/4k3/8/8/8/2B1K3 w - - 0 1` | — | status=insufficient_material; result=1/2-1/2 |
| G05 | Opposite-coloured bishops is NOT automatically a draw (mate is possible) | `2b5/8/8/4k3/8/8/8/2B1K3 w - - 0 1` | — | status=active |
| G06 | Two knights v king is NOT automatically a draw (mate is possible with help) | `8/8/8/4k3/8/8/1NN5/4K3 w - - 0 1` | — | status=active |
| G07 | King and pawn v king is sufficient | `8/8/8/4k3/8/8/4P3/4K3 w - - 0 1` | — | status=active |
| G08 | Capturing the last piece ends the game as insufficient material | `8/8/8/4k3/8/8/3n4/4K3 w - - 0 1` | — | after `e1d2` → status=insufficient_material, result=1/2-1/2 |

## 50/75-move rule

| ID | Situation | Start FEN | Moves first | Expectations |
|---|---|---|---|---|
| H01 | Halfmove clock 100: draw is claimable, game not over | `8/8/8/4k3/8/8/8/R3K3 w - - 100 80` | — | status=active; claim_fifty=True; claim_draw=True |
| H02 | Halfmove clock 99: not yet claimable before the move | `8/8/8/4k3/8/8/8/R3K3 w - - 98 80` | — | status=active; claim_fifty=False |
| H03 | Quiet move from clock 149 reaches 150: automatic 75-move draw | `8/8/8/4k3/8/8/8/R3K3 w - - 149 120` | — | after `a1a2` → status=seventyfive_moves, result=1/2-1/2 |
| H04 | A pawn move resets the clock (no 75-move draw) | `8/8/8/4k3/8/8/4P3/R3K3 w - - 149 120` | — | after `e2e3` → status=active |
| H05 | A capture resets the clock (no 75-move draw) | `8/8/8/4k3/8/8/r7/R3K3 w - - 149 120` | — | after `a1a2` → status=active, result=— |

## Repetition

| ID | Situation | Start FEN | Moves first | Expectations |
|---|---|---|---|---|
| I01 | Threefold repetition (knights out and back twice): claimable, not automatic | `rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1` | g1f3 g8f6 f3g1 f6g8 g1f3 g8f6 f3g1 f6g8 | status=active; claim_threefold=True; claim_draw=True |
| I02 | Only two occurrences: not claimable | `rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1` | g1f3 g8f6 f3g1 f6g8 | status=active; claim_threefold=False |
| I03 | Fivefold repetition ends the game automatically | `rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1` | g1f3 g8f6 f3g1 f6g8 … (16 plies: that 4-ply cycle ×4) | status=fivefold_repetition; result=1/2-1/2 |
| I04 | Same board but different castling rights is not the same position | `r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1` | e1f1 e8f8 f1e1 f8e8 e1f1 e8f8 f1e1 f8e8 | status=active; claim_threefold=False |

## Wrapper cases (`ChessGame.apply`, not python-chess)

These test our validation order: **turn → ply → format → legality**. The first failing check decides the error code.

| ID | Situation | Colour sending | UCI | Client ply | Expected error |
|---|---|---|---|---|---|
| W01 | Black tries to move when it is White's turn | black | `e7e5` | 0 | `NOT_YOUR_TURN` |
| W02 | Correct side but stale ply (client thinks 1 move played) | white | `e2e4` | 1 | `STALE_PLY` |
| W03 | Malformed UCI string | white | `e2-e4` | 0 | `BAD_FORMAT` |
| W04 | Null move '0000' is rejected as malformed | white | `0000` | 0 | `BAD_FORMAT` |
| W05 | Promotion to king is rejected as malformed | white | `a7a8k` | 0 | `BAD_FORMAT` |
| W06 | Well-formed but illegal move | white | `e2e5` | 0 | `ILLEGAL_MOVE` |
| W07 | Upper-case UCI is rejected (protocol is lower-case only) | white | `E2E4` | 0 | `BAD_FORMAT` |
| W08 | Castling written king-takes-rook (e1h1) is rejected; only e1g1 is canonical | white | `e1h1` | 0 | `ILLEGAL_MOVE` |
| W09 | Promotion suffix on a non-promotion move is illegal | white | `e2e4q` | 0 | `ILLEGAL_MOVE` |

## Notes discovered while verifying

- **Castling notation trap (W08).** python-chess treats `e1h1` (king-takes-rook) as a legal castling move in a standard game: `Move.from_uci("e1h1") in board.legal_moves` is `True`, and `board.parse_uci("e1h1")` normalises it to `e1g1`. The protocol accepts **only the canonical form** (`e1g1`, `e1c1`, `e8g8`, `e8c8`), so `ChessGame.apply` must check the submitted string against the set of `m.uci()` for legal moves rather than using `in board.legal_moves`. Otherwise two strings would mean one move, and the stored UCI history would be inconsistent.
- **Promotion stalemate (D05/F04/F05).** With only kings and one pawn there is no position where queening stalemates *and* rook-promotion mates; the catalogue uses the verified case where queening stalemates and rook-promotion keeps the game going.
- **Opposite-coloured bishops and two knights (G05/G06)** are *not* insufficient material in python-chess, because mate is possible (with the defender's cooperation). The game continues.
- **Capture resets the clock (H05).** Rook takes rook leaves K+R v K, which is sufficient material, so the game simply continues.
- **Mate beats the move counters (E07).** A mating move that also takes the halfmove clock to 100 ends the game as checkmate. The status order in `docs/protocol.md` §5 (checkmate checked first) guarantees this.
