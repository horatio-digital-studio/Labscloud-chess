# ADR-0002: One Durable Object per game, with hibernating WebSockets

**Status:** Accepted — Python API details pending S-02
**Date:** 2026-10-12

## Context
A chess game is a small, strongly consistent, single-writer state machine with two live connections that must see the same moves in the same order.

## Decision
Each game is a `GameRoom` Durable Object (SQLite-backed) that owns the authoritative state, accepts both players' WebSockets through the Hibernation API, and broadcasts full `state` snapshots. A singleton `Lobby` object holds preferences and a summary index.

## Consequences
- Moves are totally ordered per game with no locking code.
- Idle games cost nothing; sockets stay open while the object sleeps.
- In-memory state can vanish at any time, so all handlers must rebuild from SQLite (tested by running the integration suite with forced rebuild).
- Every deploy disconnects all sockets; clients reconnect automatically.

## Alternatives considered
- KV: eventually consistent, unsuitable for moves.
- D1: would need a separate real-time channel.
- Non-hibernating WebSockets: fallback if S-02 finds a Python limitation.
