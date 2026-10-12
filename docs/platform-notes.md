# Platform notes — verified facts

**Why this file exists:** Python Workers became generally available only in September 2026, so plausible-but-wrong API usage is the most likely source of bugs. Nothing about the platform goes into code unless it is in this file, with its evidence.

**Evidence levels**
- **[Docs]** stated in current Cloudflare documentation, with the page and the date checked.
- **[Tested]** reproduced by a command or test in our own environment.
- **[Inferred]** a reasonable conclusion not yet proven. Each one names the spike or test that will confirm it. **Never build on an [Inferred] line without that confirmation.**

**Last full review:** 12 October 2026. Re-check every line when changing `compatibility_date` or upgrading `workers-py`.

---

## 1. Versions to pin

| Item | Value | Evidence |
|---|---|---|
| python-chess (`chess` on PyPI) | **1.11.2** (latest on 12 Oct 2026) | [Tested] `pip index versions chess` |
| python-chess distribution | sdist only on PyPI. pywrangler installs Worker packages with `--no-build`, so an sdist can't be a dependency. **Vendored** as `src/chess/__init__.py` (unmodified 1.11.2 core) with its licence (ADR-0004). | [Tested] |
| `workers-py` (provides `pywrangler`) | **1.17.7**; `workers-runtime-sdk` **1.9.3** (both in `uv.lock`) | [Tested] installed 12 Oct 2026 |
| Wrangler (run by pywrangler via `npx --yes wrangler`, which uses the local copy) | **4.147.0**, pinned in `package.json` + `package-lock.json`; pywrangler needs ≥ 4.127.1 | [Tested] `pywrangler/utils.py` `MIN_WRANGLER_VERSION` |
| uv | pywrangler needs uv ≥ 0.12.3; CI pins **0.13.0** | [Tested] older uv failed `pywrangler sync` |
| `compatibility_date` | the date T-001 runs; never edited casually | [Docs] it selects the Pyodide/Python version |
| Compatibility flag | `python_workers` | [Docs] "You must add the `python_workers` compatibility flag" — `workers/languages/python/`, checked 12 Oct 2026 |
| Toolchain on CI | `uv` + Node.js | [Docs] pywrangler needs both |

## 2. Python Worker basics

| Fact | Evidence |
|---|---|
| Entry point is a class named `Default` extending `WorkerEntrypoint`, with `async def fetch(self, request)`. Imports: `from workers import WorkerEntrypoint, Response`. | [Docs] `workers/languages/python/basics/` (updated 22 Jun 2026) |
| Bindings, vars and secrets are attributes of `self.env` (e.g. `self.env.APP_ENV`, `self.env.LOBBY`). | [Docs] same page |
| `await request.json()` parses a JSON body; `Response.json(data)` returns JSON. | [Docs] same page |
| Code can be split across modules under `src/` and imported normally (`from chess_core.engine import ChessGame`). | [Docs] same page ("Modules") |
| Commands: `uv run pywrangler dev`, `uv run pywrangler deploy`, `uv run pywrangler types` (generates `Env` types). Upgrade: `uv lock --upgrade-package workers-py`. | [Docs] |
| `pywrangler init` creates `pyproject.toml` (with `workers-py` as a dev dependency) and the wrangler config. Packages come from `pyproject.toml`. | [Docs] |
| Supported packages: pure-Python packages from PyPI plus Pyodide-built packages. | [Docs] `workers/languages/python/packages/` |
| At deploy, Cloudflare runs the entry module **and everything it imports at top level**, then snapshots Wasm memory and boots requests from that snapshot. | [Docs] `how-python-workers-work/` (updated 9 Jul 2026) |
| Consequence: module top level must be deterministic and side-effect free. No network calls, no `random`, no `time`, no reading `env` there; such values would be frozen into the snapshot. | [Inferred] from the snapshot mechanism. Rule adopted regardless. |
| `threading` and `multiprocessing` import but don't work; `curses`, `dbm`, `pwd`, `venv` etc. are absent. The filesystem is in-memory and lost when the isolate dies. | [Docs] `workers/languages/python/stdlib/` |
| JS globals are importable via `from js import …`. Python dicts must be converted for JS APIs with `to_js(obj, dict_converter=Object.fromEntries)` (from `pyodide.ffi`). JS promises are awaited with `await`. | [Docs] `workers/languages/python/ffi/` |
| Python versions arrive yearly behind a compatibility date; old ones keep working but may get slower. | [Docs] `how-python-workers-work/` |

## 3. Static assets

