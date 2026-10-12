# Changelog

All notable changes to labscloud-chess. Versions follow `vMAJOR.MINOR.PATCH`; production deploys only from tags.

## [Unreleased]

### Added
- The application: Python Worker + GameRoom/Lobby Durable Objects, Access JWT login, lobby with name box, head-to-head, new game, game lists and email settings; live board (option A "Clubroom") with tap/drag/keyboard input, promotion picker, resign confirmation, draw offer/claim, takebacks, rematch, PGN download, connection status and reconnect; diagnostics page for staging.
- Development server and tests: unit, property (P1–P7), contract, integration, browser (Playwright), JS unit tests.
- GitHub Actions: CI, staging deploy on `main`, production deploy on `v*` tags, manual rollback.
- Planning and specification documents: architecture, build plan, requirements, protocol and JSON Schema, data model, test plan and traceability, platform notes, verified rules catalogue, UI spec, ADRs 0001–0011, runbook, email copy.
- Four visual design options (A Clubroom, B Midnight, C Broadsheet, D Sunday) on the design canvas.

## Planned

- **v0.1.0** — production launch: login, lobby, live games, all chess rules, player-chosen display names, resign/draw/claim/takeback/rematch, PGN, stats (Phases 0–5).
- **v0.2.0** — email invites, "your move" nudges (on/off switch + gap timer) and game-over emails (Phase 6).
