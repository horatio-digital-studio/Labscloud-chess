# ADR-0005: Thin vanilla-JS view, hand-rolled board

**Status:** Accepted (revised 12 October 2026 when the board was built)
**Date:** 2026-10-12

## Context
Browsers run JavaScript. Harry wants Python, not TypeScript. The page has to open quickly on an iPhone while FaceTime is running. Harry chose design option A ("Clubroom": walnut, brass, a wooden board with Unicode pieces and serif headings).

## Decision
Write the browser side as plain ES-module JavaScript with no build step and **no third-party JS at all**. The board is hand-rolled (`public/js/board.js`, ~450 lines): 64 buttons in a CSS grid, tap-tap and pointer-event drag, a promotion picker, roving-tabindex keyboard control and ARIA labels. Pieces are the Unicode chess glyphs drawn from a self-hosted 2.8 KB subset of Noto Sans Symbols 2. Fonts (Cormorant Garamond, Source Sans 3) are self-hosted from `@fontsource` (OFL). Everything is served from the Worker's static assets; no runtime CDN.

The original plan was to vendor `cm-chessboard`. Dropped because option A's look (Unicode glyph pieces with outlined white pieces, brass highlights, ring/dot targets) would have meant restyling most of it, and owning the ~450 lines keeps the CSP strict (no inline styles) and the accessibility behaviour under our control.

## Consequences
- Small download (fonts ~95 KB, JS ~45 KB unminified), instant start, strict CSP (`script-src 'self'; style-src 'self'`).
- No Node build for the frontend; Node is used only for `node --test` and to pin Wrangler.
- Board behaviour is tested by node unit tests (pure helpers in `board-model.js`, `format.js`, `socket.js`) and Playwright e2e tests.
- The client still decides nothing about legality: it only reads the server's `legal` list (REQ-UI-14).

## Alternatives considered
- `cm-chessboard` (MIT): good library, but restyling it to option A was more work than writing the board.
- PyScript / Pyodide in the browser: multi-megabyte runtime per device, slow on phones.
- TypeScript + bundler: explicitly not wanted.