| Fact | Evidence |
|---|---|
| `assets.directory`, `assets.binding`, `assets.not_found_handling = "single-page-application"`, `assets.run_worker_first` (bool or array of globs; `!` negates; max 100 entries). | [Docs] `workers/static-assets/binding/` (updated 4 Sep 2026) |
| Without `run_worker_first`, a request matching an asset is served **without invoking the Worker**. | [Docs] same page |
| `env.ASSETS.fetch(url)` serves an asset; any hostname works, only the path matters. **`html_handling` applies to these fetches too**: with the default `auto-trailing-slash`, `/game.html` answers 307 → `/game`, and `/game` serves `game.html`. So the Worker fetches `https://assets.local/game` (no extension). | [Docs] `workers/static-assets/binding/` + `routing/static-site-generation/` (checked 12 Oct 2026) |
| Requests for static assets are free and unlimited. | [Docs] Workers pricing page |
| **Design implication:** SPA fallback would serve `index.html` for `/game/{id}`. So `run_worker_first` = `["/api/*", "/ws/*", "/game/*", "/healthz", "/diag"]` (no `not_found_handling`, so no SPA fallback), and the Worker answers `/game/*` with `ASSETS.fetch("https://assets.local/game")` after JWT checks. Everything else (CSS, JS, icons) is served straight from assets, still behind Access. | Decision (recorded in ADR-0006 notes) |

## 4. Durable Objects (Python)

| Fact | Evidence |
|---|---|
| `from workers import DurableObject`; `class GameRoom(DurableObject): def __init__(self, ctx, env): super().__init__(ctx, env)`. | [Docs] `durable-objects/api/sqlite-storage-api/` (updated 21 Sep 2026) |
| Free plan: SQLite-backed classes only (`new_sqlite_classes` in `migrations`). | [Docs] DO pricing and limits |
| `ctx.storage.sql.exec(query, *bindings)` returns a cursor; `?` placeholders; methods `toArray()`, `one()` (throws unless exactly one row), `raw()`, `next()`; properties `rowsRead`, `rowsWritten`, `columnNames`. | [Docs] same page |
| Multiple statements are allowed in one `exec`; bindings apply only to the last statement. | [Docs] |
| **Consume cursors before any `await`**; a cursor held across an `await` has no snapshot isolation. | [Docs] |
| `exec` cannot run `BEGIN`/`SAVEPOINT`. Use `ctx.storage.transactionSync(callback)` (synchronous callback only) when several writes must commit together. Writes with no `await` between them are already committed atomically. | [Docs] |
| Integers come back through JS numbers (52-bit precision). Epoch milliseconds are safe. | [Docs] |
| Point-in-time recovery to any point in the last 30 days (`getBookmarkForTime`, `onNextSessionRestoreBookmark`), not available in local dev. | [Docs] |
| Free plan limits: 5 GB per account, 1 GB per object; 100 classes per account. | [Docs] DO limits page |
| Worker → DO: `stub = self.env.GAME_ROOM.getByName(game_id)`; `await stub.fetch(request)` (shown in the Python Worker example). RPC methods on DOs are supported from compatibility date 2024-04-03. | [Docs] `durable-objects/best-practices/websockets/` (updated 30 Sep 2026) |
| Calling Python RPC methods on a Python DO from a Python Worker (argument and return conversion). | [Inferred] → confirm in S-02. Until confirmed, the Worker talks to DOs only through `stub.fetch()`. |

## 5. WebSockets with hibernation (Python)

