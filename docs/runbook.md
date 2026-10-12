# Runbook — labscloud-chess

For Harry. Everything here works from a phone or tablet browser: the Cloudflare dashboard, GitHub, or a chat with Claude. No terminal and no PC needed.

**Status:** v1 draft — 12 October 2026. Finalised and checked on a phone in T-042.

---

## 1. Where things live

| Thing | Where |
|---|---|
| Code, issues, CI runs, releases | GitHub → `labscloud-chess` (private) |
| Production | `https://chess.labscloud.uk` |
| Staging | `https://chess-staging.labscloud.uk` |
| Health check (no login) | `…/healthz` on either hostname |
| Workers, logs, metrics | Cloudflare dashboard → **Workers & Pages** → `labscloud-chess` / `labscloud-chess-staging` |
| Login policy (who can sign in) | Cloudflare **Zero Trust** → Access → Applications |
| Email sending | Cloudflare → `labscloud.uk` → **Email** → Email Routing |
| Secrets used by deploys | GitHub repo → Settings → Secrets and variables → Actions |

## 2. Everyday operations

### Release to production ("ship it")
1. Check staging `/healthz` shows the commit you tested, and the UAT script passed (build plan Part E).
2. Tell Claude "ship it". Claude creates tag `vX.Y.Z`; the **Deploy production** workflow runs.
3. Open `https://chess.labscloud.uk/healthz` and confirm `version` and `commit`.
4. Note: **every deploy briefly disconnects open games**; boards reconnect by themselves within a few seconds.

### Roll back
1. GitHub → **Actions** → **Rollback production** → *Run workflow* → enter the previous tag (e.g. `v0.1.0`).
2. Wait for green, then check `/healthz` shows the old version.
3. Data is not rolled back: games keep their state. Schema changes are additive, so older code can read newer data.

### Report a bug
GitHub → **Issues** → **New issue** → **Bug report**. Fill in device, what you did, what you expected, what happened, and attach a screenshot. Include the game link if it happened in a game.

### Check logs or errors
Cloudflare → Workers & Pages → the worker → **Logs** (or **Metrics** for error counts and CPU time). Logs show player keys (`harry`/`partner`), never emails.

## 3. Account changes

### Change an email address or display name
1. GitHub → Settings → Secrets → **`PLAYERS_JSON`** → Update. Format:
   ```json
   {"harry": {"email": "you@example.com", "name": "Harry"},
    "partner": {"email": "them@example.com", "name": "Name"}}
   ```
2. Zero Trust → Access → Applications → both apps → policy → update the email list.
3. If email notifications are on: Email Routing → add and verify the new destination address.
4. Ask Claude to redeploy (or re-run the latest deploy workflow) so the Worker picks up the new secret.
Game history is unaffected because it stores `harry`/`partner`, not addresses.

### Rotate the Cloudflare API token
1. Cloudflare → My Profile → **API Tokens** → roll or create a new token (template *Edit Cloudflare Workers*, scoped to the account and `labscloud.uk`).
2. GitHub → Secrets → update `CLOUDFLARE_API_TOKEN`.
3. Delete the old token in Cloudflare.
4. Re-run the staging deploy to prove it works.

### Sign everyone out
Zero Trust → Access → Applications → the app → **Revoke existing tokens**. The next visit asks for a new PIN.

## 4. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| PIN email doesn't arrive | Spam folder, or address not in the Access policy | Check spam; add the Access sender to contacts; confirm the address in the Access policy matches exactly. |
| "Forbidden" after logging in | Email in Access policy but not in `PLAYERS_JSON` (or vice versa) | Make the two lists match (§3). |
| Board stuck on "Reconnecting…" | Phone offline, or a deploy in progress | Wait 10 s; pull to refresh; check `/healthz`. If `/healthz` fails, check Cloudflare Workers metrics and tell Claude. |
| Moves rejected with "board was out of date" | Two devices or a slow network | It resyncs automatically; if it repeats, report a bug with both devices listed. |
| `/healthz` shows an old commit after a deploy | Workflow failed or still running | GitHub → Actions → open the latest run and check the failed step; tell Claude. |
| Error 1102 / "Worker exceeded resource limits" | CPU limit hit | Note the game link and time; tell Claude (this is risk R1; ADR-0007 mitigates it). |
| Invites or nudges not arriving (Phase 6) | Address not verified in Email Routing, or notifications turned off | Check Email Routing destinations show *Verified*; check the lobby settings. |
| Game lost or corrupted | Shouldn't happen | Tell Claude immediately. Durable Objects keep 30 days of point-in-time recovery. |

## 5. Costs check (monthly, 2 minutes)

Cloudflare → Workers & Pages → **Plans**: still *Free*. Billing → no payment method required, no invoices. GitHub → Settings → Billing → Actions minutes well inside the free allowance. If anything ever shows a charge, stop and tell Claude: the design is meant to be £0 (REQ-NFR-01).

## 6. Emergency: take the site offline

Zero Trust → Access → the app → policy → remove both emails (nobody can sign in), or Cloudflare → Workers & Pages → the worker → Settings → **Domains & Routes** → remove the custom domain. Both are reversible in seconds.

## 4. Secrets the deploy workflows need

GitHub repo → **Settings → Secrets and variables → Actions → Repository secrets**:

| Secret | What | Used for |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | API token from the *Edit Cloudflare Workers* template, scoped to your account and `labscloud.uk` | Deploying |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare dashboard → any zone → right-hand column *Account ID* | Deploying |
| `PLAYERS_JSON` | `{"harry": {"email": "…", "name": "Harry"}, "partner": {"email": "…", "name": "…"}}` | Who may play |
| `ACCESS_TEAM_DOMAIN` | `https://<team>.cloudflareaccess.com` | Checking login tokens |
| `ACCESS_AUD_STAGING` | AUD tag of the `chess-staging.labscloud.uk` Access app | Checking login tokens (staging) |
| `ACCESS_AUD_PROD` | AUD tag of the `chess.labscloud.uk` Access app | Checking login tokens (production) |

If a deploy fails at **Write Worker secrets file**, the error names the missing secret. If it fails at **Smoke test /healthz**, check the Access app has a **Bypass** policy for `/healthz` (H-04). If it fails at **Deploy** with a permissions error about custom domains, edit the API token and add *Zone → Workers Routes → Edit* and *Zone → DNS → Edit* for `labscloud.uk`.

After the first deploy of each environment, open the site on your phone once: the smoke test can only see `/healthz`, so a wrong AUD tag would show up as "Please sign in again" on every page.
