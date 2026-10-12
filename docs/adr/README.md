# Architecture decision records

One page per decision. Status is `Proposed`, `Accepted`, `Superseded by ADR-NNNN` or `Rejected`. A decision changes only through a new or updated ADR, never silently in code.

| ADR | Decision | Status |
|---|---|---|
| [ADR-0001](0001-host-on-cloudflare-workers.md) | Host on Cloudflare Workers, not the Pi or a VPS | Accepted |
| [ADR-0002](0002-durable-objects-for-game-state.md) | One Durable Object per game, with hibernating WebSockets | Accepted — Python API details pending S-02 |
| [ADR-0003](0003-cloudflare-access-otp-login.md) | Cloudflare Access one-time PIN for login | Accepted — WebCrypto verification pending S-03 |
| [ADR-0004](0004-server-authoritative-python-chess.md) | Server-authoritative rules with python-chess | Accepted — Pyodide packaging pending S-01 |
| [ADR-0005](0005-vanilla-js-view-layer.md) | Thin vanilla-JS view with vendored dependencies | Accepted |
| [ADR-0006](0006-subdomain-and-worker-first-routes.md) | Serve on `chess.labscloud.uk` with Worker-first routes | Accepted |
| [ADR-0007](0007-repetition-counts-no-replay.md) | Track repetition counts; never replay moves on the hot path | Accepted — CPU numbers pending S-04 |
| [ADR-0008](0008-email-to-verified-destinations.md) | Send email only to verified destination addresses | Accepted — Python call pending S-05 |
| [ADR-0009](0009-delivery-pipeline.md) | Build in the cloud workspace, test and deploy via GitHub Actions | Accepted |
| [ADR-0010](0010-player-keys-not-emails.md) | Store player keys, not email addresses | Accepted |
| [ADR-0011](0011-takebacks-from-stored-positions.md) | Takebacks restore stored positions; nothing is replayed | Accepted |

## Template

```markdown
# ADR-NNNN: <decision in a few words>

**Status:** Proposed
**Date:** YYYY-MM-DD

## Context
What forces are at play, with evidence.

## Decision
What we will do.

## Consequences
What gets easier, what gets harder, what must now be tested.

## Alternatives considered
What else, and why not.
```