| Fact | Evidence |
|---|---|
| Accept in the DO: `from js import WebSocketPair`; `client, server = WebSocketPair.new().object_values()`; `self.ctx.acceptWebSocket(server)`; `return Response(None, status=101, web_socket=client)`. | [Docs] Python example, websockets page (30 Sep 2026) |
| Handlers: `async def webSocketMessage(self, ws, message)`, `async def webSocketClose(self, ws, code, reason, was_clean)`. | [Docs] same |
| Listing sockets: the **Python** example calls `self.ctx.get_websockets()`; the JS API is `getWebSockets()`. | [Docs] — discrepancy. [Inferred] one or both work → S-02 confirms which; use only that one. |
| `acceptWebSocket(ws, tags)` with tags, and `getWebSockets(tag)` filtering. | [Docs] JS API (`durable-objects/api/state/`). Python argument form [Inferred] → S-02. |
| `ws.serializeAttachment(value)` / `ws.deserializeAttachment()`: survives hibernation while the socket is healthy, lost on close, structured-clone types, **max 16,384 bytes**. We store a JSON string `{"player": "...", "colour": "..."}`. | [Docs] |
| After hibernation the constructor runs again and in-memory state is reset. Keep the constructor minimal. | [Docs] |
| Alarms, incoming requests, `setTimeout`/`setInterval` and open outbound sockets prevent or delay hibernation. | [Docs] |
| WebSocket protocol ping frames are answered automatically without waking the DO; `webSocketMessage` is not called for control frames. | [Docs] |
| With compatibility date ≥ 2026-04-07 (`web_socket_auto_reply_to_close`) the runtime auto-replies to Close frames; calling `ws.close()` is still safe. | [Docs] |
| **Every deploy disconnects all WebSockets** (all DOs restart). | [Docs] "WebSocket disconnection on deploy" |
| Local dev delivers hibernation events, but eviction can't be forced on demand. | [Docs] + [Inferred]. Tests therefore exercise the rebuild path explicitly (see `docs/test-plan.md` §4.3). |
| Validate in the Worker before calling the DO (each DO request is billed/counted). | [Docs] |

## 6. Cloudflare Access JWT

| Fact | Evidence |
|---|---|
| Access adds `Cf-Access-Jwt-Assertion` to requests; browsers also get a `CF_Authorization` cookie. **Validate the header**, because the cookie isn't guaranteed to be passed. | [Docs] `cloudflare-one/.../validating-json/` (updated 6 May 2026) |
| Signing keys: `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs` → `keys` (JWK, `kty` RSA, `alg` RS256, `kid`), `public_cert`, `public_certs`. | [Docs] |
| Keys rotate every 6 weeks; the previous key stays valid for 7 days. Match the token's `kid` against `keys`; don't read `public_cert` (it can be stale in caches). | [Docs] |
| Check `iss == https://<team>.cloudflareaccess.com` and `aud` contains the app's AUD tag. The AUD tag never changes unless the Access app is deleted and recreated. | [Docs] |
| Payload carries the user's `email`. | [Docs] |
| RS256 verification via WebCrypto (`crypto.subtle.importKey("jwk", …, {name: "RSASSA-PKCS1-v1_5", hash: "SHA-256"}, …)` then `verify`) from Python through the JS bridge. | [Inferred] → S-03. Fallback: `cryptography` from Pyodide's package set. |
| Free Zero Trust plan covers up to 50 users with one-time PIN login. | [Docs]/press, checked 12 Oct 2026 |
| Service tokens for CI on the free plan. | Unknown → Harry checks in H-04. |

## 7. Email

| Fact | Evidence |
|---|---|
| Binding: `"send_email": [{"name": "EMAIL", "allowed_destination_addresses": [...]}]`. Other restriction attributes: `destination_address`, `allowed_sender_addresses`. | [Docs] `email-service/configuration/send-bindings/` |
| `await env.EMAIL.send({to, from, subject, text, html, replyTo, headers, ...})` returns `{messageId}`. Errors carry `.code`, e.g. `E_RECIPIENT_NOT_ALLOWED`, `E_SENDER_NOT_VERIFIED`, `E_SENDER_DOMAIN_NOT_AVAILABLE`, `E_RATE_LIMIT_EXCEEDED`, `E_DAILY_LIMIT_EXCEEDED`, `E_DELIVERY_FAILED`. Max 50 recipients; 5 MiB total. | [Docs] `email-service/api/send-emails/workers-api/` (updated 16 Sep 2026) |
| Sending to **verified destination addresses** is free on all plans (including with only Email Routing configured) and doesn't count against the quota. Sending to arbitrary recipients needs Workers Paid. | [Docs] `email-service/platform/pricing/` |
| Local dev simulates the binding unless the binding has `remote: true`. | [Docs]/guide |
| Calling `send` from Python needs the message dict converted with `to_js(..., dict_converter=Object.fromEntries)`. | [Inferred] → S-05 |
| Enabling Email Routing changes the zone's MX records. | [Docs] — Harry checks first (H-06) |

## 8. Limits that shape the code (Workers Free)

