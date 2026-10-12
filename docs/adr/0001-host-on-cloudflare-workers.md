# ADR-0001: Host on Cloudflare Workers, not the Pi or a VPS

**Status:** Accepted
**Date:** 2026-10-12

## Context
The game must be free to run, must not depend on Harry's Raspberry Pi or home broadband, and has to serve two players at opposite ends of the country with low latency. `labscloud.uk` DNS is already on Cloudflare.

## Decision
Run everything on Cloudflare's free tier: a Python Worker, Durable Objects with SQLite storage, Workers Static Assets, Cloudflare Access and Email Service.

## Consequences
- £0/month; free-tier overruns produce errors rather than bills.
- No servers to patch; both players reach a nearby edge location.
- We depend on a platform where Python only became generally available in September 2026, so `docs/platform-notes.md` and the Phase 1 spikes exist to contain that risk.
- `chess_core` stays plain Python, so the game could move to a conventional host later with little rework.

## Alternatives considered
- Raspberry Pi behind the existing tunnel: rejected by Harry (no home dependency).
- Free container/VM tiers: tend to sleep idle apps (slow first move) and change terms more often.
