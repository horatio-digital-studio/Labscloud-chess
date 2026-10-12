# ADR-0008: Send email only to verified destination addresses

**Status:** Accepted — Python call pending S-05
**Date:** 2026-10-12

## Context
Invites and "your move" nudges need email. Cloudflare Email Service charges for sending to arbitrary recipients, but sending to verified destination addresses in the account is free on all plans.

## Decision
Enable Email Routing on `labscloud.uk`, verify both players' addresses as destinations, and use a `send_email` binding restricted with `allowed_destination_addresses` and `allowed_sender_addresses = ["chess@labscloud.uk"]`. Email failures are logged and never affect game state.

## Consequences
- £0 for email.
- Only the two players can ever be emailed, enforced by the binding as well as our code.
- Enabling Email Routing changes the zone's MX records, so Harry checks for existing mail on `@labscloud.uk` first.

## Alternatives considered
- Third-party email API free tiers: another account and API key to manage; kept as the fallback if S-05 fails.
