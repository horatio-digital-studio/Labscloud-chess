# ADR-0009: Build in the cloud workspace, test and deploy via GitHub Actions

**Status:** Accepted
**Date:** 2026-10-12

## Context
Harry doesn't want anything built or tested on his PC. Claude's workspace has restricted network access and may not run the full local Workers runtime.

## Decision
Claude writes code and runs the pure-Python gates in its workspace, then pushes branches to a private GitHub repo. GitHub Actions runs everything (including `pywrangler dev` integration tests and Playwright e2e), deploys `main` to staging, and deploys `v*` tags to production. A manual workflow rolls back to a previous tag.

## Consequences
- Harry's involvement is setup clicks and phone testing.
- Slower feedback for integration-level bugs than local testing; mitigated by keeping most logic in pure Python.
- Tag-based releases avoid paid GitHub environment-protection features.

## Alternatives considered
- Deploy from the workspace: likely blocked by the network allowlist, and would bypass CI.