| Limit | Value | Evidence |
|---|---|---|
| CPU time per invocation | 10 ms (network waits don't count) | [Docs] Workers limits |
| Requests | 100,000/day; burst 1,000/min | [Docs] |
| Subrequests per request | 50 | [Docs] |
| Exceeding CPU | Error 1102 "Worker exceeded resource limits"; shown as *Exceeded CPU Time Limits* in metrics | [Docs] |
| Overruns on Free | Fail with errors; never billed | [Docs] DO pricing |

## 9. Measurements from our own workspace

CPython 3.13 on the build workspace, python-chess 1.11.2, 12 October 2026. Pyodide in Workers will be slower by an unknown factor; **S-04 measures the real numbers on staging.**

| Operation | Median | p95 |
|---|---|---|
| Hot path: `Board(fen)` + list legal moves + mate/stalemate/insufficient checks | 0.08 ms | 0.12 ms |
| Full replay of a 131-ply game + fivefold + threefold + legal moves | 1.83 ms | 3.05 ms |

Conclusion: the hot path has huge headroom. Full replay is the only thing that could approach 10 ms under Wasm, which is why ADR-0007 removes replay from the hot path.

## 10. python-chess behaviours we rely on

| Behaviour | Evidence |
|---|---|
| `Move.from_uci("e1h1") in board.legal_moves` is **True** in a standard game, and `parse_uci("e1h1")` normalises to `e1g1`. So the legality check must compare against the set of `m.uci()` strings. | [Tested] catalogue W08 |
| `board.fen()` shows the en-passant square only when a legal en-passant capture exists. | [Tested] indirectly by the repetition check below |
| Repetition key = first four FEN fields (placement, side, castling, ep). Counting these keys gives the same answer as `board.is_repetition(3)` and `board.is_fivefold_repetition()`. | [Tested] 77,044 positions across 400 random games plus castling-rights and en-passant edge sequences: 0 mismatches |
| Opposite-coloured bishops and K+N+N v K are **not** insufficient material. | [Tested] catalogue G05, G06 |
| `can_claim_draw()` includes claims "by the next move"; our v1 rule (REQ-RULE-08) is current-position only. Use `halfmove_clock >= 100` or the repetition count ≥ 3, not `can_claim_draw()`. | [Docs] python-chess + REQ-RULE-08 |

## 11. Change log

| Date | Change |
|---|---|
| 2026-10-12 | First version, written before T-001. |


## 10. Recorded while building (12 Oct 2026)

Facts below were read from the installed SDK source (`.venv/lib/python3.13/site-packages/workers/`, workers-runtime-sdk 1.9.3) or from Cloudflare docs. The real runtime can't run in Claude's workspace (the Pyodide package index and runtime downloads are blocked), so CI's `pywrangler dev` jobs are the [Tested] confirmation for glue code.

| Fact | Evidence |
|---|---|
| `Response(body, status=101, web_socket=client)` is how a Durable Object returns the client end of a `WebSocketPair`. | [Docs] + SDK `response.py` |
| `env.GAME_ROOM.getByName(name)` returns a `_FetcherWrapper`; its `.fetch(request)` is a coroutine (SDK `fetch(..., fetcher=binding.fetch)`), so `await stub.fetch(js_request)` is right. | SDK `rpc.py` |
| `self.ctx.storage` is wrapped in `_BindingWrapper` (Python↔JS conversion on calls); other `ctx` attributes such as `acceptWebSocket` and `getWebSockets` are the raw JS functions. `ctx.storage.sql.exec(...).toArray()` comes back as Python lists of dicts, JS `null` → `None`. | SDK `entrypoints.py` (`DurableObjectContext.__getattr__`), `rpc.py` |
| `ctx.storage.transactionSync(fn)` takes a Python callable. | SDK `rpc.py` conversion + docs |
| There is no snake_case `get_websockets`; use `ctx.getWebSockets()`. | SDK source |
| Hibernation handlers: `webSocketMessage(ws, message)`, `webSocketClose(ws, code, reason, was_clean)`, `webSocketError(ws, error)`; per-socket data via `ws.serializeAttachment(str)` / `ws.deserializeAttachment()` (≤ 16 KB). | [Docs] `durable-objects/best-practices/websockets/` |
| A pyodide `FetchResponse.json()` is a coroutine but untyped; the Worker reads `json.loads(await response.text())` instead so types check. | SDK `response.py` |
| `wrangler deploy --secrets-file <json>` uploads secrets with the code in one version; secrets not in the file are kept. | [Docs] `workers/configuration/secrets/` (checked 12 Oct 2026) |
| Access's `CF_Authorization` cookie defaults to `SameSite=None`, so state-changing endpoints need their own CSRF guard (protocol §2.11). | [Docs] `cloudflare-one/identity/authorization-cookie/` (found by the 12 Oct audit) |
| Chromium launched with `--single-process` shares one cookie jar between Playwright contexts for WebSocket handshakes; never use that flag in e2e tests. | [Tested] in the workspace |
