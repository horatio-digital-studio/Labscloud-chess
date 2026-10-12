## What and why

<!-- Task ID(s) and requirement IDs (REQ-…) this covers. One short paragraph. -->

## Plan

<!-- The approach, in a few bullets. -->

## Definition of Done

- [ ] Acceptance criteria met and traced to REQ IDs in `tests/traceability.json`
- [ ] Tests written first; `uv run ./scripts/check.sh` green
- [ ] CI green: unit, contract, integration (dev server + pywrangler dev), browser (Chromium + WebKit), bundle dry-run
- [ ] No tests removed or weakened
- [ ] Versions pinned (uv.lock, package-lock.json, action SHAs)
- [ ] Docs updated (progress, tasks, CHANGELOG; ADR if a decision changed)
- [ ] UI change: CI screenshots reviewed; staging `/healthz` shows this commit
