# ADR-0010: Store player keys, not email addresses

**Status:** Accepted
**Date:** 2026-10-12

## Context
Storage, logs and fixtures shouldn't contain personal data, and changing an email address shouldn't need a data migration.

## Decision
Players are identified everywhere as `harry` or `partner`. The `PLAYERS_JSON` secret maps each key to `{email, name}`, where `name` is only the default display name: each player can type their own in the app (REQ-GAME-09), stored in the Lobby by key. The Worker converts the verified email to a key at the edge; nothing downstream sees the email.

## Consequences
- No PII in Durable Object storage, logs or test fixtures.
- Names and addresses change by updating one secret.
- Supersedes the `PLAYERS_JSON` example in build-plan H-05 and architecture §6.

## Alternatives considered
- Email as the identifier (original architecture): simpler on day one, leaks PII into storage and logs.
