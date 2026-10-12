# ADR-0003: Cloudflare Access one-time PIN for login

**Status:** Accepted — WebCrypto verification pending S-03
**Date:** 2026-10-12

## Context
Harry asked for each player to "get a login via email". There are exactly two users. Home-grown authentication is the riskiest code in most projects.

## Decision
Put both hostnames behind Cloudflare Access with the one-time-PIN method and an allow-list of the two emails. The Worker additionally verifies the signed `Cf-Access-Jwt-Assertion` (RS256, `kid`-matched keys, `aud`, `iss`, `exp`) and maps the email to a player key. `/healthz` alone has an Access Bypass policy so CI can smoke-test deploys.

## Consequences
- Zero auth UI or token storage to maintain; free for up to 50 users.
- Requests from anyone else never reach our code.
- CI can't play a game against staging unless service tokens are available on the free plan (unknown until H-04); `/diag` from Harry's phone covers that gap.

## Alternatives considered
- Self-built magic links (architecture Appendix C): more code, more risk, same user experience.
